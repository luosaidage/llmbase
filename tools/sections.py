"""
Markdown section parser with stable anchors.

Anchor format: ``h{level}-{slug-short}-{hash6}``
  - level: heading depth (1-6).
  - slug-short: ``normalize_title(title)`` truncated to 20 code points
    (CJK + ASCII alphanumeric retained; punctuation/whitespace stripped).
  - hash6: first 6 hex digits of sha1 over the joined ancestor chain
    (each title individually normalized, joined by U+203A "›"). Current
    title is the last element of the chain. (6 hex = 16M buckets — keeps
    birthday-paradox collisions <1% even on ~300-section 太虛 books.)

Stable across:
  - Trivial whitespace / punctuation / zero-width / BiDi-control edits in
    any title (normalized away before hashing).
  - Sibling reordering (position is not part of the hash).

Breaks on (caller's responsibility — handled via aliases in v0.7.2):
  - Title 字 changes anywhere in the ancestor chain.
  - Reparenting / structural moves.

Setext (=== / ---) headings are intentionally not parsed: 古籍 markdown
does not use them and disambiguating hr-vs-setext adds parser complexity
for zero practical gain on the target corpus.
"""

from __future__ import annotations

import hashlib
import re
from typing import Iterator, TypedDict

# Invisible / control / bidi / zero-width / ideographic-space / BOM.
# 古籍 OCR 常含 U+3000 (ideographic space)、U+200B (zero-width space)、
# U+202E (right-to-left override).
_INVISIBLE_RE = re.compile(
    r"[\u0000-\u001F\u200B-\u200F\u202A-\u202E\u2060-\u206F\u3000\uFEFF]+"
)

# Punctuation / brackets / whitespace stripped before slug-shortening + hashing.
# Leaves CJK characters, kana, and ASCII alphanumerics intact. Includes common
# 古籍 punctuation: em/en/horizontal dashes, ellipsis, interpunct — LLM compile
# routinely inserts/removes these, so they must not affect the hash.
_PUNCT_RE = re.compile(
    r"[《》「」『』（）()【】\[\]：:，。、？?！!"
    r"\u2014\u2013\u2015\u2026\u00B7\u30FB"  # — – ― … · ・
    r"\-_/\\.\s]+"
)

