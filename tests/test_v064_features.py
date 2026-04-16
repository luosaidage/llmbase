"""Tests for v0.6.6 additions: model override (A) + surrogate sanitize (C)."""

from unittest.mock import patch

import pytest

from tools.llm import strip_surrogates


# ─── C: surrogate sanitize ────────────────────────────────────────


def test_strip_surrogates_passes_clean_text():
    s = "玄之又玄，眾妙之門。Hello — 日本語"
    assert strip_surrogates(s) == s


def test_strip_surrogates_replaces_lone_low_surrogate():
    """The exact byte that crashes OpenAI client (\\udce7) must not survive."""
    bad = "head\udce7tail"
    out = strip_surrogates(bad)
    # Round-trip must succeed under strict UTF-8 — the bug we are fixing.
    out.encode("utf-8")
    assert "\udce7" not in out
    assert out.startswith("head") and out.endswith("tail")


def test_strip_surrogates_replaces_high_surrogate():
    bad = "\ud800abc"
    out = strip_surrogates(bad)
    out.encode("utf-8")
    assert "\ud800" not in out


def test_strip_surrogates_handles_non_string():
    assert strip_surrogates(None) is None
    assert strip_surrogates(42) == 42


def test_chat_with_context_sanitizes_payload():
    """End-to-end: surrogate-laden context must not break the LLM call."""
    captured = {}

    def fake_chat(prompt, system="", model=None, max_tokens=16384):
        captured["prompt"] = prompt
        captured["model"] = model
        # If sanitize failed, this encode raises and the test fails clearly.
        prompt.encode("utf-8")
        return "ok"

    with patch("tools.llm.chat", side_effect=fake_chat):
        from tools.llm import chat_with_context
        result = chat_with_context(
            question="what is \udce7?",
            context_files=[{"path": "art\udce7", "content": "body\udce7here"}],
        )
    assert result == "ok"
    assert "\udce7" not in captured["prompt"]


# ─── A: model override plumbing ───────────────────────────────────


def test_query_passes_model_through(tmp_kb):
    """query() must pass `model` into chat_with_context."""
    captured = {}

    def fake_cwc(question, context_files, system="", model=None, max_tokens=16384):
        captured["model"] = model
        return "stub answer"

    fake_ctx = [{"path": "stub.md", "content": "stub"}]
    with patch("tools.query._gather_context", return_value=fake_ctx), \
         patch("tools.query.chat_with_context", side_effect=fake_cwc):
        from tools.query import query
        out = query("test?", base_dir=tmp_kb, model="my-special-model")
    assert out == "stub answer"
    assert captured["model"] == "my-special-model"


def test_query_with_search_passes_model_through(tmp_kb):
    """query_with_search() must pass `model` into both LLM calls (selector + answer)."""
    # Seed minimal index.json so query_with_search doesn't bail early.
    import json
    meta_dir = tmp_kb / "wiki" / "_meta"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "index.json").write_text(json.dumps([
        {"slug": "kong", "title": "Emptiness / 空", "summary": "x", "tags": []},
    ]))

    selector_calls = []
    answer_calls = []

    def fake_chat(prompt, system="", model=None, max_tokens=16384):
        selector_calls.append(model)
        return "Emptiness / 空"

    def fake_cwc(question, context_files, system="", model=None, max_tokens=16384):
        answer_calls.append(model)
        return "stub answer"

    fake_ctx = [{"path": "stub.md", "content": "stub"}] * 3  # >=3 to skip fallback
    with patch("tools.query.chat", side_effect=fake_chat), \
         patch("tools.query.chat_with_context", side_effect=fake_cwc), \
         patch("tools.query._gather_context", return_value=fake_ctx):
        from tools.query import query_with_search
        query_with_search("what?", base_dir=tmp_kb, model="custom-model")

    assert "custom-model" in selector_calls
    assert "custom-model" in answer_calls


def test_query_default_model_is_none_when_omitted(tmp_kb):
    """Omitting `model` must result in None (defers to LLMBASE_MODEL downstream)."""
    captured = {}

    def fake_cwc(question, context_files, system="", model=None, max_tokens=16384):
        captured["model"] = model
        return "x"

    fake_ctx = [{"path": "stub.md", "content": "stub"}]
    with patch("tools.query._gather_context", return_value=fake_ctx), \
         patch("tools.query.chat_with_context", side_effect=fake_cwc):
        from tools.query import query
        query("q?", base_dir=tmp_kb)
    assert captured["model"] is None


