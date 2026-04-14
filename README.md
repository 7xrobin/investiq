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
| **LangChain** | 0.3 | Core RAG abstractions — chains, runnables, retrievers, prompt templates |
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
        ├── Chat app      → stream_rag_response() → OpenAI GPT-4o
        ├── RAG app       → Chroma retriever (jurisdiction filter)
        │                 → SQLChatMessageHistory (SQLite memory)
        ├── Ingestion app → Celery workers → Chroma vector store
        └── Goals app     → LLM goal extractor → InvestmentGoal model
```

### Request flow

```
User message
  → query reformulation (3 variants via LLM)
  → Chroma similarity search (filtered by jurisdiction)
  → inject last 5 conversation turns from memory
  → LLM synthesis (GPT-4o, streamed)
  → SSE token stream to browser
  → left panel citation cards populated
  → conversation turn saved to SQLite memory
```

---

## Project Structure

```
investiq/
├── config/                   # Django settings (base / dev / prod), urls, asgi
├── apps/
│   ├── core/                 # Custom User model, UserProfile
│   ├── chat/                 # Conversation, Message, Citation models; SSE views
│   ├── rag/                  # chain.py, prompts.py, retriever.py, query_builder.py
│   ├── ingestion/            # PDF + web loaders, chunker, Celery tasks
│   ├── goals/                # InvestmentGoal model, LLM goal extractor
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

## Environment Variables

Only secrets for external services go in `.env`. Everything else is hardcoded with sensible defaults.

| Variable | Required | Description |
|---|---|---|
| `DJANGO_SECRET_KEY` | Yes | Django cryptographic signing key |
| `OPENAI_API_KEY` | Yes | OpenAI API key (used for GPT-4o and text-embedding-3-small) |
| `LANGCHAIN_API_KEY` | No | LangSmith API key — enables chain tracing at smith.langchain.com |

---

## Key Design Rules

1. **All prompts** live in `apps/rag/prompts.py` only — never inline elsewhere
2. **All LLM calls** flow through `apps/rag/chain.py` only
3. **Every chunk** carries the full metadata schema at ingest time (`source_type`, `author`, `title`, `year`, `jurisdiction`, `url`, `page`, `last_ingested`, `language`, `tags`)
4. **Jurisdiction filter** is always applied on retrieval — never retrieve without one
5. **§63 WpHG disclaimer** is appended to every investment strategy response
6. **Chat responses** use SSE streaming; all other endpoints are synchronous
7. **Response language** auto-detected from user message (DE or EN)
