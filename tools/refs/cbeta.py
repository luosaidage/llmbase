"""CBETA reference source plugin.

Provides permalink URLs to CBETA Online for Buddhist sutras.
"""

PLUGIN_ID = "cbeta"
PLUGIN_NAME = {"en": "CBETA Buddhist Canon", "zh": "CBETA 大藏经", "ja": "CBETA 大蔵経"}
BASE_URL = "https://cbetaonline.dila.edu.tw/zh"


def get_source_url(source: dict) -> str:
    """Build CBETA Online permalink from source metadata."""
    work_id = source.get("work_id", "")
    if work_id:
        return f"{BASE_URL}/{work_id}"
    return source.get("url", "")
