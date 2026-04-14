"""
Celery tasks for document ingestion into the Chroma vector store.

Task flow:
  ingest_pdf_task  → load_pdf → chunk_document → embed → store in Chroma
  ingest_url_task  → load_url → chunk_document → embed → store in Chroma
  refresh_corpus_task → iterate country registry → dispatch per-source tasks
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


def _embed_and_store(chunks) -> int:
    """
    Embed a list of LangChain Documents and add them to the Chroma store.

    Returns the number of documents stored.
    """
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings

    if not chunks:
        return 0

    embeddings = OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    store = Chroma(
        collection_name=settings.CHROMA_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(settings.CHROMA_PERSIST_DIR),
    )

    ids = store.add_documents(chunks)
    logger.info("Stored %d chunks in Chroma collection '%s'", len(ids), settings.CHROMA_COLLECTION)
    return len(ids)


def _update_source_record(metadata: dict, chunk_count: int) -> None:
    """Create or update a SourceDocument record to track ingestion."""
    from apps.sources.models import SourceDocument

    SourceDocument.objects.update_or_create(
        url=metadata.get("url", ""),
        title=metadata.get("title", "Untitled"),
        defaults={
            "source_type": metadata.get("source_type", "other"),
            "author": metadata.get("author", ""),
            "year": metadata.get("year") or None,
            "jurisdiction": metadata.get("jurisdiction", "DE"),
            "language": metadata.get("language", "en"),
            "tags": metadata.get("tags", []),
            "last_ingested": datetime.now(tz=timezone.utc),
            "chunk_count": chunk_count,
            "is_active": True,
        },
    )


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="apps.ingestion.tasks.ingest_pdf_task",
)
def ingest_pdf_task(self, pdf_path: str, metadata: dict) -> dict:
    """
    Celery task: load a PDF file, chunk it, embed, and store in pgvector.

    Args:
        pdf_path: Absolute path to the PDF file on the worker's filesystem.
        metadata: Document-level metadata dict (must include title, source_type,
                  jurisdiction at minimum).

    Returns:
        Stats dict: {"status": "ok", "chunks": N, "path": pdf_path}
    """
    from apps.ingestion.chunker import chunk_document
    from apps.ingestion.loaders import load_pdf

    logger.info("ingest_pdf_task: %s", pdf_path)

    try:
        text = load_pdf(pdf_path)
    except Exception as exc:
        logger.error("Failed to load PDF %s: %s", pdf_path, exc)
        raise self.retry(exc=exc)

    chunks = chunk_document(
        text=text,
        metadata=metadata,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )

    try:
        stored = _embed_and_store(chunks)
    except Exception as exc:
        logger.error("Failed to embed/store PDF %s: %s", pdf_path, exc)
        raise self.retry(exc=exc)

    _update_source_record(metadata, stored)

    result = {"status": "ok", "chunks": stored, "path": pdf_path}
    logger.info("ingest_pdf_task complete: %s", result)
    return result


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    name="apps.ingestion.tasks.ingest_url_task",
)
def ingest_url_task(self, url: str, metadata: dict) -> dict:
    """
    Celery task: fetch a URL, chunk its content, embed, and store in pgvector.

    Args:
        url: HTTP/HTTPS URL to ingest.
        metadata: Document-level metadata dict. The URL field will be set
                  automatically from the url argument.

    Returns:
        Stats dict: {"status": "ok", "chunks": N, "url": url}
    """
    from apps.ingestion.chunker import chunk_document
    from apps.ingestion.loaders import load_url

    logger.info("ingest_url_task: %s", url)

    metadata = {**metadata, "url": url}

    try:
        text = load_url(url)
    except Exception as exc:
        logger.error("Failed to fetch URL %s: %s", url, exc)
        raise self.retry(exc=exc)

    chunks = chunk_document(
        text=text,
        metadata=metadata,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )

    try:
        stored = _embed_and_store(chunks)
    except Exception as exc:
        logger.error("Failed to embed/store URL %s: %s", url, exc)
        raise self.retry(exc=exc)

    _update_source_record(metadata, stored)

    result = {"status": "ok", "chunks": stored, "url": url}
    logger.info("ingest_url_task complete: %s", result)
    return result


@shared_task(
    name="apps.ingestion.tasks.refresh_corpus_task",
    time_limit=3600,
    soft_time_limit=3500,
)
def refresh_corpus_task() -> dict:
    """
    Scheduled task: re-ingest all sources from the country registry.

    Dispatches one ingest_url_task per URL-based source. PDF sources must be
    submitted manually via ingest_pdf_task (PDFs are not fetched from URLs).

    Returns:
        Summary dict: {"dispatched": N, "skipped": N, "jurisdictions": [...]}
    """
    from apps.ingestion.country_registry import get_all_sources

    logger.info("refresh_corpus_task: starting full corpus refresh")

    sources = get_all_sources()
    dispatched = 0
    skipped = 0

    for source in sources:
        url: str = source.get("url", "").strip()
        if not url or not url.startswith("http"):
            logger.debug("Skipping non-URL source: %r", source.get("name"))
            skipped += 1
            continue

        metadata: dict[str, Any] = {
            "title": source.get("name", source.get("title", "Unknown")),
            "source_type": source.get("type", source.get("source_type", "regulatory")),
            "author": source.get("author", ""),
            "year": source.get("year", 0),
            "jurisdiction": source.get("jurisdiction", "DE"),
            "language": source.get("language", "en"),
            "tags": source.get("tags", []),
            "url": url,
        }

        ingest_url_task.delay(url=url, metadata=metadata)
        dispatched += 1
        logger.debug("Dispatched ingest_url_task for %s", url)

    result = {
        "status": "ok",
        "dispatched": dispatched,
        "skipped": skipped,
        "total_sources": len(sources),
    }
    logger.info("refresh_corpus_task: %s", result)
    return result
