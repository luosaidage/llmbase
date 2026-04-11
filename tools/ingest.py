"""Ingest module: collect raw documents into the raw/ directory."""

import hashlib
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import frontmatter
import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from .config import load_config, ensure_dirs


def _validate_url(url: str):
    """Block SSRF: reject private/internal network URLs."""
    import ipaddress, socket
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    hostname = parsed.hostname or ""
    if not hostname:
        raise ValueError("No hostname in URL")
    # Block obvious internal hostnames
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "[::]", "[::1]"):
        raise ValueError(f"Blocked internal hostname: {hostname}")
    # Resolve and check for dangerous private IP ranges
    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if addr.is_loopback or addr.is_link_local:
                raise ValueError(f"Blocked loopback/link-local IP: {addr}")
            # Block common internal ranges (cloud metadata, RFC1918)
            blocked_nets = [
                ipaddress.ip_network("10.0.0.0/8"),
                ipaddress.ip_network("172.16.0.0/12"),
                ipaddress.ip_network("192.168.0.0/16"),
                ipaddress.ip_network("169.254.0.0/16"),  # AWS/GCP metadata
            ]
            for net in blocked_nets:
                if addr in net:
                    raise ValueError(f"Blocked internal IP: {addr}")
    except socket.gaierror:
        pass  # DNS resolution failed — let requests handle it


