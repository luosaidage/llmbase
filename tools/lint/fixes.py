"""Lint fixes — auto-repair pipeline for the knowledge base."""

import json
import re
from pathlib import Path

import frontmatter

from ..config import load_config, ensure_dirs
from ..llm import chat
from .checks import (
    check_stubs, check_dirty_tags, check_uncategorized,
)
from .dedup import merge_duplicates


# ─── Customizable constants ──────────────────────────────────────
# Override to change the LLM instructions for stub generation.
# See tools/compile.py docstring for the full constants contract.

STUB_SYSTEM_PROMPT = """You are a trilingual knowledge base compiler. Generate a stub article
for a missing concept based on how existing articles reference it.

Rules:
- Write in three languages: English, 中文, 日本語 (each under an h2 header)
- Keep it concise but informative (2-3 paragraphs per language)
- Use [[wiki-link]] for cross-references to related concepts
- Base your content ONLY on what can be reasonably inferred from the provided contexts
- If you cannot determine what the concept is about, respond with exactly: CANNOT_GENERATE"""



def normalize_tags(base_dir: Path | None = None) -> list[str]:
    """System-wide tag normalization: merge synonymous tags using LLM.

    1. Collect all unique tags with frequencies
    2. Ask LLM to group synonymous tags and pick a canonical form
    3. Rewrite all articles with normalized tags

    This runs ONCE (or occasionally), not on every auto_fix.
    """
    from collections import Counter

    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])

    # Collect all tags with frequencies
    tag_counter = Counter()
    for md_file in concepts_dir.glob("*.md"):
        post = frontmatter.load(str(md_file))
        for t in post.metadata.get("tags", []):
            tag_counter[t.lower()] += 1

    if len(tag_counter) < 5:
        return []

    # Build compact tag list for LLM (top 80 tags to avoid overflow)
    tag_list = "\n".join(
        f"- {tag} ({count})" for tag, count in tag_counter.most_common(80)
    )

    prompt = (
        f"Here are {len(tag_counter)} tags from a knowledge base, with article counts:\n\n"
        f"{tag_list}\n\n"
        f"Group SYNONYMOUS tags (same concept, different wording) and pick ONE canonical form for each group.\n"
        f"Only group truly synonymous tags — 'buddhism' and 'buddhist-ethics' are NOT synonyms.\n\n"
        f"Output JSON: a dict mapping old_tag → canonical_tag. Only include tags that need renaming.\n"
        f"Example: {{\"confucian-philosophy\": \"confucianism\", \"daoist-philosophy\": \"daoism\"}}\n"
        f"Output ONLY the JSON dict, nothing else."
    )

    try:
        response = chat(prompt, max_tokens=2048)
        # Parse JSON from response
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return []

        import json
        tag_map = json.loads(text[start:end + 1])
    except Exception:
        return []

    if not tag_map:
        return []

    # Apply tag renaming across all articles
    fixes = []
    for md_file in concepts_dir.glob("*.md"):
        post = frontmatter.load(str(md_file))
        tags = post.metadata.get("tags", [])
        new_tags = []
        changed = False
        for t in tags:
            canonical = tag_map.get(t.lower(), t)
            new_tags.append(canonical)
            if canonical != t:
                changed = True

        if changed:
            post.metadata["tags"] = sorted(set(new_tags))
            md_file.write_text(frontmatter.dumps(post), encoding="utf-8")
            fixes.append(f"Normalized tags for {md_file.stem}")

    return fixes



def fix_dirty_tags(base_dir: Path | None = None) -> list[str]:
    """Clean up dirty tags by removing bad ones and regenerating via LLM."""
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])

    dirty_articles = check_dirty_tags(cfg)
    if not dirty_articles:
        return []

    fixes = []
    for issue in dirty_articles:
        slug = issue.split("Dirty tags in ")[1].split(":")[0]
        path = concepts_dir / f"{slug}.md"
        if not path.exists():
            continue

        post = frontmatter.load(str(path))
        old_tags = post.metadata.get("tags", [])

        # Keep only clean tags
        clean = [t for t in old_tags if isinstance(t, str) and len(t) <= 40
                 and len(t.split()) <= 4
                 and not any(p in t.lower() for p in [
                     "we need", "the user", "output", "list ", "tags:",
                     "tag1", "tag2", "interpret", "based on",
                 ])]

        if len(clean) < 2:
            # Too few clean tags remaining — ask LLM for new ones
            title = post.metadata.get("title", slug)
            prompt = f"List 2-4 relevant tags for this article (comma-separated, lowercase, short keywords only):\n\n# {title}\n\n{post.content[:2000]}"
            try:
                response = chat(prompt, max_tokens=128)
                new_tags = [t.strip().lower() for t in response.split(",") if t.strip() and len(t.strip()) <= 40]
                clean = list(set(clean + new_tags))
            except Exception:
                pass

        if set(clean) != set(old_tags):
            post.metadata["tags"] = sorted(clean)
            path.write_text(frontmatter.dumps(post), encoding="utf-8")
            fixes.append(f"Cleaned tags for {slug}: {old_tags} → {clean}")

    return fixes



