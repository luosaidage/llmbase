"""Tests for tools.normalize — paragraph merge + head-level rewrite (v0.7.3)."""

import pytest

from tools.normalize import (
    CLOSING_WRAPPERS,
    SENTENCE_TERMINATORS,
    HeadRule,
    normalize_heads,
    normalize_paragraphs,
)


# ─── normalize_paragraphs ──────────────────────────────────────────────


def test_paragraphs_merges_non_terminator_line():
    src = "甲曰，\n夫道者\n"
    assert normalize_paragraphs(src) == "甲曰，夫道者\n"


def test_paragraphs_keeps_break_after_terminator():
    src = "甲曰道也。\n乙曰德也。\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_merges_chain_across_multiple_lines():
    src = "一，\n二，\n三，\n四。\n"
    assert normalize_paragraphs(src) == "一，二，三，四。\n"


def test_paragraphs_preserves_blank_line_as_boundary():
    src = "甲曰，\n夫道者\n\n乙曰，\n夫德者\n"
    assert normalize_paragraphs(src) == "甲曰，夫道者\n\n乙曰，夫德者\n"


def test_paragraphs_terminator_followed_by_closing_wrapper():
    # 。」 still counts as terminated (』 may legitimately follow 。).
    src = "甲曰『道』。\n乙答曰\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_does_not_merge_into_heading():
    src = "前一段，\n## 標題\n後一段\n"
    # The "前一段，" line has no terminator, but must not swallow the heading.
    assert normalize_paragraphs(src) == src


def test_paragraphs_does_not_merge_into_empty_heading():
    # Empty ATX headings (``#``, ``## ``) are valid per CommonMark §4.2
    # and must still be treated as structural so paragraph merging
    # doesn't swallow them.
    for heading in ("#", "##", "### ", "###### "):
        src = f"前一段，\n{heading}\n後一段\n"
        assert normalize_paragraphs(src) == src, heading


def test_paragraphs_does_not_merge_heading_into_body():
    src = "## 標題\n後一段，\n續之\n"
    assert normalize_paragraphs(src) == "## 標題\n後一段，續之\n"


def test_paragraphs_preserves_list_items():
    src = "一曰，\n- 道\n- 德\n續之\n"
    # "一曰，" must not absorb "- 道"; list items must not merge with each other or with "續之".
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_list_item_continuation():
    # Indented lazy-continuation of a list item is part of the list block
    # (CommonMark §5.2); a following plain line must not merge into it.
    src = "- item\n  cont\nnext\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_list_ends_on_blank_line():
    # Blank line closes the list container; normal merging resumes.
    src = "- item\n  cont\n\n甲，\n乙\n"
    assert normalize_paragraphs(src) == "- item\n  cont\n\n甲，乙\n"


def test_paragraphs_preserves_blockquote_continuation():
    # Lazy-continuation of a blockquote (§5.1) belongs to the blockquote.
    src = "> 引也\n續之\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_html_block_inner():
    # HTML block (§4.6) inner lines are not merged; the block extends
    # until the next blank line.
    src = "<div>\nfoo\nbar\n</div>\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_inline_html_does_not_open_block():
    # Inline-only HTML tags (``<span>``, ``<a>``) are not type-6 block
    # starters — the paragraph merge must still run across them.
    src = "甲，\n<span>乙</span>\n"
    assert normalize_paragraphs(src) == "甲，<span>乙</span>\n"


def test_paragraphs_preserves_link_reference_definition():
    # Link reference definition (§4.7) must not be merged into the
    # paragraph above; otherwise the reference resolution breaks.
    src = "前文，\n[ref]: https://example.com\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_indented_code_block():
    # 4+ indent after a blank line is an indented code block (§4.4);
    # consecutive indented lines must not merge (or lose their indent).
    src = "前文。\n\n    code_a\n    code_b\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_indented_code_ends_on_blank_line():
    src = "\n    a\n    b\n\n甲，\n乙\n"
    assert normalize_paragraphs(src) == "\n    a\n    b\n\n甲，乙\n"


