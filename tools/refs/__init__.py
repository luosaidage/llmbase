"""Reference source plugin system.

Each .py file in this directory with a PLUGIN_ID is a ref plugin.
Plugins provide source URLs and metadata for verifiable citations.

Protocol — a ref plugin must define:
  PLUGIN_ID: str          — unique identifier (e.g., "cbeta")
  PLUGIN_NAME: dict       — trilingual display name {"en": ..., "zh": ..., "ja": ...}
  get_source_url(source: dict) -> str   — build permalink from source metadata

Optional:
  search_references(query: str, max_results: int) -> list[dict]
"""

import importlib
import logging
from pathlib import Path

logger = logging.getLogger("llmbase.refs")

_plugins: dict | None = None


def discover_plugins() -> dict:
    """Auto-discover ref plugins in this directory."""
    global _plugins
    if _plugins is not None:
        return _plugins

    _plugins = {}
    refs_dir = Path(__file__).parent

    for py_file in refs_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue
        module_name = f"tools.refs.{py_file.stem}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "PLUGIN_ID"):
                _plugins[mod.PLUGIN_ID] = mod
        except Exception as e:
            logger.warning(f"Failed to load ref plugin {py_file.name}: {e}")

    return _plugins


def list_plugins() -> list[dict]:
    """List all available ref plugins with metadata."""
    plugins = discover_plugins()
    result = []
    for pid, mod in plugins.items():
        result.append({
            "id": pid,
            "name": getattr(mod, "PLUGIN_NAME", {"en": pid}),
        })
    return result


def get_source_url(source: dict) -> str:
    """Resolve a source dict to a permalink URL using the appropriate plugin."""
    plugin_id = source.get("plugin", "")
    plugins = discover_plugins()
    plugin = plugins.get(plugin_id)

    if plugin and hasattr(plugin, "get_source_url"):
        return plugin.get_source_url(source)

    # Fallback: use raw URL if available
    return source.get("url", "")
