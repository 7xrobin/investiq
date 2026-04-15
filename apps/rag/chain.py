"""
Shared RAG utilities: document formatting and the stateless build_rag_chain().
"""
from __future__ import annotations

import logging

from django.conf import settings
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnablePassthrough
from langchain_openai import ChatOpenAI

from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from .retriever import get_retriever

logger = logging.getLogger(__name__)


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
    """Stateless RAG chain — useful for testing retrieval in isolation."""
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