def test_paragraphs_preserves_tab_indented_code():
    # Tab-indented code is also a valid indented code block (§4.4).
    src = "\n\tcode\n\tline\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_indented_code_after_heading():
    # §4.4 lets an indented code block follow any non-paragraph block,
    # not just a blank line — heading, list, blockquote, etc.
    src = "# H\n    a\n    b\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_line_after_indented_code_does_not_merge():
    # The first non-indented line after an indented code block must
    # start a fresh paragraph — it cannot be merged into the last
    # code line (that would corrupt the code).
    src = "\n    a,\nnext,\nline\n"
    assert normalize_paragraphs(src) == "\n    a,\nnext,line\n"


def test_paragraphs_fence_inside_list_keeps_container():
    # A fenced code block inside a list item must not drop the list
    # container; later list-continuation lines must still be protected
    # from merging.
    src = "- item\n  ```\n  code\n  ```\n  cont,\n  next\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_multi_paragraph_list_item():
    # CommonMark §5.2: a blank line inside a list item separates two
    # paragraphs of the same item; indented continuation after the
    # blank is still list content and must not merge.
    src = "- item\n\n  cont,\n  next\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_multi_paragraph_list_item_deep():
    # Same rule when the blank follows a continuation paragraph, not
    # the list marker itself.
    src = "- item\n  first,\n\n  second,\n  third\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_blockquote():
    src = "甲曰，\n> 引也\n乙答\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_table_row():
    src = "列也，\n| 甲 | 乙 |\n| -- | -- |\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_thematic_break():
    src = "終也，\n---\n次段\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_fenced_code_verbatim():
    # Inside a fence, nothing gets merged — even lines that look like CJK prose.
    src = "前文，\n```\n甲曰，\n夫道者\n```\n後文\n"
    expected = "前文，\n```\n甲曰，\n夫道者\n```\n後文\n"
    assert normalize_paragraphs(src) == expected


def test_paragraphs_fence_opener_with_info_string():
    src = "```python\nx = 1\ny = 2\n```\n"
    # Code inside the fence is never merged.
    assert normalize_paragraphs(src) == src


def test_paragraphs_tilde_fences():
    src = "前文，\n~~~\n甲，\n乙\n~~~\n後文\n"
    assert normalize_paragraphs(src) == src


def test_paragraphs_preserves_missing_trailing_newline():
    src = "甲，\n乙"
    assert normalize_paragraphs(src) == "甲，乙"


def test_paragraphs_preserves_multiple_trailing_newlines():
    # ``splitlines()`` drops trailing empty lines; verify both passes
    # restore the exact trailing-newline count from the input.
    assert normalize_paragraphs("a\n\n") == "a\n\n"
    assert normalize_paragraphs("甲，\n乙\n\n\n") == "甲，乙\n\n\n"


def test_paragraphs_mixed_endings_preserve_trailing_newline():
    # Mixed CRLF+LF is pathological but shouldn't drop the final newline.
    assert normalize_paragraphs("a。\r\nb。\n").endswith("\r\n")


def test_paragraphs_lstrips_lazy_continuation():
    # Leading whitespace on a continuation line is lazy-continuation per
    # CommonMark; dropping it is correct.
    src = "甲，\n   乙\n"
    assert normalize_paragraphs(src) == "甲，乙\n"


def test_paragraphs_empty_input():
    assert normalize_paragraphs("") == ""


def test_paragraphs_preserves_crlf():
    # CRLF inputs keep their line-ending style on output (data-preservation).
    src = "甲，\r\n乙。\r\n"
    assert normalize_paragraphs(src) == "甲，乙。\r\n"


def test_paragraphs_override_terminators(monkeypatch):
    # Downstream can add e.g. ``，`` to SENTENCE_TERMINATORS to stop
    # merging on it. Verify the override is honored.
    monkeypatch.setattr("tools.normalize.SENTENCE_TERMINATORS", "。！？；.!?;，")
    src = "甲，\n乙。\n"
    assert normalize_paragraphs(src) == src  # ``，`` now terminates


