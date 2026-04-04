"""LLM interaction layer using any OpenAI-compatible API."""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
import httpx
from openai import OpenAI

# Load .env from project root
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("LLMBASE_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("LLMBASE_BASE_URL") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            timeout=httpx.Timeout(300.0, connect=30.0),
            max_retries=3,
        )
    return _client


def get_default_model() -> str:
    return os.getenv("LLMBASE_MODEL", "gpt-4o")


def chat(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 8192,
) -> str:
    """Send a single prompt and return the text response."""
    if model is None:
        model = get_default_model()

    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            if not content:
                reasoning = getattr(response.choices[0].message, "reasoning_content", None)
                if reasoning:
                    content = reasoning
            return content or ""
        except Exception as e:
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            raise


def chat_with_context(
    question: str,
    context_files: list[dict],
    system: str = "",
    model: str | None = None,
    max_tokens: int = 8192,
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
