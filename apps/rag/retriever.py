"""
Chroma vector store retriever with jurisdiction metadata filtering.

Chroma persists its index to CHROMA_PERSIST_DIR (a local directory).
No external database connection is required.
"""
from __future__ import annotations

import logging

from django.conf import settings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_openai import OpenAIEmbeddings

logger = logging.getLogger(__name__)


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )


def get_vector_store() -> Chroma:
    """Return the shared Chroma vector store instance."""
    return Chroma(
        collection_name=settings.CHROMA_COLLECTION,
        embedding_function=_get_embeddings(),
        persist_directory=str(settings.CHROMA_PERSIST_DIR),
    )


def get_retriever(jurisdiction: str = "DE", k: int | None = None) -> VectorStoreRetriever:
    """
    Return a retriever pre-filtered to a specific jurisdiction.

    Chroma's where filter uses the standard metadata dict syntax.
    """
    if k is None:
        k = getattr(settings, "MAX_RETRIEVAL_DOCS", 6)

    store = get_vector_store()
    retriever = store.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": k,
            "filter": {"jurisdiction": jurisdiction},
        },
    )
    logger.debug("Built Chroma retriever for jurisdiction=%s k=%d", jurisdiction, k)
    return retriever


def get_multi_jurisdiction_retriever(
    jurisdictions: list[str],
    k_per_jurisdiction: int = 3,
) -> VectorStoreRetriever:
    """Retrieve documents spanning multiple jurisdictions."""
    store = get_vector_store()
    retriever = store.as_retriever(
        search_type="similarity",
        search_kwargs={
            "k": k_per_jurisdiction * len(jurisdictions),
            "filter": {"jurisdiction": {"$in": jurisdictions}},
        },
    )
    return retriever


def retrieve_context_docs(user_message: str, jurisdiction: str = "DE") -> list[Document]:
    """
    Retrieve documents for RAG context.

    This keeps retrieval concerns out of agent orchestration. We intentionally
    avoid additional balancing/deduping here and rely on clean ingestion data.
    """
    from .query_builder import reform_query

    try:
        queries = reform_query(user_message, jurisdiction=jurisdiction)
    except Exception:
        queries = [user_message]
        logger.warning("Query reformulation failed, using original query.")

    # We need similarity scores for the UI "Sources & References" panel.
    # VectorStoreRetriever.invoke() returns Documents only, so we call the
    # vector store directly to get (Document, score) pairs.
    store = get_vector_store()
    # Fetch more than we need, because we will filter out low-similarity chunks.
    k = getattr(settings, "MAX_RETRIEVAL_DOCS", 6) * 3
    min_relevance_score = getattr(settings, "MIN_RELEVANCE_SCORE", 0.2)
    docs: list[Document] = []
    seen_keys: set[tuple[str, str]] = set()

    for query in queries:
        try:
            docs_with_scores = store.similarity_search_with_relevance_scores(
                query,
                k=k,
                filter={"jurisdiction": jurisdiction},
            )
            for doc, score in docs_with_scores:
                if score is not None and score < min_relevance_score:
                    continue

                # Copy metadata so we don't mutate shared doc instances.
                md = dict(doc.metadata or {})
                md["relevance_score"] = score
                # Best-effort de-dupe for multi-query retrieval.
                # If stable IDs are missing, avoid over-filtering.
                source_id = str(md.get("source_id", "") or "")
                chunk_id = str(md.get("chunk_id", "") or "")
                if source_id or chunk_id:
                    key = (source_id, chunk_id)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)

                docs.append(Document(page_content=doc.page_content, metadata=md))
        except Exception as exc:
            logger.warning("Retrieval failed for query %r: %s", query, exc)

    return docs