def test_paragraphs_default_constants_shape():
    # Guard against accidental drift of the default sets.
    assert "。" in SENTENCE_TERMINATORS and "." in SENTENCE_TERMINATORS
    assert "」" in CLOSING_WRAPPERS and ")" in CLOSING_WRAPPERS


# ─── normalize_heads ───────────────────────────────────────────────────


TAIXU_PACK: list[HeadRule] = [
    {"pattern": r"^第[一二三四五六七八九十百千零]+[章編篇卷]", "level": 2},
    {"pattern": r"^[甲乙丙丁戊己庚辛壬癸]、", "level": 3},
]


def test_heads_no_rules_is_noop():
    src = "# 書名\n## 章一\n內文\n"
    assert normalize_heads(src, []) == src


def test_heads_rewrites_by_pattern():
    src = "### 第一章 判教\n內文\n# 甲、釋義\n"
    expected = "## 第一章 判教\n內文\n### 甲、釋義\n"
    assert normalize_heads(src, TAIXU_PACK) == expected


def test_heads_non_matching_heading_preserved():
    src = "## 敘論\n內文\n"
    assert normalize_heads(src, TAIXU_PACK) == src


def test_heads_first_match_wins():
    rules: list[HeadRule] = [
        {"pattern": r"章", "level": 2},
        {"pattern": r"章", "level": 4},  # would have been applied but earlier rule wins
    ]
    src = "###### 第一章\n"
    assert normalize_heads(src, rules) == "## 第一章\n"


def test_heads_preserves_indent_and_closer():
    # ATX closer ``##`` after the title is preserved; 0-3 space indent too.
    src = "   #### 第一章 判教 ##\n"
    expected = "   ## 第一章 判教 ##\n"
    assert normalize_heads(src, TAIXU_PACK) == expected


def test_heads_skips_fenced_code():
    # ``## 第一章`` inside a fence is not a heading; must not be rewritten.
    src = "# 書\n```\n## 第一章 fake\n```\n## 第一章 real\n"
    expected = "# 書\n```\n## 第一章 fake\n```\n## 第一章 real\n"
    assert normalize_heads(src, TAIXU_PACK) == expected


def test_heads_skips_html_block():
    # ``#`` inside an HTML block is not a heading per CommonMark §4.2;
    # must not be rewritten by rules.
    src = "<div>\n# 第一章 fake\n</div>\n\n### 第一章 real\n"
    expected = "<div>\n# 第一章 fake\n</div>\n\n## 第一章 real\n"
    assert normalize_heads(src, TAIXU_PACK) == expected


def test_heads_rejects_invalid_level():
    with pytest.raises(ValueError):
        normalize_heads("# x\n", [{"pattern": r"x", "level": 7}])
    with pytest.raises(ValueError):
        normalize_heads("# x\n", [{"pattern": r"x", "level": 0}])


def test_heads_preserves_missing_trailing_newline():
    src = "#### 第一章"
    assert normalize_heads(src, TAIXU_PACK) == "## 第一章"


def test_heads_empty_input():
    assert normalize_heads("", TAIXU_PACK) == ""


def test_heads_preserves_crlf():
    src = "### 第一章\r\n內文\r\n"
    assert normalize_heads(src, TAIXU_PACK) == "## 第一章\r\n內文\r\n"


# ─── composition ───────────────────────────────────────────────────────


def test_paragraphs_then_heads_composes_cleanly():
    src = (
        "#### 第一章 判教\n"
        "夫道者，\n"
        "萬物之始也。\n"
        "\n"
        "# 甲、釋義\n"
        "未終，\n"
        "續之。\n"
    )
    expected = (
        "## 第一章 判教\n"
        "夫道者，萬物之始也。\n"
        "\n"
        "### 甲、釋義\n"
        "未終，續之。\n"
    )
    assert normalize_heads(normalize_paragraphs(src), TAIXU_PACK) == expected
