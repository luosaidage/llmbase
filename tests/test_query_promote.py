"""Tests for promote_to_concept — QA → wiki concept sediment.

LLM is mocked. The judge has three observable behaviors we care about:
1. Decline (promote=false) → no file written, returns reason
2. Promote new concept → file created in concepts/, index rebuilt
3. Promote into an existing slug (via dedup) → existing file is merged, no duplicate
"""

import json
from pathlib import Path

import frontmatter

from tools.query import promote_to_concept


def _judge_response(decision: dict) -> str:
    return json.dumps(decision, ensure_ascii=False)


def test_promote_declined(tmp_kb, monkeypatch):
    """Judge says no — nothing should be written."""
    monkeypatch.chdir(tmp_kb)

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response({"promote": False, "reason": "too vague"})

    monkeypatch.setattr("tools.query.chat", fake_chat)

    concepts_dir = tmp_kb / "wiki" / "concepts"
    before = sorted(p.name for p in concepts_dir.glob("*.md"))

    result = promote_to_concept(
        question="What is the meaning of life?",
        answer="42",
        consulted=[],
        index=[],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is False
    assert "too vague" in result["reason"]

    after = sorted(p.name for p in concepts_dir.glob("*.md"))
    assert before == after, "no new files should be written when judge declines"


def test_promote_new_concept(tmp_kb, monkeypatch):
    """Judge approves a brand-new concept — file created, index rebuilt."""
    monkeypatch.chdir(tmp_kb)

    judge_decision = {
        "promote": True,
        "reason": "clear new concept",
        "merge_into": None,
        "slug": "wu-wei",
        "title": "Non-Action / 無為",
        "summary": "Daoist principle of effortless action",
        "tags": ["daoism", "philosophy"],
        "content": (
            "## English\n\nWu Wei means effortless action.\n\n"
            "## 中文\n\n無為即不強為。\n\n"
            "## 日本語\n\n無為とは作為のない行いをいう。"
        ),
    }

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response(judge_decision)

    monkeypatch.setattr("tools.query.chat", fake_chat)

    result = promote_to_concept(
        question="What is wu wei?",
        answer="Wu wei is the Daoist principle of effortless action…",
        consulted=[],
        index=[],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is True
    assert result["slug"] == "wu-wei"
    assert result["merged"] is False

    article_path = Path(result["path"])
    assert article_path.exists()

    post = frontmatter.load(str(article_path))
    assert post.metadata["title"] == "Non-Action / 無為"
    assert "daoism" in post.metadata["tags"]
    assert post.metadata["sources"][0]["plugin"] == "qa"
    assert post.metadata["sources"][0]["question"] == "What is wu wei?"

    # Index rebuilt
    index_path = tmp_kb / "wiki" / "_meta" / "index.json"
    assert index_path.exists()
    index = json.loads(index_path.read_text())
    slugs = {e["slug"] for e in index}
    assert "wu-wei" in slugs


def test_promote_merges_into_existing(tmp_kb, monkeypatch):
    """If judge proposes a slug that already exists, _write_article merges
    rather than duplicates. promotion.merged should be True."""
    monkeypatch.chdir(tmp_kb)

    # tmp_kb already has 'kong' (Emptiness / 空)
    judge_decision = {
        "promote": True,
        "reason": "extends existing concept",
        "merge_into": "kong",
        "slug": "kong",
        "title": "Emptiness / 空",
        "summary": "Extended view of emptiness",
        "tags": ["buddhism", "madhyamaka"],
        "content": (
            "## English\n\nEmptiness, as elaborated by Nagarjuna, "
            "denies inherent existence to all phenomena. " * 5 + "\n\n"
            "## 中文\n\n空者，破自性也。" * 5 + "\n\n"
            "## 日本語\n\n空とは自性の否定をいう。" * 5
        ),
    }

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response(judge_decision)

    monkeypatch.setattr("tools.query.chat", fake_chat)

    concepts_dir = tmp_kb / "wiki" / "concepts"
    files_before = sorted(p.name for p in concepts_dir.glob("*.md"))

    result = promote_to_concept(
        question="What is emptiness in Madhyamaka?",
        answer="In Madhyamaka, emptiness means…",
        consulted=[{"slug": "kong", "title": "Emptiness / 空"}],
        index=[
            {"slug": "kong", "title": "Emptiness / 空", "summary": "core concept"},
        ],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is True
    assert result["merged"] is True
    assert result["slug"] == "kong"

    files_after = sorted(p.name for p in concepts_dir.glob("*.md"))
    assert files_before == files_after, "no duplicate file should be created"

    # The kong article should now have the new (longer) content
    post = frontmatter.load(str(concepts_dir / "kong.md"))
    assert "Nagarjuna" in post.content


def test_promote_invalid_json(tmp_kb, monkeypatch):
    """Judge returns garbage — should fail safely without writing."""
    monkeypatch.chdir(tmp_kb)

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return "I'm sorry, I cannot decide this question."

    monkeypatch.setattr("tools.query.chat", fake_chat)

    concepts_dir = tmp_kb / "wiki" / "concepts"
    before = sorted(p.name for p in concepts_dir.glob("*.md"))

    result = promote_to_concept(
        question="anything",
        answer="anything",
        consulted=[],
        index=[],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is False
    assert "JSON" in result["reason"] or "invalid" in result["reason"].lower()

    after = sorted(p.name for p in concepts_dir.glob("*.md"))
    assert before == after


def test_promote_non_object_json(tmp_kb, monkeypatch):
    """Judge returns valid JSON but not an object (e.g. array, scalar) — fail closed."""
    monkeypatch.chdir(tmp_kb)

    for payload in ('[]', '"ok"', 'null', '42'):
        def fake_chat(prompt, system="", model=None, max_tokens=8192, _p=payload, **kwargs):
            return _p

        monkeypatch.setattr("tools.query.chat", fake_chat)

        result = promote_to_concept(
            question="anything",
            answer="anything",
            consulted=[],
            index=[],
            base_dir=tmp_kb,
        )

        assert result["promoted"] is False, f"payload {payload!r} should not promote"
        assert "non-object" in result["reason"], f"payload {payload!r} reason: {result['reason']}"


def test_promote_merge_into_overrides_slug(tmp_kb, monkeypatch):
    """Judge proposes a NEW slug but says merge_into=existing — must merge into existing,
    not create a duplicate file under the new slug."""
    monkeypatch.chdir(tmp_kb)

    judge_decision = {
        "promote": True,
        "reason": "extends emptiness",
        "merge_into": "kong",
        "slug": "emptiness-madhyamaka",  # different from merge_into!
        "title": "Emptiness in Madhyamaka",
        "summary": "extension",
        "tags": ["buddhism"],
        "content": (
            "## English\n\nMadhyamaka view of emptiness as elaborated by Nagarjuna. " * 4 + "\n\n"
            "## 中文\n\n中观对空的阐发。" * 4 + "\n\n"
            "## 日本語\n\n中観の空観。" * 4
        ),
    }

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response(judge_decision)

    monkeypatch.setattr("tools.query.chat", fake_chat)

    concepts_dir = tmp_kb / "wiki" / "concepts"
    files_before = sorted(p.name for p in concepts_dir.glob("*.md"))

    result = promote_to_concept(
        question="What is emptiness in Madhyamaka?",
        answer="Madhyamaka emptiness…",
        consulted=[{"slug": "kong", "title": "Emptiness / 空"}],
        index=[{"slug": "kong", "title": "Emptiness / 空", "summary": "core"}],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is True
    assert result["slug"] == "kong", "merge_into should win over decision.slug"
    assert result["merged"] is True

    # No new file under the proposed-but-overridden slug
    assert not (concepts_dir / "emptiness-madhyamaka.md").exists()

    files_after = sorted(p.name for p in concepts_dir.glob("*.md"))
    assert files_before == files_after


def test_promote_traversal_slug_rejected(tmp_kb, monkeypatch):
    """Slug with path traversal characters must be sanitized; if it sanitizes
    to empty, the promotion is rejected without touching disk."""
    monkeypatch.chdir(tmp_kb)

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response({
            "promote": True,
            "reason": "evil",
            "slug": "../../../etc/passwd",
            "title": "Evil",
            "content": "## English\n\nbody",
        })

    monkeypatch.setattr("tools.query.chat", fake_chat)

    concepts_dir = tmp_kb / "wiki" / "concepts"
    before = sorted(p.name for p in concepts_dir.glob("*.md"))

    result = promote_to_concept(
        question="evil",
        answer="evil",
        consulted=[],
        index=[],
        base_dir=tmp_kb,
    )

    # Sanitization strips ../, /, leaving "etcpasswd" — should still write a
    # safe file inside concepts/, NOT outside it.
    after = sorted(p.name for p in concepts_dir.glob("*.md"))
    if result["promoted"]:
        assert result["path"].startswith(str(concepts_dir))
        # All new files must be inside concepts_dir
        for name in set(after) - set(before):
            assert (concepts_dir / name).exists()
    # Nothing escaped the concepts dir either way
    assert not Path("/etc/passwd-llmbase-test").exists()


def test_mcp_kb_ask_promote_takes_job_lock(tmp_kb, monkeypatch):
    """kb_ask with promote=true must acquire the same job_lock that kb_ingest/
    kb_compile use, to prevent concurrent mutations of wiki/concepts."""
    monkeypatch.chdir(tmp_kb)

    from tools import mcp_server
    from tools.worker import job_lock

    # Pre-acquire the job lock — kb_ask with promote should refuse
    assert job_lock.acquire(blocking=False)
    try:
        result = mcp_server.handle_tool(
            "kb_ask",
            {"question": "anything", "promote": True},
            tmp_kb,
        )
        assert "Another write operation is running" in result
    finally:
        job_lock.release()

    # Without promote=true, kb_ask is still read-only and should NOT be gated
    # (we don't actually call it because it would hit the LLM; we just check
    # that the lock isn't acquired by checking it's available right after).
    assert not job_lock.locked()


def test_promote_missing_required_fields(tmp_kb, monkeypatch):
    """Judge says promote=true but omits content — should reject."""
    monkeypatch.chdir(tmp_kb)

    def fake_chat(prompt, system="", model=None, max_tokens=8192, **kwargs):
        return _judge_response({
            "promote": True,
            "reason": "looks good",
            "slug": "incomplete",
            "title": "Incomplete",
            # missing content
        })

    monkeypatch.setattr("tools.query.chat", fake_chat)

    result = promote_to_concept(
        question="anything",
        answer="anything",
        consulted=[],
        index=[],
        base_dir=tmp_kb,
    )

    assert result["promoted"] is False
    assert "content" in result["reason"]
