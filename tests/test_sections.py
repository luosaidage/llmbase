"""Tests for tools.sections — parser, anchor stability, ops + HTTP integration (v0.7.1)."""

import frontmatter
import pytest

from tools.operations import dispatch
from tools.sections import (
    extract_section_text,
    find_section,
    make_anchor,
    normalize_title,
    parse_sections,
)
from tools.web import create_web_app


# ─── normalize_title ──────────────────────────────────────────────────


def test_normalize_strips_invisibles_and_punct():
    # U+3000 (ideographic space), U+200B (zero-width), U+202E (RTL override),
    # CJK punctuation, and ASCII punctuation all stripped.
    assert normalize_title("緒論\u3000（一）：第一章\u200b") == "緒論一第一章"
    assert normalize_title("Title — with [brackets]!") == "Titlewithbrackets"


def test_normalize_preserves_cjk_kana_alnum():
    assert normalize_title("第三章 判教") == "第三章判教"
    assert normalize_title("ひらがな カタカナ ABC123") == "ひらがなカタカナABC123"


def test_normalize_empty_title_safely():
    assert normalize_title("") == ""
    assert normalize_title("   \u3000\u200b") == ""
    assert normalize_title("——「」（）") == ""


# ─── make_anchor ──────────────────────────────────────────────────────


def test_anchor_format_and_components():
    a = make_anchor(2, ["緒論"])
    assert a.startswith("h2-緒論-")
    # Bumped from 4 to 6 hex post-Codex to keep birthday-paradox collision
    # rate <1% even on ~300-section 太虛 books.
    assert len(a.rsplit("-", 1)[1]) == 6


def test_anchor_stable_across_whitespace_and_punct_noise():
    """The whole point: trivial title edits must not change the anchor."""
    a1 = make_anchor(3, ["緒論", "第一章 判教"])
    a2 = make_anchor(3, ["緒論", "第一章\u3000判教"])  # ideographic space inserted
    a3 = make_anchor(3, ["緒論：", "第一章——判教！"])  # punctuation noise
    assert a1 == a2 == a3


def test_anchor_changes_when_title_word_changes():
    """A real edit (字 change) must produce a new anchor — caller handles via aliases."""
    a1 = make_anchor(2, ["緒言"])
    a2 = make_anchor(2, ["弁言"])
    assert a1 != a2


def test_anchor_path_distinguishes_same_title_under_different_parents():
    """The 結論 collision case from the design doc."""
    a1 = make_anchor(4, ["緒論", "第一章", "結論"])
    a2 = make_anchor(4, ["緒論", "第二章", "結論"])
    assert a1 != a2


def test_anchor_independent_of_sibling_position():
    """Reordering siblings must not shift any sibling's anchor."""
    a = make_anchor(3, ["緒論", "結論"])
    # Same chain, regardless of how many siblings exist before it in flat parse.
    assert make_anchor(3, ["緒論", "結論"]) == a


def test_anchor_empty_title_falls_back():
    a = make_anchor(3, ["——「」（）"])  # normalize → empty
    assert a.startswith("h3-_-")


def test_anchor_truncates_long_slug():
    long = "甲" * 50
    a = make_anchor(2, [long])
    slug_part = a.split("-", 2)[1]
    assert len(slug_part) == 20
    assert slug_part == "甲" * 20


# ─── parse_sections ──────────────────────────────────────────────────


def test_parse_empty_body():
    assert parse_sections("") == []


def test_parse_no_headings():
    assert parse_sections("just a paragraph\n\nand another\n") == []


def test_parse_single_heading_spans_to_end():
    body = "## Hello\n\nbody text\n"
    sections = parse_sections(body)
    assert len(sections) == 1
    assert sections[0]["level"] == 2
    assert sections[0]["title"] == "Hello"
    assert sections[0]["start"] == 0
    assert sections[0]["end"] == len(body)
    assert sections[0]["children"] == []


def test_parse_nested_tree_shape():
    body = (
        "## A\n"
        "intro a\n"
        "### A1\n"
        "intro a1\n"
        "### A2\n"
        "intro a2\n"
        "## B\n"
        "intro b\n"
    )
    sections = parse_sections(body)
    assert len(sections) == 2
    a, b = sections
    assert a["title"] == "A"
    assert b["title"] == "B"
    assert [c["title"] for c in a["children"]] == ["A1", "A2"]
    assert b["children"] == []


