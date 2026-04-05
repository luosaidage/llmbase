# LLMBase Project Guidelines

## Architecture
- Domain-agnostic: no hardcoded domains, all structure emerges from content via LLM
- Three-layer: raw/ → wiki/concepts/ → config.yaml (Karpathy pattern)
- Trilingual by default: EN / 中文 / 日本語
- All wiki-links use [[target]] syntax; resolved via alias map (aliases.json)

## Code Patterns
- LLM calls go through tools/llm.py:chat() — never call OpenAI directly
- Alias resolution via tools/resolve.py — always use resolve_link() for wiki-link targets
- Taxonomy is LLM-generated (not hardcoded) — tools/taxonomy.py
- Article slugs are pinyin/kebab-case; titles are bilingual "English / 中文"
- Never expose specific LLM provider names in public code or commits

## Auto-Fix Pipeline (tools/lint.py:auto_fix)
1. clean_garbage() — remove template stubs
2. fix metadata — LLM generates missing summary/tags
3. fix_broken_links() — alias-aware, only stubs for truly missing concepts
4. merge_duplicates() — LLM confirms, content 叠加进化
5. fix_uncategorized() — regenerate taxonomy

## Key Files
- tools/resolve.py — alias system (central to all link resolution)
- tools/xici.py — guided introduction generation
- tools/taxonomy.py — emergent LLM-generated categories
- wiki/_meta/ — aliases.json, taxonomy.json, health.json, backlinks.json

## CI Process
- TypeScript check: `cd frontend && npx tsc --noEmit`
- Python import check: `python -c "from tools.lint import lint; print('OK')"`
- Lint check: `python llmbase.py lint check`
- Build: `cd frontend && npx vite build`
