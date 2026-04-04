"""Lint module: health checks, consistency checks, and wiki enhancement."""

import json
import re
from pathlib import Path

import frontmatter

from .config import load_config, ensure_dirs
from .llm import chat


SYSTEM_PROMPT = """You are a knowledge base quality analyst. Your job is to review wiki articles
and identify issues, inconsistencies, and opportunities for improvement.

Be specific and actionable in your findings. Reference article titles and specific content."""


def lint(base_dir: Path | None = None) -> dict:
    """Run all lint checks on the wiki."""
    cfg = load_config(base_dir)
    ensure_dirs(cfg)

    results = {
        "structural": check_structural(cfg),
        "broken_links": check_broken_links(cfg),
        "orphans": check_orphans(cfg),
        "missing_metadata": check_missing_metadata(cfg),
    }

    # Count total issues
    total = sum(len(v) for v in results.values())
    results["total_issues"] = total

    return results


def lint_deep(base_dir: Path | None = None) -> str:
    """Use LLM to do a deep quality check on the wiki content."""
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])

    articles = []
    for md_file in sorted(concepts_dir.glob("*.md")):
        post = frontmatter.load(str(md_file))
        articles.append({
            "slug": md_file.stem,
            "title": post.metadata.get("title", md_file.stem),
            "summary": post.metadata.get("summary", ""),
            "tags": post.metadata.get("tags", []),
            "content_preview": post.content[:500],
        })

    if not articles:
        return "No articles to lint. Run `llmbase compile` first."

    articles_text = json.dumps(articles, indent=2, ensure_ascii=False)

    prompt = f"""Review this knowledge base wiki for quality issues.

Articles:
{articles_text}

Please check for and report:
1. **Inconsistencies**: Contradictory information across articles
2. **Missing data**: Important topics referenced but not yet covered
3. **Weak connections**: Concepts that should be linked but aren't
4. **New article candidates**: Connections between existing concepts that deserve their own article
5. **Suggested questions**: Further research questions worth exploring based on the knowledge base

Format your response as a structured markdown report."""

    return chat(prompt, system=SYSTEM_PROMPT, max_tokens=cfg["llm"]["max_tokens"])


def check_structural(cfg: dict) -> list[str]:
    """Check for structural issues."""
    issues = []
    concepts_dir = Path(cfg["paths"]["concepts"])
    meta_dir = Path(cfg["paths"]["meta"])

    if not (meta_dir / "_index.md").exists():
        issues.append("Missing master index file (_index.md)")

    if not (meta_dir / "index.json").exists():
        issues.append("Missing JSON index (index.json)")

    article_count = len(list(concepts_dir.glob("*.md")))
    if article_count == 0:
        issues.append("No articles in the wiki")

    return issues


def check_broken_links(cfg: dict) -> list[str]:
    """Find broken wiki-links [[target]] that don't have corresponding articles."""
    issues = []
    concepts_dir = Path(cfg["paths"]["concepts"])
    link_pattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
    existing_slugs = {f.stem.lower() for f in concepts_dir.glob("*.md")}

    for md_file in concepts_dir.glob("*.md"):
        content = md_file.read_text()
        for match in link_pattern.finditer(content):
            target = match.group(1).strip().lower().replace(" ", "-")
            if target not in existing_slugs:
                issues.append(f"Broken link in {md_file.stem}: [[{match.group(1)}]]")

    return issues


def check_orphans(cfg: dict) -> list[str]:
    """Find articles that are not linked to from any other article."""
    issues = []
    concepts_dir = Path(cfg["paths"]["concepts"])
    meta_dir = Path(cfg["paths"]["meta"])

    backlinks_path = meta_dir / "backlinks.json"
    if not backlinks_path.exists():
        return ["Backlinks map not built yet"]

    backlinks = json.loads(backlinks_path.read_text())
    linked_slugs = set(backlinks.keys())

    for md_file in concepts_dir.glob("*.md"):
        slug = md_file.stem.lower()
        if slug not in linked_slugs:
            issues.append(f"Orphan article (no incoming links): {md_file.stem}")

    return issues


def check_missing_metadata(cfg: dict) -> list[str]:
    """Find articles with missing or incomplete metadata."""
    issues = []
    concepts_dir = Path(cfg["paths"]["concepts"])

    for md_file in concepts_dir.glob("*.md"):
        post = frontmatter.load(str(md_file))
        slug = md_file.stem
        if not post.metadata.get("title"):
            issues.append(f"Missing title: {slug}")
        if not post.metadata.get("summary"):
            issues.append(f"Missing summary: {slug}")
        if not post.metadata.get("tags"):
            issues.append(f"Missing tags: {slug}")

    return issues


def auto_fix(base_dir: Path | None = None) -> list[str]:
    """Attempt to auto-fix common lint issues using LLM."""
    cfg = load_config(base_dir)
    ensure_dirs(cfg)
    concepts_dir = Path(cfg["paths"]["concepts"])
    fixes = []

    # Fix missing metadata
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

    return fixes
