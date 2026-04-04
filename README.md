# LLMBase

LLM-powered personal knowledge base. Inspired by [Karpathy's approach](https://x.com/karpathy/status/2039805659525644595) — raw data goes in, an LLM compiles it into a structured, interlinked wiki, and you query/enhance it over time.

No vector database. No embeddings pipeline. Just markdown files, an LLM, and a simple CLI.

## How It Works

```
raw/  ──LLM compile──>  wiki/  ──query/lint──>  wiki/ (enhanced)
 │                        │                        │
 ├─ web articles          ├─ concept articles       ├─ filed answers
 ├─ papers                ├─ index + backlinks      ├─ new connections
 └─ local files           └─ cross-references       └─ health fixes
```

**Phase 1: Ingest** — Collect documents from URLs, local files, or directories into `raw/`

**Phase 2: Compile** — LLM reads raw docs, extracts concepts, writes wiki articles with `[[wiki-links]]`, builds index

**Phase 3: Query** — Ask questions against the wiki. Answers rendered as markdown, Marp slides, or charts. Outputs filed back into the wiki.

**Phase 4: Lint** — LLM health checks: find inconsistencies, broken links, orphan articles, suggest new connections

## Quick Start

```bash
# Install backend
pip install -e .

# Build frontend
cd frontend && npm install && npx vite build && cd ..

# Configure your LLM provider (any OpenAI-compatible API)
cp .env.example .env
# Edit .env with your API key and model

# Ingest some content
llmbase ingest url https://example.com/article
llmbase ingest file ./paper.md
llmbase ingest dir ./research-papers/

# Compile into wiki
llmbase compile new

# Ask questions
llmbase query "What are the key concepts?"
llmbase query "Compare X and Y" --format marp --file-back

# Search
llmbase search query "topic"

# Health check
llmbase lint check
llmbase lint deep

# Web UI
llmbase web          # Browse, search, Q&A at localhost:5555

# Agent API
llmbase serve        # HTTP API at localhost:5556
```

## LLM Provider

LLMBase works with any OpenAI-compatible API. Copy `.env.example` to `.env` and configure:

```bash
# OpenAI
LLMBASE_API_KEY=sk-...
LLMBASE_BASE_URL=https://api.openai.com/v1
LLMBASE_MODEL=gpt-4o

# OpenRouter (access 200+ models)
LLMBASE_API_KEY=sk-or-...
LLMBASE_BASE_URL=https://openrouter.ai/api/v1
LLMBASE_MODEL=anthropic/claude-sonnet-4-6

# Ollama (local, free)
LLMBASE_API_KEY=ollama
LLMBASE_BASE_URL=http://localhost:11434/v1
LLMBASE_MODEL=llama3.1
```

Also supports `OPENAI_API_KEY` / `OPENAI_BASE_URL` as fallback.

## Agent API

Agents can interact with the knowledge base via HTTP or Python:

```python
from tools.agent_api import KnowledgeBase

kb = KnowledgeBase("./")
kb.ingest("https://example.com/article")
kb.compile()
result = kb.ask("What is X?")
results = kb.search("keyword")
```

HTTP endpoints at `localhost:5556`:
- `POST /api/ingest` — Add documents
- `POST /api/compile` — Compile raw → wiki
- `POST /api/ask` — Q&A
- `GET /api/search?q=keyword` — Search
- `GET /api/articles` — List articles
- `GET /api/articles/<slug>` — Read article
- `POST /api/lint` — Health check

## Browser Integration

With [OpenCLI](https://github.com/jackwener/opencli) installed, ingest pages using your local Chrome session:

```bash
npm install -g @jackwener/opencli
llmbase ingest browse https://example.com/login-required-page
```

## Project Structure

```
llmbase/
├── raw/                  # Ingested source documents
├── wiki/
│   ├── _meta/           # Index files (index.json, backlinks.json)
│   ├── concepts/        # Wiki articles (compiled by LLM)
│   └── outputs/         # Filed query answers
├── tools/
│   ├── cli.py           # CLI entry point
│   ├── ingest.py        # Document ingestion
│   ├── compile.py       # LLM compilation
│   ├── query.py         # Q&A engine
│   ├── search.py        # Full-text search + web UI
│   ├── lint.py          # Health checks
│   ├── agent_api.py     # Agent HTTP API
│   ├── browser.py       # OpenCLI browser integration
│   ├── web.py           # Web frontend
│   ├── llm.py           # LLM client (OpenAI-compatible)
│   └── config.py        # Configuration
├── config.yaml
├── .env.example
└── pyproject.toml
```

## Design Philosophy

- **No vector DB needed** — At personal scale (~100-500 articles), index files + LLM context window are sufficient
- **Explorations add up** — Every query answer gets filed back into the wiki
- **LLM does the writing** — You rarely edit the wiki manually
- **Incremental compilation** — New raw data gets integrated, not reprocessed from scratch
- **Agent-first** — Built for LLM agents to use as a tool

## License

MIT