def ingest_url(url: str, base_dir: Path | None = None) -> Path:
    """Fetch a web article and save as markdown with images downloaded locally."""
    _validate_url(url)
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    raw_dir = Path(cfg["paths"]["raw"])

    # Fetch page
    resp = requests.get(url, timeout=30, headers={"User-Agent": "LLMBase/1.0"}, allow_redirects=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract title
    title = soup.title.string.strip() if soup.title and soup.title.string else urlparse(url).netloc
    slug = _slugify(title)

    # Create directory for this document
    doc_dir = raw_dir / slug
    doc_dir.mkdir(parents=True, exist_ok=True)
    images_dir = doc_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # Extract main content (try article tag, then body)
    article = soup.find("article") or soup.find("main") or soup.body
    if article is None:
        article = soup

    # Download images and rewrite URLs
    for img in article.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        try:
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                parsed = urlparse(url)
                src = f"{parsed.scheme}://{parsed.netloc}{src}"
            img_resp = requests.get(src, timeout=15)
            img_resp.raise_for_status()
            ext = _guess_ext(src, img_resp.headers.get("content-type", ""))
            img_hash = hashlib.md5(src.encode()).hexdigest()[:8]
            img_name = f"{img_hash}{ext}"
            img_path = images_dir / img_name
            img_path.write_bytes(img_resp.content)
            img["src"] = f"images/{img_name}"
        except Exception:
            pass  # Skip failed image downloads

    # Convert to markdown (handle deeply nested HTML)
    import sys
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(10000)
    try:
        html_str = str(article)
        # Truncate extremely large pages
        if len(html_str) > 500000:
            html_str = html_str[:500000]
        content = md(html_str, heading_style="ATX", strip=["script", "style", "nav"])
    except RecursionError:
        # Fallback: extract text directly
        content = article.get_text(separator="\n\n", strip=True)
    finally:
        sys.setrecursionlimit(old_limit)

    # Create frontmatter
    post = frontmatter.Post(content)
    post.metadata["title"] = title
    post.metadata["source"] = url
    post.metadata["ingested_at"] = datetime.now(timezone.utc).isoformat()
    post.metadata["type"] = "web_article"
    post.metadata["compiled"] = False

    doc_path = doc_dir / "index.md"
    doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")

    from .hooks import emit
    emit("ingested", source="web", url=url, title=title, path=str(doc_path))

    return doc_path


def ingest_file(file_path: str, base_dir: Path | None = None) -> Path:
    """Copy a local file (paper PDF, markdown, etc.) into raw/."""
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    raw_dir = Path(cfg["paths"]["raw"])

    src = Path(file_path)
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {file_path}")

    slug = _slugify(src.stem)
    doc_dir = raw_dir / slug
    doc_dir.mkdir(parents=True, exist_ok=True)

    dest = doc_dir / src.name
    shutil.copy2(src, dest)

    # If it's already a markdown file, add frontmatter if missing
    if src.suffix.lower() in (".md", ".markdown"):
        post = frontmatter.load(str(dest))
        if "title" not in post.metadata:
            post.metadata["title"] = src.stem
        if "ingested_at" not in post.metadata:
            post.metadata["ingested_at"] = datetime.now(timezone.utc).isoformat()
        post.metadata["type"] = "local_file"
        post.metadata["compiled"] = False
        dest.write_text(frontmatter.dumps(post), encoding="utf-8")
    else:
        # Create a companion metadata file
        meta = frontmatter.Post("")
        meta.metadata["title"] = src.stem
        meta.metadata["source"] = str(src.resolve())
        meta.metadata["ingested_at"] = datetime.now(timezone.utc).isoformat()
        meta.metadata["type"] = "local_file"
        meta.metadata["file"] = src.name
        meta.metadata["compiled"] = False
        meta_path = doc_dir / "index.md"
        meta_path.write_text(frontmatter.dumps(meta), encoding="utf-8")

    from .hooks import emit
    emit("ingested", source="file", title=src.stem, path=str(dest))

    return dest


def ingest_directory(dir_path: str, base_dir: Path | None = None) -> list[Path]:
    """Ingest all supported files from a directory."""
    src_dir = Path(dir_path)
    if not src_dir.is_dir():
        raise NotADirectoryError(f"Not a directory: {dir_path}")

    results = []
    supported = {".md", ".markdown", ".txt", ".pdf", ".py", ".json", ".csv"}
    for f in sorted(src_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in supported:
            results.append(ingest_file(str(f), base_dir))
    return results


def _safe_meta_value(v):
    """Coerce a frontmatter value to a JSON-safe type, redacting local paths."""
    if v is None:
        return v
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, str):
        return None if _is_local_path(v) else v
    if isinstance(v, (list, tuple)):
        return [x for x in (_safe_meta_value(i) for i in v) if x is not None]
    if isinstance(v, dict):
        return {str(k): sv for k, sv in ((str(k), _safe_meta_value(val)) for k, val in v.items()) if sv is not None}
    s = str(v)
    return None if _is_local_path(s) else s


def _sanitize_entry(entry: dict, raw_dir_str: str = "") -> dict:
    """Sanitize fields that may leak local filesystem paths.

    - ``path`` is converted to a relative slug (the part after ``raw/``)
    - Other string values that look like absolute filesystem paths are removed
    """
    sanitized = {}
    for k, v in entry.items():
        if k == "path" and isinstance(v, str):
            # Convert absolute path to relative slug for the frontend
            if raw_dir_str and raw_dir_str in v:
                sanitized[k] = v.split(raw_dir_str)[-1].lstrip("/\\")
            else:
                # Fallback: take last path component
                sanitized[k] = Path(v).name
            continue
        # Redact string values that look like absolute local paths
        if isinstance(v, str) and _is_local_path(v):
            continue
        sanitized[k] = v
    return sanitized


def _is_local_path(v: str) -> bool:
    """Check if a string looks like a local filesystem path.

    Requires at least two path components (e.g. /home/user) to avoid
    false-positives on site-relative URLs like /works/foo.
    """
    if v.startswith(("http://", "https://")):
        return False
    # Unix absolute paths with 2+ components (e.g. /home/user, not /works)
    if v.startswith("/") and v.count("/") >= 2:
        return True
    # Windows absolute paths: C:\... or UNC \\server\...
    if len(v) >= 3 and v[1] == ":" and v[2] in ("/", "\\"):
        return True
    if v.startswith("\\\\"):
        return True
    return False


def list_raw(base_dir: Path | None = None) -> list[dict]:
    """List all raw documents with their metadata."""
    cfg = load_config(base_dir)
    raw_dir = Path(cfg["paths"]["raw"])
    if not raw_dir.exists():
        return []

    raw_dir_str = str(raw_dir) + "/"
    docs = []
    for doc_dir in sorted(raw_dir.iterdir()):
        if not doc_dir.is_dir():
            continue
        index_path = doc_dir / "index.md"
        if index_path.exists():
            post = frontmatter.load(str(index_path))
            entry = {
                "path": str(doc_dir),
                "title": post.metadata.get("title", doc_dir.name),
                "type": post.metadata.get("type", "unknown"),
                "compiled": post.metadata.get("compiled", False),
                "ingested_at": post.metadata.get("ingested_at", ""),
            }
            # Include all frontmatter fields so downstream can group/filter
            # (e.g. by work, chapter, source, canon, etc.)
            for k, v in post.metadata.items():
                if k not in entry:
                    entry[k] = _safe_meta_value(v)
            docs.append(_sanitize_entry(entry, raw_dir_str))
        else:
            # Check for any markdown file
            md_files = list(doc_dir.glob("*.md"))
            if md_files:
                post = frontmatter.load(str(md_files[0]))
                entry = {
                    "path": str(doc_dir),
                    "title": post.metadata.get("title", doc_dir.name),
                    "type": post.metadata.get("type", "unknown"),
                    "compiled": post.metadata.get("compiled", False),
                    "ingested_at": post.metadata.get("ingested_at", ""),
                }
                for k, v in post.metadata.items():
                    if k not in entry:
                        entry[k] = _safe_meta_value(v)
                docs.append(_sanitize_entry(entry, raw_dir_str))
    return docs


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")


def _guess_ext(url: str, content_type: str) -> str:
    """Guess image file extension."""
    ct_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
    }
    for ct, ext in ct_map.items():
        if ct in content_type:
            return ext
    # Try from URL
    path = urlparse(url).path
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"):
        if path.lower().endswith(ext):
            return ext
    return ".png"
