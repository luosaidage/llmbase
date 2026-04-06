"""ctext.org reference source plugin.

Provides permalink URLs to ctext.org for Chinese classics.
"""

PLUGIN_ID = "ctext"
PLUGIN_NAME = {"en": "Chinese Text Project", "zh": "中国哲学书电子化计划", "ja": "中国哲学書電子化計画"}
BASE_URL = "https://ctext.org"


def get_source_url(source: dict) -> str:
    """Build ctext.org permalink from source metadata."""
    url = source.get("url", "")
    if url:
        return url
    book = source.get("book", "")
    chapter = source.get("chapter", "")
    if book and chapter:
        return f"{BASE_URL}/{book}/{chapter}"
    return ""
