"""
Embedding pipeline functions for adding documents to the Chroma vector store.

These are plain synchronous functions. Callers that need non-blocking behaviour
should wrap them in a threading.Thread (daemon=True).

  embed_pdf(pdf_path, metadata)  → load → auto-extract metadata → chunk → store
  embed_url(url, metadata)       → fetch → auto-extract metadata → chunk → store
  refresh_corpus_pipeline()      → iterate country registry → call embed_url per source
"""
from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def _build_source_id(metadata: dict, fallback_source: str) -> str:
    """Build a readable source identifier used for replace-on-reembed."""
    url = (metadata.get("url") or "").strip()
    if url:
        return url
    title = (metadata.get("title") or "untitled").strip()
    source_name = Path(fallback_source).name
    return f"{title}::{source_name}"


def _embed_and_store(chunks, source_id: str) -> int:
    """Embed chunks and replace any existing chunks for the same source."""
    from langchain_chroma import Chroma
    from langchain_openai import OpenAIEmbeddings

    if not chunks:
        return 0

    # TODO: check the embed dimension
    embeddings = OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    store = Chroma(
        collection_name=settings.CHROMA_COLLECTION,
        embedding_function=embeddings,
        persist_directory=str(settings.CHROMA_PERSIST_DIR),
    )
    # Delete old chunks for the same source
    try:
        store.delete(where={"source_id": source_id})
    except Exception as exc:
        logger.warning("Failed to delete old chunks for source_id=%s: %s", source_id, exc)

    ids = store.add_documents(chunks)
    logger.info(
        "Stored %d chunks in Chroma collection '%s' (source_id=%s)",
        len(ids),
        settings.CHROMA_COLLECTION,
        source_id,
    )
    return len(ids)


def _update_source_record(metadata: dict, chunk_count: int) -> None:
    """Create or update a SourceDocument record to track ingestion.

    tags is kept as a list here — SourceDocument.tags is a JSONField.
    The comma-string conversion for Chroma happens in chunker.py.
    """
    from apps.sources.models import SourceDocument

    # Tags arrive as either a list (from extractor) or comma-string (from Chroma
    # round-trip). Normalise to list for Django storage.
    tags_raw = metadata.get("tags", [])
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    else:
        tags = list(tags_raw)

    SourceDocument.objects.update_or_create(
        url=metadata.get("url", ""),
        title=metadata.get("title", "Untitled"),
        defaults={
            "source_type": metadata.get("source_type", "other"),
            "author": metadata.get("author", ""),
            "year": metadata.get("year") or None,
            "jurisdiction": metadata.get("jurisdiction", "DE"),
            "language": metadata.get("language", "en"),
            "tags": tags,
            "last_ingested": datetime.now(tz=timezone.utc),
            "chunk_count": chunk_count,
            "is_active": True,
        },
    )


def _enrich_metadata(text: str, user_metadata: dict) -> dict:
    """
    Run LLM-based metadata extraction and merge with user-provided values.

    User-provided non-empty values always take precedence over LLM output.
    Returns a merged metadata dict ready for chunk_document().
    """
    from apps.embed.metadata import extract_document_metadata

    extracted = extract_document_metadata(
        text=text,
        url=user_metadata.get("url", ""),
        user_hints=user_metadata,
    )
    # Start from LLM result, then override with any non-empty user-provided field.
    merged = {**extracted}
    for key, value in user_metadata.items():
        if value is not None and value != "" and value != [] and value != 0:
            merged[key] = value
    return merged


def embed_pdf(pdf_path: str, metadata: dict) -> dict:
    """
    Load a PDF, auto-extract missing metadata, chunk, embed, and store in Chroma.

    Returns stats dict: {"status": "ok", "chunks": N, "source": pdf_path}
    """
    from apps.embed.chunker import chunk_document
    from apps.embed.loaders import load_pdf

    logger.info("embed_pdf: %s", pdf_path)

    text = load_pdf(pdf_path)
    enriched = _enrich_metadata(text, metadata)
    source_id = _build_source_id(enriched, pdf_path)
    enriched["source_id"] = source_id

    chunks = chunk_document(
        text=text,
        metadata=enriched,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )
    stored = _embed_and_store(chunks, source_id=source_id)
    _update_source_record(enriched, stored)

    result = {"status": "ok", "chunks": stored, "source": pdf_path}
    logger.info("embed_pdf complete: %s", result)
    return result


def embed_url(url: str, metadata: dict) -> dict:
    """
    Fetch a URL, auto-extract missing metadata, chunk, embed, and store in Chroma.

    Returns stats dict: {"status": "ok", "chunks": N, "source": url}
    """
    from apps.embed.chunker import chunk_document
    from apps.embed.loaders import load_url

    logger.info("embed_url: %s", url)

    base_metadata = {**metadata, "url": url}
    text = load_url(url)
    enriched = _enrich_metadata(text, base_metadata)
    source_id = _build_source_id(enriched, url)
    enriched["source_id"] = source_id

    chunks = chunk_document(
        text=text,
        metadata=enriched,
        chunk_size=settings.CHUNK_SIZE,
        overlap=settings.CHUNK_OVERLAP,
    )
    stored = _embed_and_store(chunks, source_id=source_id)
    _update_source_record(enriched, stored)

    result = {"status": "ok", "chunks": stored, "source": url}
    logger.info("embed_url complete: %s", result)
    return result


def refresh_corpus_pipeline() -> dict:
    """
    Re-embed all URL-based sources from the country registry.

    PDF sources must be submitted manually via embed_pdf.
    Registry sources already have metadata populated from the YAML file,
    so LLM extraction is still run but user_hints will override most fields.
    """
    from apps.embed.country_registry import get_all_sources

    logger.info("refresh_corpus_pipeline: starting full corpus refresh")

    sources = get_all_sources()
    completed = 0
    skipped = 0

    for source in sources:
        url: str = source.get("url", "").strip()
        if not url or not url.startswith("http"):
            logger.debug("Skipping non-URL source: %r", source.get("name"))
            skipped += 1
            continue

        metadata: dict[str, Any] = {
            "title": source.get("name", source.get("title", "")),
            "source_type": source.get("type", source.get("source_type", "regulatory")),
            "author": source.get("author", ""),
            "year": source.get("year", 0),
            "jurisdiction": source.get("jurisdiction", "DE"),
            "language": source.get("language", "en"),
            "tags": source.get("tags", []),
            "url": url,
        }

        embed_url(url=url, metadata=metadata)
        completed += 1

    result = {
        "status": "ok",
        "completed": completed,
        "skipped": skipped,
        "total_sources": len(sources),
    }
    logger.info("refresh_corpus_pipeline: %s", result)
    return result
