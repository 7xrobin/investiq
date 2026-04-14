"""
Document chunking with full metadata schema enforcement.

Produces LangChain Document objects ready for embedding and storage in pgvector.
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
    "source_type": str,   # 'regulatory' | 'academic' | 'news' | 'other'
    "author": str,        # Author name or issuing body
    "title": str,         # Document title
    "year": int,          # Publication year (0 if unknown)
    "jurisdiction": str,  # 'DE' | 'EU' | 'UK' | 'US' | 'GLOBAL'
    "url": str,           # Source URL (empty string if not applicable)
    "page": int,          # Page number within original document (0 if N/A)
    "last_ingested": str, # ISO 8601 datetime string of ingestion time
    "language": str,      # 'en' | 'de'
    "tags": list,         # List of string tags
}

VALID_SOURCE_TYPES = {"regulatory", "academic", "news", "other"}
VALID_JURISDICTIONS = {"DE", "EU", "UK", "US", "GLOBAL"}
VALID_LANGUAGES = {"en", "de"}


def _validate_and_fill_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Validate that metadata conforms to METADATA_SCHEMA.

    Fills in default values for missing fields and coerces types where safe.
    Raises ValueError for unrecoverable schema violations.
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
        "tags": [],
    }

    filled = {**defaults, **metadata}

    # Coerce types.
    if not isinstance(filled["year"], int):
        try:
            filled["year"] = int(filled["year"]) if filled["year"] else 0
        except (ValueError, TypeError):
            filled["year"] = 0

    if not isinstance(filled["page"], int):
        try:
            filled["page"] = int(filled["page"]) if filled["page"] else 0
        except (ValueError, TypeError):
            filled["page"] = 0

    if not isinstance(filled["tags"], list):
        filled["tags"] = list(filled["tags"]) if filled["tags"] else []

    # Normalise string fields.
    for str_field in ("source_type", "author", "title", "jurisdiction", "url", "language", "last_ingested"):
        filled[str_field] = str(filled[str_field]).strip()

    # Validate controlled-vocabulary fields.
    if filled["source_type"] not in VALID_SOURCE_TYPES:
        logger.warning(
            "Invalid source_type %r — defaulting to 'other'.", filled["source_type"]
        )
        filled["source_type"] = "other"

    if filled["jurisdiction"] not in VALID_JURISDICTIONS:
        logger.warning(
            "Invalid jurisdiction %r — defaulting to 'DE'.", filled["jurisdiction"]
        )
        filled["jurisdiction"] = "DE"

    if filled["language"] not in VALID_LANGUAGES:
        logger.warning(
            "Invalid language %r — defaulting to 'en'.", filled["language"]
        )
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

    Uses RecursiveCharacterTextSplitter with a hierarchy of separators tuned
    for financial and regulatory documents (section headers, paragraphs, sentences).

    Args:
        text: Raw extracted text of the document.
        metadata: Document-level metadata dict. Must include at minimum:
                  title, source_type, jurisdiction. All other keys will be
                  filled with safe defaults.
        chunk_size: Target character size for each chunk (default 1000).
        overlap: Character overlap between consecutive chunks (default 200).

    Returns:
        List of LangChain Document objects, each with full metadata attached.
        Empty list if the input text is blank after stripping.
    """
    text = text.strip()
    if not text:
        logger.warning("chunk_document called with empty text for title=%r", metadata.get("title"))
        return []

    validated_meta = _validate_and_fill_metadata(metadata)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=overlap,
        separators=[
            "\n\n\n",   # Section breaks (common in PDFs)
            "\n\n",     # Paragraphs
            "\n",       # Lines
            ". ",       # Sentences
            ", ",       # Clauses
            " ",        # Words
            "",         # Characters (last resort)
        ],
        length_function=len,
        is_separator_regex=False,
        add_start_index=True,  # Adds char_start_index to metadata for provenance.
    )

    raw_chunks = splitter.split_text(text)
    documents: list[Document] = []

    for chunk_idx, chunk_text in enumerate(raw_chunks):
        chunk_meta = dict(validated_meta)
        chunk_meta["chunk_index"] = chunk_idx
        chunk_meta["chunk_count_in_doc"] = len(raw_chunks)

        documents.append(Document(page_content=chunk_text, metadata=chunk_meta))

    logger.info(
        "Chunked document %r into %d chunks (size=%d, overlap=%d)",
        validated_meta.get("title"),
        len(documents),
        chunk_size,
        overlap,
    )
    return documents