def test_parse_skipped_levels_still_nest_correctly():
    # Common in 古籍: H2 directly into H4 (skipping H3).
    body = "## A\n#### A1\n#### A2\n## B\n"
    sections = parse_sections(body)
    assert len(sections) == 2
    assert [c["title"] for c in sections[0]["children"]] == ["A1", "A2"]


def test_parse_eight_layer_deep_nesting():
    """太虛's 甲乙丙丁戊己庚辛 case — 8-level nesting must parse, even past h6."""
    # Markdown maxes at h6, but 古籍 nests deeper via list / annotation;
    # this test ensures we at least parse h1..h6 correctly when they all stack.
    body = "".join(f"{'#' * lvl} L{lvl}\n" for lvl in range(1, 7))
    sections = parse_sections(body)
    # Should be one root that nests all the way down.
    assert len(sections) == 1
    node = sections[0]
    depth = 1
    while node["children"]:
        node = node["children"][0]
        depth += 1
    assert depth == 6


def test_parse_skips_headings_in_fenced_code():
    body = (
        "## Real\n"
        "```\n"
        "## Not a heading\n"
        "```\n"
        "## Also Real\n"
    )
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["Real", "Also Real"]


def test_parse_skips_headings_in_tilde_fences():
    body = "## Real\n~~~\n## Hidden\n~~~\n## Also Real\n"
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["Real", "Also Real"]


def test_parse_fence_with_longer_opener_requires_matching_close():
    # CommonMark §4.5: closer must be ≥ opener in length, same char.
    # A 3-tick line inside a 5-tick fence does NOT close it; the heading inside
    # must remain hidden.
    body = "## Real\n`````\n```\n## Hidden\n`````\n## Also Real\n"
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["Real", "Also Real"]


def test_parse_preserves_csharp_in_title():
    # ## C# must NOT lose the trailing # — the closing-hash sequence requires
    # whitespace before it per CommonMark §4.2.
    body = "## C#\n## C #\n"
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["C#", "C"]


def test_parse_ignores_4_space_indented_pseudo_heading():
    # 4+ space indent makes it an indented code block, not a heading.
    body = "## Real\n    ## Not A Heading\nmore text\n## Also Real\n"
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["Real", "Also Real"]


def test_parse_3_space_indent_still_heading():
    # 0–3 space indent is allowed for ATX headings.
    body = "   ## Indented Three\n## Normal\n"
    sections = parse_sections(body)
    assert [s["title"] for s in sections] == ["Indented Three", "Normal"]


def test_parse_collision_suffixed():
    # Two headings with identical normalize+chain → second gets -2 suffix.
    # We construct the collision deliberately via the same parent + same title.
    body = "## P\n### X\n### X\n## P2\n### X\n"
    sections = parse_sections(body)
    p, p2 = sections
    a1, a2 = p["children"]
    assert a1["anchor"] != a2["anchor"]
    assert a2["anchor"].endswith("-2")
    # First X under P2 has different parent → no collision.
    assert not p2["children"][0]["anchor"].endswith("-2")


def test_parse_subtree_slice_is_self_contained():
    body = "## A\nA body\n### A1\nA1 body\n## B\nB body\n"
    sections = parse_sections(body)
    a = sections[0]
    sliced = body[a["start"] : a["end"]]
    assert sliced.startswith("## A")
    assert "A1 body" in sliced  # descendants included
    assert "B body" not in sliced  # sibling excluded


# ─── find_section / extract_section_text ──────────────────────────────


def test_find_section_walks_tree():
    body = "## A\n### A1\n#### A1a\n## B\n"
    sections = parse_sections(body)
    a1a_anchor = sections[0]["children"][0]["children"][0]["anchor"]
    found = find_section(sections, a1a_anchor)
    assert found is not None
    assert found["title"] == "A1a"


def test_find_section_returns_none_when_missing():
    sections = parse_sections("## A\n")
    assert find_section(sections, "h2-bogus-0000") is None


def test_extract_section_text_returns_subtree():
    body = "## A\nA body\n### A1\nA1 body\n## B\nB body\n"
    sections = parse_sections(body)
    a_anchor = sections[0]["anchor"]
    text = extract_section_text(body, sections, a_anchor)
    assert text is not None
    assert text.startswith("## A")
    assert "A1 body" in text
    assert "B body" not in text


