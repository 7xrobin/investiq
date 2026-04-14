"""
Chroma vector store retriever with jurisdiction metadata filtering.

Chroma persists its index to CHROMA_PERSIST_DIR (a local directory).
No external database connection is required.
"""
from __future__ import annotations

import logging

from django.conf import settings
from langchain_chroma import Chroma
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
