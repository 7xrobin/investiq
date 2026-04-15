"""
Metadata extraction for embedded documents.

Two responsibilities:
  - extract_document_metadata(): LLM-based extraction of document-level fields
    (title, author, year, source_type, language, tags) from document text.
    Called once per document; cheap vs. per-chunk LLM calls.
  - extract_section_title(): Heuristic extraction of the section heading that
    a chunk belongs to. No LLM cost — runs per chunk.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Document-level metadata (LLM, one call per document)
# ---------------------------------------------------------------------------

# Characters from the document sent to the LLM — enough to see title, author,
# abstract, and opening sections without being too expensive.
_EXCERPT_CHARS = 4000


def extract_document_metadata(
    text: str,
    url: str = "",
    user_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Extract document-level metadata using an LLM.

    Sends the first _EXCERPT_CHARS characters to the LLM with
    DOCUMENT_METADATA_PROMPT and returns a dict with:
        title, author, year, source_type, language, tags (list)

    user_hints values take precedence over LLM output — any field already
    provided by the caller (non-empty/non-None) is kept as-is. This lets
    the user override individual fields while the LLM fills the rest.

    Falls back gracefully to an empty dict on any error so the pipeline
    continues with defaults.
    """
    from django.conf import settings
    from langchain_openai import ChatOpenAI

    from apps.rag.prompts import DOCUMENT_METADATA_PROMPT

    empty: dict[str, Any] = {}

    if not text or not text.strip():
        return empty

    excerpt = text.strip()[:_EXCERPT_CHARS]

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.0,
        openai_api_key=settings.OPENAI_API_KEY,
    )
    chain = DOCUMENT_METADATA_PROMPT | llm

    try:
        response = chain.invoke({"text_excerpt": excerpt, "url": url or ""})
        raw = response.content.strip()

        # Strip markdown code fences if model wrapped output.
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()

        extracted: dict[str, Any] = json.loads(raw)

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Document metadata JSON parse error: %s", exc)
        return empty
    except Exception as exc:
        logger.error("Document metadata LLM error: %s", exc, exc_info=True)
        return empty

    # Sanitise and type-coerce extracted values.
    result: dict[str, Any] = {}

    title = extracted.get("title")
    result["title"] = str(title).strip() if title else ""

    author = extracted.get("author")
    result["author"] = str(author).strip() if author else ""

    year = extracted.get("year")
    try:
        result["year"] = int(year) if year is not None else None
    except (ValueError, TypeError):
        result["year"] = None

    source_type = extracted.get("source_type", "other")
    result["source_type"] = (
        source_type
        if source_type in ("regulatory", "academic", "news", "other")
        else "other"
    )

    language = extracted.get("language", "en")
    result["language"] = language if language in ("en", "de") else "en"

    tags = extracted.get("tags", [])
    result["tags"] = [str(t).strip().lower() for t in tags if t] if isinstance(tags, list) else []

    # Apply user hints: any non-empty caller-provided value overrides LLM output.
    if user_hints:
        for key, value in user_hints.items():
            if value is not None and value != "" and value != [] and value != 0:
                result[key] = value

    logger.debug("Extracted document metadata: %r", result)
    return result


# ---------------------------------------------------------------------------
# Chunk-level section title (heuristic, no LLM)
# ---------------------------------------------------------------------------

# Patterns that suggest a line is a section heading.
_HEADING_PATTERNS = [
    re.compile(r"^#{1,4}\s+\S"),          # Markdown headings: # Title
    re.compile(r"^[A-Z][A-Z\s\d\-:]{4,}$"),  # ALL-CAPS lines (min 5 chars)
    re.compile(r"^\d+(\.\d+)*\s+[A-Z]"),  # Numbered sections: 1.2 Title
    re.compile(r"^[A-Z][^\.\n]{5,79}$"),  # Title-cased short line (no trailing dot)
]

_MAX_HEADING_LEN = 120


def extract_section_title(chunk_text: str) -> str:
    """
    Heuristically identify the section heading a chunk belongs to.

    Looks at the first few non-empty lines of the chunk. Returns the first
    line that matches a heading pattern, stripped of leading `#` characters.
    Returns an empty string if no heading is detected.
    """
    if not chunk_text:
        return ""

    lines = chunk_text.splitlines()
    candidates = [l.strip() for l in lines[:5] if l.strip()]

    for line in candidates:
        if len(line) > _MAX_HEADING_LEN:
            continue
        # Skip lines that look like body text (end with sentence punctuation).
        if line.endswith((".", ",", ";", ":", "?", "!")):
            continue
        for pattern in _HEADING_PATTERNS:
            if pattern.match(line):
                # Strip leading markdown `#` markers.
                return re.sub(r"^#+\s*", "", line).strip()

    return ""