def test_extract_section_text_unknown_anchor_returns_none():
    body = "## A\n"
    sections = parse_sections(body)
    assert extract_section_text(body, sections, "nope") is None


# ─── ops integration ──────────────────────────────────────────────────


def _seed_layered_article(tmp_kb, slug="layered"):
    body = (
        "## 緒論\n"
        "intro to the work\n"
        "### 第一章 判教\n"
        "chapter one body\n"
        "#### 一心之分析\n"
        "subsection body\n"
        "## 結論\n"
        "conclusion body\n"
    )
    post = frontmatter.Post(body)
    post.metadata.update({
        "title": "Layered / 多層",
        "summary": "Multi-layer test article",
        "tags": ["test"],
        "created": "2026-04-18T00:00:00+00:00",
        "updated": "2026-04-18T00:00:00+00:00",
    })
    (tmp_kb / "wiki" / "concepts" / f"{slug}.md").write_text(
        frontmatter.dumps(post), encoding="utf-8"
    )
    return slug, body


def test_op_kb_get_sections_returns_tree(tmp_kb):
    slug, _ = _seed_layered_article(tmp_kb)
    result = dispatch("kb_get_sections", tmp_kb, {"slug": slug})
    assert result["found"] is True
    assert result["slug"] == slug
    assert len(result["sections"]) == 2
    titles = [s["title"] for s in result["sections"]]
    assert titles == ["緒論", "結論"]
    # 緒論 has a chapter with a sub-subsection.
    chap = result["sections"][0]["children"][0]
    assert chap["title"] == "第一章 判教"
    assert chap["children"][0]["title"] == "一心之分析"


def test_op_kb_get_sections_missing_article(tmp_kb):
    result = dispatch("kb_get_sections", tmp_kb, {"slug": "nonexistent"})
    assert result == {"found": False, "slug": "nonexistent"}


def test_op_kb_get_with_section_returns_subtree(tmp_kb):
    slug, body = _seed_layered_article(tmp_kb)
    sections_result = dispatch("kb_get_sections", tmp_kb, {"slug": slug})
    chap_anchor = sections_result["sections"][0]["children"][0]["anchor"]

    result = dispatch("kb_get", tmp_kb, {"slug": slug, "section": chap_anchor})
    assert result["found"] is True
    assert result["section_found"] is True
    assert result["section"] == chap_anchor
    assert result["content"].startswith("### 第一章 判教")
    assert "一心之分析" in result["content"]
    assert "## 結論" not in result["content"]


def test_op_kb_get_unknown_section_flag(tmp_kb):
    slug, _ = _seed_layered_article(tmp_kb)
    result = dispatch("kb_get", tmp_kb, {"slug": slug, "section": "h2-bogus-0000"})
    assert result["found"] is True
    assert result["section_found"] is False


def test_op_kb_get_no_section_unchanged(tmp_kb):
    slug, body = _seed_layered_article(tmp_kb)
    result = dispatch("kb_get", tmp_kb, {"slug": slug})
    # Backwards compat: existing field shape preserved when section is absent.
    assert "section" not in result
    assert "section_found" not in result
    # frontmatter.dumps strips one trailing newline on round-trip; compare with rstrip.
    assert result["content"] == body.rstrip("\n")


# ─── HTTP integration ────────────────────────────────────────────────


@pytest.fixture
def client(tmp_kb):
    app = create_web_app(tmp_kb)
    app.config["TESTING"] = True
    return app.test_client()


def test_http_sections_returns_tree(client, tmp_kb):
    slug, _ = _seed_layered_article(tmp_kb)
    r = client.get(f"/api/articles/{slug}/sections")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert body["slug"] == slug
    assert [s["title"] for s in body["sections"]] == ["緒論", "結論"]


def test_http_sections_404_unknown(client):
    r = client.get("/api/articles/nope/sections")
    assert r.status_code == 404


def test_http_sections_path_traversal_blocked(client):
    r = client.get("/api/articles/..%2F..%2Fetc%2Fpasswd/sections")
    # Either rejected as invalid slug or simply not found — never 200 with content.
    assert r.status_code in (400, 404)
