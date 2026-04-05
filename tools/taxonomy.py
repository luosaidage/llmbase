"""Taxonomy — hierarchical categories with multilingual labels."""

import json
import re
from pathlib import Path
from collections import defaultdict

import frontmatter

from .config import load_config

# Pre-defined top-level categories with multilingual labels
# Articles are mapped by matching their tags against these patterns
HIERARCHY = [
    {
        "id": "confucianism",
        "label": {"en": "Confucianism", "zh": "儒家", "ja": "儒教"},
        "match": ["confuci", "analects", "mencius", "mengzi", "lunyu", "junzi", "ren", "li-", "xiao",
                  "benevolence", "virtue", "filial", "ritual", "propriety", "four-books", "five-classics",
                  "doctrine-of-the-mean", "great-learning", "zhongyong", "daxue"],
        "children": [
            {"id": "analects", "label": {"en": "Analerta", "zh": "论语", "ja": "論語"},
             "match": ["analects", "lunyu", "xue-er", "confucius-analects"]},
            {"id": "mencius", "label": {"en": "Mencius", "zh": "孟子", "ja": "孟子"},
             "match": ["mencius", "mengzi", "mencius-"]},
            {"id": "daxue", "label": {"en": "Great Learning", "zh": "大学", "ja": "大学"},
             "match": ["great-learning", "daxue", "sincerity", "self-cultivation"]},
            {"id": "zhongyong", "label": {"en": "Doctrine of the Mean", "zh": "中庸", "ja": "中庸"},
             "match": ["mean", "zhongyong", "central-harmony", "zhonghe"]},
            {"id": "confucian-ethics", "label": {"en": "Ethics & Virtues", "zh": "伦理道德", "ja": "倫理道徳"},
             "match": ["ethics", "virtue", "moral", "benevolent", "governance", "trust"]},
        ]
    },
    {
        "id": "buddhism",
        "label": {"en": "Buddhism", "zh": "佛教", "ja": "仏教"},
        "match": ["buddh", "sutra", "dharma", "nirvana", "bodhisattva", "arhat", "tathagata",
                  "agama", "mahayana", "meditation", "karmic", "sangha", "tripitaka",
                  "brahma", "contemplation", "defilement", "liberation", "eight-noble"],
        "children": [
            {"id": "agama", "label": {"en": "Āgama Sūtras", "zh": "阿含经", "ja": "阿含経"},
             "match": ["agama", "changahan", "shi-bao"]},
            {"id": "cosmology", "label": {"en": "Cosmology", "zh": "宇宙观", "ja": "宇宙論"},
             "match": ["cosmolog", "heaven", "caste", "realm", "world"]},
            {"id": "practice", "label": {"en": "Practice & Path", "zh": "修行", "ja": "修行"},
             "match": ["meditat", "practice", "path", "contemplat", "liberation", "stages"]},
            {"id": "doctrine", "label": {"en": "Doctrine", "zh": "教义", "ja": "教義"},
             "match": ["doctrine", "dependent", "aggregate", "noble", "dharma", "truth"]},
        ]
    },
    {
        "id": "daoism",
        "label": {"en": "Daoism", "zh": "道家", "ja": "道教"},
        "match": ["dao", "tao", "laozi", "zhuangzi", "wuwei", "yin-yang", "daodejing"],
        "children": []
    },
    {
        "id": "mohism",
        "label": {"en": "Mohism", "zh": "墨家", "ja": "墨家"},
        "match": ["mohis", "mozi", "jian-ai", "universal-love"],
        "children": []
    },
    {
        "id": "classics",
        "label": {"en": "Classical Studies", "zh": "经学", "ja": "経学"},
        "match": ["classic", "text-stud", "hermeneutic", "translation", "manuscript", "canon",
                  "commentary", "scholarship", "textual", "philolog"],
        "children": []
    },
    {
        "id": "non-target",
        "label": {"en": "Non-target (Archive)", "zh": "非目标（存档）", "ja": "対象外（アーカイブ）"},
        "match": ["non-target", "ollama", "gemma", "quantiz", "gguf", "llm-tool", "ai-model"],
        "children": []
    },
]


def build_taxonomy(base_dir: Path | None = None, lang: str = "zh") -> list[dict]:
    """Build hierarchical taxonomy from articles, with labels in the requested language."""
    cfg = load_config(base_dir)
    concepts_dir = Path(cfg["paths"]["concepts"])

    if not concepts_dir.exists():
        return []

    # Load all articles
    articles = []
    for md_file in sorted(concepts_dir.glob("*.md")):
        post = frontmatter.load(str(md_file))
        articles.append({
            "slug": md_file.stem,
            "title": post.metadata.get("title", md_file.stem),
            "tags": [t.lower().replace(" ", "-") for t in post.metadata.get("tags", [])],
            "summary": post.metadata.get("summary", ""),
        })

    # Assign articles to categories
    assigned = set()
    result = []

    for cat in HIERARCHY:
        cat_articles, child_cats = _match_category(cat, articles, assigned, lang)
        if cat_articles or child_cats:
            entry = {
                "id": cat["id"],
                "label": cat["label"].get(lang, cat["label"].get("en", cat["id"])),
                "count": len(cat_articles),
                "articles": cat_articles,
                "children": child_cats,
            }
            # Total count includes children
            entry["total"] = entry["count"] + sum(c["count"] for c in child_cats)
            result.append(entry)

    # Collect unassigned into "Other"
    unassigned = [a for a in articles if a["slug"] not in assigned]
    if unassigned:
        other_label = {"en": "Other", "zh": "其他", "ja": "その他"}
        result.append({
            "id": "other",
            "label": other_label.get(lang, "Other"),
            "count": len(unassigned),
            "total": len(unassigned),
            "articles": [{"slug": a["slug"], "title": a["title"]} for a in unassigned],
            "children": [],
        })

    return result


def _match_category(cat: dict, articles: list, assigned: set, lang: str) -> tuple[list, list]:
    """Match articles to a category and its children."""
    cat_patterns = [p.lower() for p in cat.get("match", [])]

    # Process children first (more specific matches)
    child_results = []
    for child in cat.get("children", []):
        child_patterns = [p.lower() for p in child.get("match", [])]
        child_articles = []
        for a in articles:
            if a["slug"] in assigned:
                continue
            slug_tags = a["slug"] + " " + " ".join(a["tags"])
            if any(p in slug_tags for p in child_patterns):
                child_articles.append({"slug": a["slug"], "title": a["title"]})
                assigned.add(a["slug"])
        if child_articles:
            child_results.append({
                "id": child["id"],
                "label": child["label"].get(lang, child["label"].get("en", child["id"])),
                "count": len(child_articles),
                "articles": child_articles,
                "children": [],
            })

    # Then match remaining to parent
    parent_articles = []
    for a in articles:
        if a["slug"] in assigned:
            continue
        slug_tags = a["slug"] + " " + " ".join(a["tags"])
        if any(p in slug_tags for p in cat_patterns):
            parent_articles.append({"slug": a["slug"], "title": a["title"]})
            assigned.add(a["slug"])

    return parent_articles, child_results


def load_taxonomy(base_dir: Path | None = None) -> dict:
    """Load cached taxonomy."""
    cfg = load_config(base_dir)
    meta_dir = Path(cfg["paths"]["meta"])
    path = meta_dir / "taxonomy.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"categories": []}
