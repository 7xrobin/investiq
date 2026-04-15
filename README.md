# KyronInvest

AI-powered investment research assistant for expat professionals in Germany. Ask questions about investment regulations, portfolio theory, and financial products — get grounded, cited answers drawn from regulatory documents and academic literature, streamed in real time.

---

## Tech Stack

### Backend

| Package | Version | Role |
|---|---|---|
| **Django** | 5.0 | Web framework — views, ORM, auth, admin, session management |
| **django-environ** | 0.11 | Reads `.env` files into Django settings; keeps secrets out of code |
| **django-extensions** | 3.2 | Developer utilities (`shell_plus`, `show_urls`, `runserver_plus`) |
| **Whitenoise** | 6.7 | Serves static files directly from Django in production (no nginx needed) |

### AI / RAG Pipeline

| Package | Version | Role |
|---|---|---|
| **LangChain** | 0.3 | Core abstractions — chains, runnables, tool-calling agent, prompt templates |
| **langchain-openai** | 0.2 | LangChain bindings for OpenAI Chat and Embedding models |
| **langchain-community** | 0.3 | `SQLChatMessageHistory` — persists conversation memory to SQLite |
| **langchain-chroma** | 0.1 | LangChain bindings for the Chroma vector store |
| **openai** | 1.40 | Direct OpenAI SDK (used by langchain-openai under the hood) |
| **tiktoken** | 0.7 | Token counting for chunking and context-window management |
| **LangSmith** | ≥0.1.112 | Optional tracing and observability for LangChain runs |

### Vector Store & Memory

| Package | Role |
|---|---|
| **Chroma** (`chromadb`) | Local vector database. Persists embeddings to `data/chroma/` (SQLite-backed). Handles similarity search with metadata filtering (jurisdiction, source type). |
| **SQLAlchemy** | Database toolkit used by `SQLChatMessageHistory` to read/write the SQLite memory file at `data/memory.sqlite3`. |
| **SQLite** (stdlib) | Two separate databases: `db.sqlite3` for all Django models (users, conversations, citations); `data/memory.sqlite3` for LangChain conversation history checkpoints. |

> **Why two SQLite files?** The Django DB holds structured relational data with its own migration lifecycle. The memory DB is owned by LangChain and stores raw message sequences — different schemas, different access patterns, no benefit to mixing them.

### Document Ingestion

| Package | Role |
|---|---|
| **pypdf** | Extracts text from PDF files page-by-page |
| **httpx** | Async-capable HTTP client for fetching web sources (BaFin, gesetze-im-internet.de, etc.) |
| **beautifulsoup4** | Parses fetched HTML, strips navigation/scripts, extracts `<article>` / `<main>` content |
| **Celery** | Distributed task queue — runs PDF and URL ingestion jobs in the background |
| **Redis** | Celery message broker and result backend. Only required when running ingestion workers. |

### Frontend

| Library | How it's loaded | Role |
|---|---|---|
| **Tailwind CSS** | CDN | Utility-first styling |
| **Alpine.js** | CDN | Lightweight reactivity — citation card state, panel toggles |
| **HTMX** | CDN | Partial page updates without a full JS framework |
| **marked.js** | CDN | Renders LLM markdown responses (bold, lists, code blocks) in the chat panel |

---

## Architecture

```
Browser
  └── Django (SSE streaming views)
        ├── Chat app      → stream_agent_response() → LangChain Agent → OpenAI GPT-4o
        ├── RAG app       → Chroma retriever (jurisdiction filter)
        │                 → SQLChatMessageHistory (SQLite memory)
        │                 → Tools: save_goal · update_goal · simulate_returns
        ├── Ingestion app → Celery workers → Chroma vector store
        └── Goals app     → InvestmentGoal model (written to by agent tools)
```

### RAG app modules

| File | Role |
|---|---|
| `retriever.py` | Chroma vector store — jurisdiction-filtered similarity search |
| `chain.py` | Shared utilities: `_format_docs`, `_docs_to_citation_dicts`, `build_rag_chain` |
| `agent.py` | Agent definition (`create_investiq_agent`) and streaming entry point (`stream_agent_response`) — owns SQLite memory wiring |
| `tools.py` | LangChain `@tool` definitions for goal management and portfolio simulation |
| `prompts.py` | All prompt strings: `SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`, `AGENT_SYSTEM_PROMPT`, `GOAL_EXTRACTION_PROMPT`, `QUERY_REFORM_PROMPT` |
| `query_builder.py` | Multi-query reformulation — expands one query into 3 retrieval variants |

### Request flow

