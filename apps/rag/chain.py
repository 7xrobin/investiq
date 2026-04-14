"""
RAG chain construction and streaming response generator.

All LLM calls in the application flow through this module.
Chat history is persisted via LangChain's SQLChatMessageHistory (separate
SQLite file from the Django app DB — see MEMORY_DB_PATH in settings).
"""
from __future__ import annotations

import logging
from typing import Generator

from django.conf import settings
from langchain_community.chat_message_histories import SQLChatMessageHistory
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_openai import ChatOpenAI

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .query_builder import reform_query
from .retriever import get_retriever

logger = logging.getLogger(__name__)

# Number of past message pairs (user + assistant) to include as memory context.
HISTORY_WINDOW = 5


def _get_chat_history(conversation_id: int) -> SQLChatMessageHistory:
    """
    Return a SQLChatMessageHistory for the given conversation.

    Stored in MEMORY_DB_PATH (data/memory.sqlite3), separate from the Django DB.
    Each conversation is keyed by its integer PK.
    """
    db_path = settings.MEMORY_DB_PATH
    return SQLChatMessageHistory(
        session_id=str(conversation_id),
        connection_string=f"sqlite:///{db_path}",
    )


def _format_docs(docs: list[Document]) -> str:
    """Concatenate retrieved documents into a structured context block."""
    parts = []
    for i, doc in enumerate(docs, start=1):
        meta = doc.metadata
        header_parts = [f"[Doc {i}] {meta.get('title', 'Unknown Title')}"]
        for key, label in [
            ("author", "Author"),
            ("year", "Year"),
            ("jurisdiction", "Jurisdiction"),
            ("source_type", "Type"),
            ("page", "Page"),
            ("url", "URL"),
        ]:
            if value := meta.get(key):
                header_parts.append(f"{label}: {value}")
        parts.append(" | ".join(header_parts) + f"\n\n{doc.page_content}")
    return "\n\n---\n\n".join(parts) if parts else "No relevant documents found."


def _docs_to_citation_dicts(docs: list[Document]) -> list[dict]:
    """Convert retrieved Documents to citation dict format for the SSE payload."""
    return [
        {
            "source_title": doc.metadata.get("title", "Unknown"),
            "source_author": doc.metadata.get("author", ""),
            "source_year": doc.metadata.get("year"),
            "source_url": doc.metadata.get("url", ""),
            "source_type": doc.metadata.get("source_type", "regulatory"),
            "page_number": doc.metadata.get("page"),
            "jurisdiction": doc.metadata.get("jurisdiction", "DE"),
            "relevance_score": doc.metadata.get("relevance_score"),
            "chunk_text": doc.page_content,
        }
        for doc in docs
    ]


def build_rag_chain(jurisdiction: str = "DE") -> Runnable:
    """
    Build and return a stateless LangChain RAG chain (no memory).

    TODO: For streaming with memory use
    stream_rag_response() instead.
    """
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.2,
        streaming=True,
        openai_api_key=settings.OPENAI_API_KEY,
    )
    retriever = get_retriever(jurisdiction=jurisdiction)
    chain = (
        RunnablePassthrough.assign(
            context=lambda x: _format_docs(retriever.invoke(x["user_message"]))
        )
        | USER_PROMPT_TEMPLATE
        | llm.bind(system=SYSTEM_PROMPT)
        | StrOutputParser()
    )
    return chain


def stream_rag_response(
    user_message: str,
    conversation_id: int,
    jurisdiction: str = "DE",
    goal_context: str = "",
) -> Generator[dict, None, None]:
    """
    Stream a RAG response, injecting conversation history from SQLite.

    Yields dicts:
      {"type": "citations", "citations": [...]}   — before first token
      {"type": "token",     "content": "..."}     — one per LLM token
      {"type": "done"}                             — final event
      {"type": "error",     "message": "..."}      — on failure
    """
    logger.info(
        "Streaming RAG response: conversation=%d jurisdiction=%s",
        conversation_id,
        jurisdiction,
    )

    # ── 1. Multi-query reformulation ─────────────────────────────────────────
    try:
        reformulated_queries = reform_query(user_message, jurisdiction=jurisdiction)
    except Exception:
        reformulated_queries = [user_message]
        logger.warning("Query reform failed, using original query.")

    # ── 2. Retrieval (deduplicated across reformulated queries) ───────────────
    retriever = get_retriever(jurisdiction=jurisdiction)
    seen: set[str] = set()
    all_docs: list[Document] = []

    for q in reformulated_queries:
        try:
            for doc in retriever.invoke(q):
                key = doc.page_content[:200]
                if key not in seen:
                    seen.add(key)
                    all_docs.append(doc)
        except Exception as exc:
            logger.warning("Retrieval failed for query %r: %s", q, exc)

    # ── 3. Emit citations so the left panel can populate immediately ──────────
    citation_dicts = _docs_to_citation_dicts(all_docs)
    yield {"type": "citations", "citations": citation_dicts}

    # ── 4. Load conversation history from SQLite ──────────────────────────────
    history = _get_chat_history(conversation_id)
    # Trim to the last HISTORY_WINDOW pairs (2 * N messages)
    past_messages = history.messages[-(HISTORY_WINDOW * 2):]

    # ── 5. Build message list: system → history → current user message ────────
    context = _format_docs(all_docs)
    prompt_text = USER_PROMPT_TEMPLATE.format(
        user_message=user_message,
        context=context,
        jurisdiction=jurisdiction,
        goal_context=goal_context or "No investment goals set.",
    )

    messages = [SystemMessage(content=SYSTEM_PROMPT)]
    messages.extend(past_messages)
    messages.append(HumanMessage(content=prompt_text))

    # ── 6. Stream LLM response ────────────────────────────────────────────────
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.2,
        streaming=True,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    full_response = ""
    try:
        for chunk in llm.stream(messages):
            token = chunk.content
            if token:
                full_response += token
                yield {"type": "token", "content": token}
    except Exception as exc:
        logger.exception("LLM streaming error for conversation=%d: %s", conversation_id, exc)
        yield {"type": "error", "message": f"LLM error: {exc}"}
        return

    # ── 7. Persist turn to memory ─────────────────────────────────────────────
    try:
        history.add_user_message(user_message)
        history.add_ai_message(full_response)
    except Exception as exc:
        # Non-fatal — the response was already streamed successfully.
        logger.warning("Failed to persist chat history for conversation=%d: %s", conversation_id, exc)

    yield {"type": "done"}
