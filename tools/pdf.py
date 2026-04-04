"""PDF processing module — convert PDF files to markdown for ingestion."""

import re
from pathlib import Path
from datetime import datetime, timezone

import frontmatter

from .config import load_config, ensure_dirs


def pdf_to_markdown(pdf_path: str, chunk_pages: int = 0) -> list[dict]:
    """Extract text from a PDF and convert to markdown documents.

    Args:
        pdf_path: Path to the PDF file.
        chunk_pages: If > 0, split into chunks of this many pages.
                     If 0, output as a single document.

    Returns:
        List of dicts with keys: title, content, page_start, page_end, metadata
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise ImportError("PyMuPDF is required for PDF processing. Install: pip install pymupdf")

    doc = fitz.open(pdf_path)
    total_pages = len(doc)

    # Extract metadata
    meta = doc.metadata or {}
    title = meta.get("title", "") or Path(pdf_path).stem
    author = meta.get("author", "")

    if chunk_pages <= 0:
        # Single document
        text = _extract_all_text(doc)
        return [{
            "title": title,
            "content": text,
            "page_start": 1,
            "page_end": total_pages,
            "metadata": {"author": author, "total_pages": total_pages},
        }]

    # Chunked output
    chunks = []
    for start in range(0, total_pages, chunk_pages):
        end = min(start + chunk_pages, total_pages)
        text = _extract_page_range(doc, start, end)
        if text.strip():
            chunk_title = f"{title} (p.{start+1}-{end})" if total_pages > chunk_pages else title
            chunks.append({
                "title": chunk_title,
                "content": text,
                "page_start": start + 1,
                "page_end": end,
                "metadata": {"author": author, "total_pages": total_pages},
            })

    doc.close()
    return chunks


def ingest_pdf(
    pdf_path: str,
    chunk_pages: int = 20,
    base_dir: Path | None = None,
) -> list[Path]:
    """Ingest a PDF file into the knowledge base.

    Converts PDF to markdown, splits into chunks, and saves to raw/.

    Args:
        pdf_path: Path to the PDF file.
        chunk_pages: Pages per chunk (0 = single doc, default 20).
        base_dir: Knowledge base root directory.

    Returns:
        List of paths to created raw documents.
    """
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    raw_dir = Path(cfg["paths"]["raw"])

    chunks = pdf_to_markdown(pdf_path, chunk_pages)
    results = []

    src_name = Path(pdf_path).stem
    slug_base = re.sub(r"[^\w]+", "-", src_name).strip("-")

    for i, chunk in enumerate(chunks):
        if len(chunks) == 1:
            slug = slug_base
        else:
            slug = f"{slug_base}-p{chunk['page_start']:03d}-{chunk['page_end']:03d}"

        doc_dir = raw_dir / slug
        doc_dir.mkdir(parents=True, exist_ok=True)

        post = frontmatter.Post(chunk["content"])
        post.metadata["title"] = chunk["title"]
        post.metadata["source"] = str(Path(pdf_path).resolve())
        post.metadata["ingested_at"] = datetime.now(timezone.utc).isoformat()
        post.metadata["type"] = "pdf"
        post.metadata["page_start"] = chunk["page_start"]
        post.metadata["page_end"] = chunk["page_end"]
        post.metadata["total_pages"] = chunk["metadata"]["total_pages"]
        if chunk["metadata"].get("author"):
            post.metadata["author"] = chunk["metadata"]["author"]
        post.metadata["compiled"] = False

        doc_path = doc_dir / "index.md"
        doc_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        results.append(doc_path)

    return results


def _extract_all_text(doc) -> str:
    """Extract text from all pages."""
    parts = []
    for i, page in enumerate(doc):
        text = page.get_text().strip()
        if text:
            parts.append(f"<!-- Page {i+1} -->\n\n{_clean_text(text)}")
    return "\n\n---\n\n".join(parts)


def _extract_page_range(doc, start: int, end: int) -> str:
    """Extract text from a range of pages."""
    parts = []
    for i in range(start, end):
        page = doc[i]
        text = page.get_text().strip()
        if text:
            parts.append(_clean_text(text))
    return "\n\n".join(parts)


def _clean_text(text: str) -> str:
    """Clean up extracted PDF text."""
    # Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove page headers/footers (common patterns)
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
    # Clean up hyphenated line breaks (English)
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    return text.strip()
