"""Wikisource reference source plugin.

Provides permalink URLs to zh.wikisource.org for classical Chinese texts.
"""

PLUGIN_ID = "wikisource"
PLUGIN_NAME = {"en": "Wikisource", "zh": "维基文库", "ja": "ウィキソース"}
BASE_URL = "https://zh.wikisource.org/wiki"


def get_source_url(source: dict) -> str:
    """Build Wikisource permalink from source metadata."""
    url = source.get("url", "")
    if url:
        return url
    title = source.get("title", "")
    if title:
        return f"{BASE_URL}/{title}"
    return ""
