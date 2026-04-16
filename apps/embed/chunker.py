"""
Document chunking with metadata schema enforcement.

Produces LangChain Document objects ready for embedding and storage in Chroma.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadata schema definition
# ---------------------------------------------------------------------------

METADATA_SCHEMA: dict[str, type] = {
    "source_type": str,    # 'regulatory' | 'academic' | 'news' | 'other'
    "author": str,         # Author name or issuing body
    "title": str,          # Document title
    "year": int,           # Publication year (0 if unknown)
    "jurisdiction": str,   # 'DE' | 'EU' | 'UK' | 'US' | 'GLOBAL'
    "url": str,            # Source URL (empty string if not applicable)
    "page": int,           # Page number within original document (0 if N/A)
    "last_ingested": str,  # ISO 8601 datetime string of ingestion time
    "language": str,       # 'en' | 'de'
    "tags": str,           # Comma-separated keywords (string for Chroma compatibility)
    "section_title": str,  # Section heading this chunk belongs to
    "source_id": str,      # Stable source identity for idempotent storage/retrieval
    "chunk_id": str,       # Stable chunk identity within the source
}

VALID_SOURCE_TYPES = {"regulatory", "academic", "news", "other"}
VALID_JURISDICTIONS = {"DE", "EU", "UK", "US", "GLOBAL"}
VALID_LANGUAGES = {"en", "de"}


def _validate_and_fill_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Validate and fill metadata, returning a dict safe for Chroma storage.

    - Fills missing fields with safe defaults
    - Coerces types
    - Converts tags list → comma-separated string (Chroma requires scalar values)
    """
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    defaults: dict[str, Any] = {
        "source_type": "other",
        "author": "",
        "title": "Untitled",
        "year": 0,
        "jurisdiction": "DE",
        "url": "",
        "page": 0,
        "last_ingested": now_iso,
        "language": "en",
        "tags": "",
        "section_title": "",
        "source_id": "",
        "chunk_id": "",
    }

    filled = {**defaults, **metadata}

    # Coerce numeric fields.
    for int_field in ("year", "page"):
        if not isinstance(filled[int_field], int):
            try:
                filled[int_field] = int(filled[int_field]) if filled[int_field] else 0
            except (ValueError, TypeError):
                filled[int_field] = 0

    # Normalise string fields.
    for str_field in ("source_type", "author", "title", "jurisdiction", "url",
                      "language", "last_ingested", "section_title", "source_id", "chunk_id"):
        filled[str_field] = str(filled[str_field]).strip()

    # Convert tags to a comma-separated string — Chroma cannot store empty lists.
    tags_raw = filled.get("tags", "")
    if isinstance(tags_raw, list):
        filled["tags"] = ", ".join(str(t) for t in tags_raw if t)
    elif isinstance(tags_raw, str):
        filled["tags"] = tags_raw.strip()
    else:
        filled["tags"] = ""

    # Validate controlled-vocabulary fields.
    if filled["source_type"] not in VALID_SOURCE_TYPES:
        logger.warning("Invalid source_type %r — defaulting to 'other'.", filled["source_type"])
        filled["source_type"] = "other"

    if filled["jurisdiction"] not in VALID_JURISDICTIONS:
        logger.warning("Invalid jurisdiction %r — defaulting to 'DE'.", filled["jurisdiction"])
        filled["jurisdiction"] = "DE"

    if filled["language"] not in VALID_LANGUAGES:
        logger.warning("Invalid language %r — defaulting to 'en'.", filled["language"])
        filled["language"] = "en"

    # Always stamp ingestion time.
    filled["last_ingested"] = now_iso

    return filled


def chunk_document(
    text: str,
    metadata: dict[str, Any],
    chunk_size: int = 1000,
    overlap: int = 200,
) -> list[Document]:
    """
    Split a document's text into overlapping chunks and attach full metadata to each.

    Tags are converted to a comma-separated string before storage (Chroma scalar
    requirement). Section titles are extracted heuristically from each chunk's text.

    Args:
        text: Raw extracted text of the document.
        metadata: Document-level metadata. Must include at minimum title and
                  jurisdiction; all other keys default to safe values.
        chunk_size: Target character size per chunk (default 1000).
        overlap: Character overlap between consecutive chunks (default 200).

    Returns:
        List of LangChain Document objects with full metadata. Empty list if
        input text is blank after stripping.
    """
    from apps.embed.metadata import extract_section_title

    text = text.strip()
    if not text:
        logger.warning("chunk_document called with empty text for title=%r", metadata.get("title"))
        return []

    validated_meta = _validate_and_fill_metadata(metadata)

    # TODO: improve the chunking logic
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=[
            "\n\n\n",
            "\n\n",
            "\n",
            ". ",
            ", ",
            " ",
            "",
        ],
        length_function=len,
        is_separator_regex=False,
        add_start_index=True,
    )

    raw_chunks = splitter.split_text(text)
    documents: list[Document] = []

    for chunk_idx, chunk_text in enumerate(raw_chunks):
        chunk_meta = dict(validated_meta)
        chunk_meta["chunk_index"] = chunk_idx
        chunk_meta["chunk_count_in_doc"] = len(raw_chunks)
        chunk_meta["section_title"] = extract_section_title(chunk_text)
        chunk_meta["chunk_id"] = str(chunk_idx)
        documents.append(Document(page_content=chunk_text, metadata=chunk_meta))

    logger.info(
        "Chunked %r into %d chunks (size=%d, overlap=%d)",
        validated_meta.get("title"),
        len(documents),
        chunk_size,
        overlap,
    )
    return documents
