"""LLM interaction layer with automatic fallback across models."""

import os
import time
import logging
from pathlib import Path

from dotenv import load_dotenv
import httpx
from openai import OpenAI

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

logger = logging.getLogger("llmbase.llm")

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("LLMBASE_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("LLMBASE_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=httpx.Timeout(300.0, connect=30.0),
            max_retries=2,
        )
    return _client


def get_default_model() -> str:
    return os.getenv("LLMBASE_MODEL", "gpt-4o")


def get_fallback_models() -> list[str]:
    """Get fallback model list from env. Comma-separated; empty = no fallback.

    Since 0.5.0: an empty/unset ``LLMBASE_FALLBACK_MODELS`` means *no*
    fallback — only the primary model is retried. Earlier versions
    auto-generated a fallback chain (e.g. gpt-4o → gpt-4o-mini), which
    silently broke aggregator deployments where the API token only had
    rights to the primary model. Downstream that wants fallback must now
    set the env var explicitly, e.g.::

        LLMBASE_FALLBACK_MODELS=gpt-4o-mini,gpt-3.5-turbo
    """
    fallbacks = os.getenv("LLMBASE_FALLBACK_MODELS", "")
    if not fallbacks:
        return []
    return [m.strip() for m in fallbacks.split(",") if m.strip()]


def _get_retries(primary: bool) -> int:
    """Per-model retry budget. Configurable via env, with sane defaults."""
    if primary:
        env_key, default = "LLMBASE_PRIMARY_RETRIES", 3
    else:
        env_key, default = "LLMBASE_FALLBACK_RETRIES", 1
    raw = os.getenv(env_key, "")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning(f"Invalid {env_key}={raw!r}, using default {default}")
        return default


def _call_llm(messages: list, model: str, max_tokens: int) -> str:
    """Single LLM call with response extraction.

    Handles models with thinking mode: if content is empty but
    reasoning_content exists, uses that as content.
    """
    client = get_client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )
    msg = response.choices[0].message
    content = msg.content or ""
    reasoning = getattr(msg, "reasoning_content", None) or ""

    # If content is empty, model might have put everything in reasoning
    if not content.strip() and reasoning:
        content = reasoning

    return content


def extract_json(text: str) -> str:
    """Extract valid JSON from mixed thinking+content LLM output.

    Call this explicitly when you expect JSON — not applied globally.
    Searches from the END of the text to find the last valid JSON
    block (thinking comes first, JSON output last).
    Returns the original text if no valid JSON found.
    """
    import json as _json

    stripped = text.strip()

    # Quick validation if it already looks like JSON
    if stripped.startswith(("[", "{")):
        try:
            _json.loads(stripped)
            return stripped
        except _json.JSONDecodeError:
            pass  # Might be incomplete, try extraction below

    # Search from the end — try whichever closing bracket is rightmost first
    pairs = [("[", "]"), ("{", "}")]
    pairs.sort(key=lambda p: text.rfind(p[1]), reverse=True)

    for start_char, end_char in pairs:
        end_pos = text.rfind(end_char)
        if end_pos == -1:
            continue
        # Find the matching opening bracket before it
        start_pos = text.rfind(start_char, 0, end_pos)
        if start_pos == -1:
            continue
        candidate = text[start_pos:end_pos + 1]
        try:
            _json.loads(candidate)
            return candidate
        except _json.JSONDecodeError:
            # Try progressively earlier opening brackets
            while True:
                start_pos = text.rfind(start_char, 0, start_pos)
                if start_pos == -1:
                    break
                candidate = text[start_pos:end_pos + 1]
                try:
                    _json.loads(candidate)
                    return candidate
                except _json.JSONDecodeError:
                    continue

    return text  # No valid JSON found


def chat(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 16384,
) -> str:
    """Send a prompt with automatic model fallback on failure."""
    if model is None:
        model = get_default_model()

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # Try primary model with retries
    models_to_try = [model] + get_fallback_models()

    for i, current_model in enumerate(models_to_try):
        retries = _get_retries(primary=(i == 0))
        for attempt in range(retries):
            try:
                result = _call_llm(messages, current_model, max_tokens)
                if result:
                    if i > 0:
                        logger.warning(f"Primary model failed, used fallback: {current_model}")
                    return result
                # Empty result — retry or try next model
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
            except Exception as e:
                err_msg = str(e)
                if attempt < retries - 1:
                    wait = 2 ** attempt
                    logger.debug(f"{current_model} attempt {attempt+1} failed: {err_msg}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                if i < len(models_to_try) - 1:
                    logger.warning(f"{current_model} failed ({err_msg}), falling back to {models_to_try[i+1]}")
                    break  # Try next model
                raise  # Last model, re-raise

    return ""


def chat_with_context(
    question: str,
    context_files: list[dict],
    system: str = "",
    model: str | None = None,
    max_tokens: int = 16384,
) -> str:
    """Ask a question with file contents as context."""
    context_parts = []
    for f in context_files:
        context_parts.append(f"## {f['path']}\n\n{f['content']}")
    context_block = "\n\n---\n\n".join(context_parts)

    prompt = f"""Here are the relevant knowledge base articles:

{context_block}

---

Based on the above context, please answer the following question:

{question}"""

    return chat(prompt, system=system, model=model, max_tokens=max_tokens)