# ATX heading per CommonMark §4.2: 0–3 leading spaces, 1–6 ``#``, required
# space, optional trailing closing sequence (``#+`` preceded by whitespace).
# 4+ leading spaces would make it a code block, not a heading.
_HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.+?)(?:\s+#+)?\s*$")

# Fenced code block opener (CommonMark §4.5); closer must be the same fence
# character (` or ~), length >= opener, no info string, only whitespace after.
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}([`~]{3,})\s*$")

SLUG_MAX_CHARS = 20
# 6 hex = 16M buckets. The original spec called for 4 hex, but at the scale
# 太虛 books reach (~300 sections) the birthday-paradox collision probability
# at 4 hex is ~50% per book; at 6 hex it drops to ~0.3%. Collision suffixes
# (-2, -3) still work but depend on parse order, so minimising collisions
# also minimises the cases where sibling reorder shifts an anchor.
HASH_LEN = 6
ANCHOR_SEP = "›"  # U+203A — single codepoint, never appears in normalized titles.
EMPTY_SLUG_FALLBACK = "_"


class Section(TypedDict):
    """One node in the section tree.

    start/end are character offsets into the article body. body[start:end]
    yields the heading line + content + all descendant sections (subtree
    slice — useful for ``kb_get section=...`` extraction).
    """

    level: int
    title: str
    anchor: str
    start: int
    end: int
    children: list["Section"]


def normalize_title(title: str) -> str:
    """Strip invisibles + punctuation + whitespace; preserve CJK / kana / alphanumerics."""
    s = _INVISIBLE_RE.sub("", title)
    s = _PUNCT_RE.sub("", s)
    return s


def _slug_short(title: str) -> str:
    norm = normalize_title(title)
    return norm[:SLUG_MAX_CHARS] if norm else EMPTY_SLUG_FALLBACK


def _hash_hex(ancestor_titles: list[str]) -> str:
    joined = ANCHOR_SEP.join(normalize_title(t) for t in ancestor_titles)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:HASH_LEN]


def make_anchor(level: int, ancestor_titles: list[str]) -> str:
    """Build anchor for a heading given its level and ancestor chain (current title last)."""
    if not ancestor_titles:
        raise ValueError("ancestor_titles must contain at least the current title")
    return f"h{level}-{_slug_short(ancestor_titles[-1])}-{_hash_hex(ancestor_titles)}"


def _iter_headings(body: str) -> Iterator[tuple[int, int, str]]:
    """Yield (level, char_offset_of_line_start, raw_title) for each ATX heading.

    Skips headings inside fenced code blocks. Offsets are Python-string
    code-point indices into ``body`` so callers can slice directly with
    ``body[start:end]``. Heading regex follows CommonMark §4.2 (0–3 space
    indent max; trailing ``#+`` only stripped when preceded by whitespace,
    so ``## C#`` stays as ``C#``); fence closer follows §4.5 (same char,
    length ≥ opener, no info string).
    """
    fence_open: str | None = None
    cursor = 0
    for line in body.splitlines(keepends=True):
        if fence_open is None:
            m_fence = _FENCE_OPEN_RE.match(line)
            if m_fence:
                fence_open = m_fence.group(1)
            else:
                m_head = _HEADING_RE.match(line.rstrip("\n"))
                if m_head:
                    yield len(m_head.group(1)), cursor, m_head.group(2).strip()
        else:
            m_close = _FENCE_CLOSE_RE.match(line.rstrip("\n"))
            if m_close and m_close.group(1)[0] == fence_open[0] and len(m_close.group(1)) >= len(fence_open):
                fence_open = None
        cursor += len(line)


def parse_sections(body: str) -> list[Section]:
    """Parse a markdown body into a nested section tree.

    Returns top-level sections; descendants nest under ``children``. Anchor
    uniqueness is enforced per call: collisions append ``-2``, ``-3``, …
    """
    flat: list[dict] = []
    title_stack: list[tuple[int, str]] = []  # (level, title) ancestor chain.

    for level, start, title in _iter_headings(body):
        while title_stack and title_stack[-1][0] >= level:
            title_stack.pop()
        ancestors = [t for _, t in title_stack] + [title]
        flat.append({"level": level, "title": title, "start": start, "ancestors": ancestors})
        title_stack.append((level, title))

    n = len(flat)
    for i, s in enumerate(flat):
        end = len(body)
        for j in range(i + 1, n):
            if flat[j]["level"] <= s["level"]:
                end = flat[j]["start"]
                break
        s["end"] = end

    seen: dict[str, int] = {}
    for s in flat:
        base = make_anchor(s["level"], s["ancestors"])
        n_seen = seen.get(base, 0)
        s["anchor"] = base if n_seen == 0 else f"{base}-{n_seen + 1}"
        seen[base] = n_seen + 1

    return _nest(flat)


def _nest(flat: list[dict]) -> list[Section]:
    roots: list[Section] = []
    stack: list[Section] = []
    for s in flat:
        node: Section = {
            "level": s["level"],
            "title": s["title"],
            "anchor": s["anchor"],
            "start": s["start"],
            "end": s["end"],
            "children": [],
        }
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            stack[-1]["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def find_section(sections: list[Section], anchor: str) -> Section | None:
    """Walk the tree to find a section by exact anchor match. Returns None if absent."""
    for s in sections:
        if s["anchor"] == anchor:
            return s
        found = find_section(s["children"], anchor)
        if found is not None:
            return found
    return None


def extract_section_text(body: str, sections: list[Section], anchor: str) -> str | None:
    """Return body[start:end] for the named section subtree, or None if anchor not found."""
    s = find_section(sections, anchor)
    if s is None:
        return None
    return body[s["start"] : s["end"]]