```
User message
  → query reformulation (3 variants via LLM)             [query_builder.py]
  → Chroma similarity search, jurisdiction-filtered       [retriever.py]
  → SSE: citations emitted to left panel immediately
  → question + retrieved context formatted into {input}   [chain.py utilities]
  → LangChain tool-calling agent invoked                  [agent.py]
      ├── answers using context (no tool call needed)
      ├── OR calls save_investment_goal / update_investment_goal
      └── OR calls simulate_portfolio_returns
  → final answer emitted word-by-word as SSE token events
  → turn saved to SQLite memory (data/memory.sqlite3)     [agent.py]
```

### Storage layers

| Layer | Technology | What lives there |
|---|---|---|
| Vector store | Chroma (`data/chroma/`) | Document embeddings, searched by the RAG pipeline |
| Conversation memory | SQLite (`data/memory.sqlite3`) | LangChain `SQLChatMessageHistory`, managed by `agent.py` |
| App data | SQLite (`db.sqlite3`) | Users, Conversations, Messages, Citations, InvestmentGoals |

> Retrieval is part of the pipeline and always runs — it is **not** a LangChain tool. Tools are reserved for goal management side-effects the LLM can optionally trigger mid-conversation.

---

## Project Structure

```
investiq/
├── config/                   # Django settings (base / dev / prod), urls, asgi
├── apps/
│   ├── core/                 # Custom User model, UserProfile
│   ├── chat/                 # Conversation, Message, Citation models; SSE views
│   ├── rag/
│   │   ├── agent.py          # LangChain agent definition + stream_agent_response()
│   │   ├── tools.py          # @tool definitions: save/update goal, simulate returns
│   │   ├── chain.py          # Shared utilities: _format_docs, build_rag_chain
│   │   ├── prompts.py        # All prompts (SYSTEM, USER, AGENT, GOAL_EXTRACTION, QUERY_REFORM)
│   │   ├── retriever.py      # Chroma vector store, jurisdiction-filtered retriever
│   │   └── query_builder.py  # Multi-query reformulation
│   ├── ingestion/            # PDF + web loaders, chunker, Celery tasks
│   ├── goals/                # InvestmentGoal model, LLM extractor, views
│   └── sources/              # SourceDocument tracker, admin corpus browser
├── templates/                # base.html + split-panel chat UI
├── static/                   # CSS entry point
├── data/
│   ├── chroma/               # Chroma vector index (auto-created on first ingest)
│   ├── memory.sqlite3        # LangChain conversation memory (auto-created)
│   ├── pdfs/                 # Drop PDFs here before running ingest tasks
│   └── countries/config.yaml # Multi-country source registry (DE/EU/UK/US)
├── celery_app.py
└── manage.py
```

---

## Getting Started

### 1. Install dependencies

```bash
cd investiq
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set DJANGO_SECRET_KEY and OPENAI_API_KEY
```

### 3. Run migrations and create a superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 4. Start the dev server

```bash
python manage.py runserver
```

Open `http://localhost:8000` and log in.

### 5. Ingest documents (optional — required for RAG to return results)

```bash
# In a second terminal (requires Redis running for Celery)
celery -A celery_app worker --loglevel=info

# Trigger ingestion from the Django shell
python manage.py shell_plus
>>> from apps.ingestion.tasks import ingest_pdf_task
>>> ingest_pdf_task.delay("data/pdfs/markowitz1952.pdf", {
...     "title": "Portfolio Selection",
...     "author": "Markowitz",
...     "year": 1952,
...     "source_type": "academic",
...     "jurisdiction": "GLOBAL",
...     "language": "en",
...     "tags": ["portfolio theory", "MPT"],
... })
```

---

## Key Design Rules

1. **All prompts** live in `apps/rag/prompts.py` only — never inline elsewhere
2. **All LLM calls** flow through `apps/rag/agent.py` (`stream_agent_response`) or `apps/rag/chain.py` (`build_rag_chain` for testing)
3. **Retrieval is pipeline, not a tool** — Chroma is always queried before the agent runs; tools are for goal management side-effects only
4. **Every chunk** carries the full metadata schema at ingest time (`source_type`, `author`, `title`, `year`, `jurisdiction`, `url`, `page`, `last_ingested`, `language`, `tags`)
5. **Jurisdiction filter** is always applied on retrieval — never retrieve without one
<!-- TODO: improve UX of it -->
6. **§63 WpHG disclaimer** is appended to every investment strategy response (enforced in `AGENT_SYSTEM_PROMPT` and `simulate_portfolio_returns` tool docstring)
7. **Chat responses** use SSE streaming; all other endpoints are synchronous
8. **Response language** auto-detected from user message (DE or EN)
9. **User context in tools** is captured via closures at agent-build time — the LLM never receives or passes `user_id`
