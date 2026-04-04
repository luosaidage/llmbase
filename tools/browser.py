"""Browser integration via opencli for web content fetching and reading."""

import json
import subprocess
import shutil
from pathlib import Path


def is_opencli_available() -> bool:
    """Check if opencli is installed."""
    return shutil.which("opencli") is not None


def opencli_run(args: list[str], timeout: int = 30) -> str:
    """Run an opencli command and return output."""
    cmd = ["opencli"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"opencli error: {result.stderr}")
    return result.stdout


def browse_url(url: str) -> str:
    """Open a URL in the browser and get the page content."""
    try:
        opencli_run(["operate", "open", url], timeout=15)
        state = opencli_run(["operate", "state"], timeout=10)
        return state
    except Exception as e:
        return f"Error browsing {url}: {e}"


def screenshot(output_path: str | None = None) -> str:
    """Take a screenshot of the current browser page."""
    args = ["operate", "screenshot"]
    if output_path:
        args.extend(["--output", output_path])
    return opencli_run(args, timeout=10)


def extract_text(url: str) -> str:
    """Navigate to URL and extract text content."""
    try:
        opencli_run(["operate", "open", url], timeout=15)
        content = opencli_run(["operate", "get", "body", "--text"], timeout=10)
        return content
    except Exception as e:
        return f"Error extracting text from {url}: {e}"


def search_web(query: str, site: str = "hackernews", limit: int = 10) -> list[dict]:
    """Search a supported site via opencli."""
    try:
        output = opencli_run([site, "search", query, "-f", "json", "--limit", str(limit)], timeout=20)
        return json.loads(output)
    except Exception:
        return []


def fetch_article(url: str) -> dict:
    """Fetch a web article via opencli browser, returning title and content."""
    try:
        opencli_run(["operate", "open", url], timeout=15)

        # Get page title
        title = opencli_run(["operate", "get", "title"], timeout=5).strip()

        # Get main content
        content = ""
        for selector in ["article", "main", ".content", "#content", "body"]:
            try:
                content = opencli_run(["operate", "get", selector, "--text"], timeout=5).strip()
                if len(content) > 100:
                    break
            except Exception:
                continue

        return {"title": title, "content": content, "url": url}
    except Exception as e:
        return {"title": "", "content": "", "url": url, "error": str(e)}