def clean_garbage(base_dir: Path | None = None) -> list[str]:
    """Remove garbage/empty stub articles detected by check_stubs.

    Returns list of removed article slugs.
    """
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])

    stubs = check_stubs(cfg)
    if not stubs:
        return []

    removed = []
    for issue in stubs:
        # Parse "Unfilled template: slug" or "Placeholder stub: slug"
        slug = issue.split(": ", 1)[-1].split(" (")[0]
        path = concepts_dir / f"{slug}.md"
        if path.exists():
            path.unlink()
            removed.append(slug)

    if removed:
        from ..compile import rebuild_index
        rebuild_index(base_dir)

    return removed



def fix_uncategorized(base_dir: Path | None = None) -> list[str]:
    """Regenerate taxonomy to re-classify uncategorized articles.

    Since taxonomy is now LLM-generated (not hardcoded), the fix is
    simply to regenerate it — the LLM will find the right categories.
    """
    uncategorized = check_uncategorized(load_config(base_dir), base_dir)
    if not uncategorized:
        return []

    from ..taxonomy import generate_taxonomy
    generate_taxonomy(base_dir)
    return [f"Regenerated taxonomy to re-classify {len(uncategorized)} uncategorized article(s)"]



def fix_broken_links(base_dir: Path | None = None, max_stubs: int = 10) -> list[str]:
    """Generate stub articles for broken wiki-link targets.

    Only creates stubs for truly unresolvable links (after alias resolution).
    Strategy A: Use LLM to generate a trilingual stub from referencing context.
    Strategy B: If LLM fails, create a minimal placeholder stub.
    Returns list of fix descriptions.
    """
    from ..resolve import load_aliases, resolve_link

    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])
    meta_dir = Path(cfg["paths"]["meta"])
    link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
    existing_slugs = {f.stem.lower() for f in concepts_dir.glob("*.md")}
    aliases = load_aliases(meta_dir)

    # Collect broken links grouped by target slug
    # target_slug -> [(source_slug, context_snippet)]
    missing: dict[str, list[tuple[str, str]]] = {}

    for md_file in concepts_dir.glob("*.md"):
        content = md_file.read_text()
        for match in link_pattern.finditer(content):
            raw_target = match.group(1).strip()
            # Skip if resolvable via aliases
            resolved = resolve_link(raw_target, aliases)
            if resolved and resolved in existing_slugs:
                continue
            # Also skip if simple normalization works
            simple = raw_target.lower().replace(" ", "-")
            if simple in existing_slugs:
                continue
            target_slug = simple
            # Extract context around the link (200 chars each side)
            start = max(0, match.start() - 200)
            end = min(len(content), match.end() + 200)
            snippet = content[start:end].strip()
            missing.setdefault(target_slug, []).append((md_file.stem, snippet))

    if not missing:
        return []

    fixes = []
    from datetime import datetime, timezone

    for target_slug, refs in list(missing.items())[:max_stubs]:
        # Build context from all referencing articles
        contexts = "\n\n---\n\n".join(
            f"From article '{src}':\n...{snippet}..."
            for src, snippet in refs[:5]  # cap context to 5 references
        )
        ref_slugs = [src for src, _ in refs]

        # Strategy A: LLM-generated stub
        article_content = None
        title = target_slug.replace("-", " ").title()
        summary = ""
        tags = ["stub"]

        try:
            prompt = (
                f"The concept '{target_slug}' is referenced in existing articles but has no article yet.\n\n"
                f"Here is how it appears in context:\n\n{contexts}\n\n"
                f"Generate a wiki article in this exact format (no extra text before or after):\n\n"
                f"title: English Title / 中文标题\n"
                f"summary: One-line summary in English\n"
                f"tags: tag1, tag2\n"
                f"---\n"
                f"## English\n\n(content)\n\n"
                f"## 中文\n\n(内容)\n\n"
                f"## 日本語\n\n(内容)"
            )
            response = chat(prompt, system=STUB_SYSTEM_PROMPT, max_tokens=2048)

            if "CANNOT_GENERATE" not in response and len(response.strip()) > 100:
                # Parse the LLM response
                lines = response.strip().split("\n")
                body_start = 0
                for i, line in enumerate(lines):
                    if line.strip() == "---":
                        body_start = i + 1
                        break
                    if ":" in line:
                        key, _, val = line.partition(":")
                        key = key.strip().lower()
                        val = val.strip()
                        if key == "title" and val:
                            title = val
                        elif key == "summary" and val:
                            summary = val
                        elif key == "tags" and val:
                            tags = [t.strip().lower() for t in val.split(",")]
                            if "stub" not in tags:
                                tags.append("stub")

                article_content = "\n".join(lines[body_start:]).strip()
        except Exception:
            pass  # Fall through to Strategy B

        # Strategy B: minimal stub
        if not article_content or len(article_content) < 50:
            referrers = ", ".join(f"[[{s}]]" for s in ref_slugs[:5])
            article_content = (
                f"## English\n\n"
                f"This article has not been fully written yet. "
                f"It is referenced by: {referrers}.\n\n"
                f"## 中文\n\n"
                f"本条目尚未完成撰写。引用来源：{referrers}。\n\n"
                f"## 日本語\n\n"
                f"この記事はまだ完成していません。参照元：{referrers}。"
            )
            summary = summary or "Stub article — referenced but not yet written"
            title = target_slug.replace("-", " ").title()

        # Write the stub article
        post = frontmatter.Post(article_content)
        post.metadata["title"] = title
        post.metadata["summary"] = summary
        post.metadata["tags"] = tags
        post.metadata["stub"] = True
        post.metadata["created"] = datetime.now(timezone.utc).isoformat()
        post.metadata["updated"] = datetime.now(timezone.utc).isoformat()

        article_path = concepts_dir / f"{target_slug}.md"
        article_path.write_text(frontmatter.dumps(post), encoding="utf-8")
        fixes.append(f"Created stub for broken link: {target_slug} (referenced by {len(refs)} article(s))")

    # Rebuild index so new stubs appear in search and backlinks
    if fixes:
        from ..compile import rebuild_index
        rebuild_index(base_dir)

    return fixes