# ─── A: /api/ask honors model in body ─────────────────────────────


def _client(tmp_kb):
    from tools.web import create_web_app
    app = create_web_app(tmp_kb)
    app.config["TESTING"] = True
    return app.test_client()


def test_api_ask_shallow_passes_model(tmp_kb):
    captured = {}

    def fake_query(q, file_back=False, base_dir=None, tone="default", return_path=False, model=None):
        captured["model"] = model
        return {"answer": "x", "output_path": None}

    with patch("tools.web.query", side_effect=fake_query):
        c = _client(tmp_kb)
        r = c.post("/api/ask", json={"question": "hi", "deep": False, "model": "alpha-v2"})
    assert r.status_code == 200
    assert captured["model"] == "alpha-v2"


def test_api_ask_deep_passes_model(tmp_kb):
    captured = {}

    def fake_dispatch(name, base, args):
        captured.update(args)
        return {"answer": "x", "consulted": []}

    from tools import operations as _ops
    with patch.object(_ops, "dispatch", side_effect=fake_dispatch):
        c = _client(tmp_kb)
        r = c.post("/api/ask", json={"question": "hi", "deep": True, "model": "beta-v3"})
    assert r.status_code == 200
    assert captured["model"] == "beta-v3"


def test_api_ask_omitted_model_not_in_dispatch_args(tmp_kb):
    """When client omits `model`, ops dispatch must not receive a stray key."""
    captured = {}

    def fake_dispatch(name, base, args):
        captured.update(args)
        return {"answer": "x", "consulted": []}

    from tools import operations as _ops
    with patch.object(_ops, "dispatch", side_effect=fake_dispatch):
        c = _client(tmp_kb)
        r = c.post("/api/ask", json={"question": "hi", "deep": True})
    assert r.status_code == 200
    assert "model" not in captured


def test_api_ask_rejects_non_string_model(tmp_kb):
    c = _client(tmp_kb)
    r = c.post("/api/ask", json={"question": "hi", "deep": False, "model": 123})
    assert r.status_code == 400


def test_api_ask_rejects_oversized_model(tmp_kb):
    c = _client(tmp_kb)
    r = c.post("/api/ask", json={"question": "hi", "deep": False, "model": "x" * 201})
    assert r.status_code == 400


def test_api_ask_empty_string_model_treated_as_none(tmp_kb):
    """Empty / whitespace `model` must be treated as 'use default', not error."""
    captured = {}

    def fake_query(q, file_back=False, base_dir=None, tone="default", return_path=False, model=None):
        captured["model"] = model
        return {"answer": "x", "output_path": None}

    with patch("tools.web.query", side_effect=fake_query):
        c = _client(tmp_kb)
        r = c.post("/api/ask", json={"question": "hi", "deep": False, "model": "  "})
    assert r.status_code == 200
    assert captured["model"] is None


# ─── A: kb_ask Operation accepts model ────────────────────────────


def test_kb_ask_operation_declares_model_param():
    from tools.operations import _REGISTRY
    op = _REGISTRY["kb_ask"]
    assert "model" in op.params["properties"]


# ─── C: ingest_url sanitizes before write ─────────────────────────


def test_ingest_url_sanitizes_content(tmp_kb, monkeypatch):
    """ingest_url must not write lone surrogates into raw/."""
    from tools import ingest as _ing

    class FakeResp:
        status_code = 200
        content = b"<html><head><title>T</title></head><body><p>fake</p></body></html>"
        text = content.decode()
        encoding = "utf-8"
        headers = {"content-type": "text/html; charset=utf-8"}
        def raise_for_status(self): pass

    # Bypass SSRF check + network — we only want to assert sanitize.
    monkeypatch.setattr(_ing, "_validate_url", lambda u: None)
    monkeypatch.setattr(_ing, "requests", type("R", (), {"get": staticmethod(lambda *a, **k: FakeResp())}))
    # Force a surrogate into the markdown conversion path.
    monkeypatch.setattr(_ing, "md", lambda *a, **k: "body\udce7tail")

    path = _ing.ingest_url("https://example.com/x", base_dir=tmp_kb)
    text = path.read_text(encoding="utf-8")
    assert "\udce7" not in text  # sanitized to U+FFFD