def auto_fix(base_dir: Path | None = None) -> list[str]:
    """Attempt to auto-fix common lint issues using LLM.

    Pipeline order:
    1. Clean garbage stubs (remove before other fixes)
    2. Fix missing metadata (summary, tags)
    3. Fix broken links (generate stubs)
    4. Merge duplicates
    5. Regenerate taxonomy for uncategorized
    """
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])
    fixes = []

    # 1. Clean garbage first
    garbage = clean_garbage(base_dir)
    if garbage:
        fixes.append(f"Cleaned {len(garbage)} garbage article(s): {', '.join(garbage[:5])}")

    # 2. Fix dirty tags (prompt leaks, sentences in tag fields)
    tag_clean = fix_dirty_tags(base_dir)
    fixes.extend(tag_clean)

    # 3. Normalize synonymous tags (confucian-philosophy → confucianism, etc.)
    tag_norm = normalize_tags(base_dir)
    fixes.extend(tag_norm)

    # 4. Fix missing metadata
    for md_file in concepts_dir.glob("*.md"):
        post = frontmatter.load(str(md_file))
        needs_fix = False

        if not post.metadata.get("summary") and post.content.strip():
            prompt = f"Write a one-line summary for this article:\n\n# {post.metadata.get('title', md_file.stem)}\n\n{post.content[:2000]}"
            summary = chat(prompt, max_tokens=256)
            post.metadata["summary"] = summary.strip().strip('"')
            needs_fix = True

        if not post.metadata.get("tags") and post.content.strip():
            prompt = f"List 2-4 relevant tags for this article (comma-separated, lowercase):\n\n# {post.metadata.get('title', md_file.stem)}\n\n{post.content[:2000]}"
            tags = chat(prompt, max_tokens=128)
            post.metadata["tags"] = [t.strip().lower() for t in tags.split(",")]
            needs_fix = True

        if needs_fix:
            md_file.write_text(frontmatter.dumps(post), encoding="utf-8")
            fixes.append(f"Fixed metadata for: {md_file.stem}")

    # Fix broken links by generating stubs
    health_cfg = cfg.get("health", {})
    if health_cfg.get("auto_fix_broken_links", True):
        max_stubs = health_cfg.get("max_stubs_per_run", 10)
        link_fixes = fix_broken_links(base_dir, max_stubs)
        fixes.extend(link_fixes)

    # Merge duplicate articles
    merge_fixes = merge_duplicates(base_dir)
    fixes.extend(merge_fixes)

    # Fix uncategorized articles by regenerating taxonomy
    tag_fixes = fix_uncategorized(base_dir)
    fixes.extend(tag_fixes)

    from ..hooks import emit
    emit("after_auto_fix", fix_count=len(fixes), fixes=fixes[:20])

    return fixes

