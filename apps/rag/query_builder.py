"""
Query reformulation using LLM multi-query expansion.

Generates 3 semantically distinct search queries from the original user query
to improve recall in the pgvector retrieval step.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from langchain_openai import ChatOpenAI

from .prompts import QUERY_REFORM_PROMPT

logger = logging.getLogger(__name__)


def reform_query(query: str, jurisdiction: str = "DE") -> list[str]:
    """
    Return 3 reformulated queries for multi-query retrieval.

    Uses QUERY_REFORM_PROMPT to instruct the LLM to generate alternative
    framings of the original query — regulatory, product-specific, and
    conceptual — each optimised for dense vector search.

    Args:
        query: The original user question.
        jurisdiction: Jurisdiction code used to tune terminology (DE/EU/UK/US).

    Returns:
        A list of 3 reformulated query strings. Falls back to [query] on error
        so the calling code always gets a usable list.
    """
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.3,
        openai_api_key=settings.OPENAI_API_KEY,
    )

    chain = QUERY_REFORM_PROMPT | llm

    try:
        response = chain.invoke({"query": query, "jurisdiction": jurisdiction})
        raw = response.content.strip()

        # Strip markdown code fences if model added them.
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()

        reformulated: list[str] = json.loads(raw)

        if not isinstance(reformulated, list):
            raise ValueError("LLM did not return a JSON array.")

        # Ensure we have exactly 3 strings; pad with original if needed.
        reformulated = [str(q) for q in reformulated[:3]]
        while len(reformulated) < 3:
            reformulated.append(query)

        logger.debug(
            "Query reformulation: original=%r, reformulated=%r",
            query,
            reformulated,
        )
        return reformulated

    except (json.JSONDecodeError, ValueError, Exception) as exc:
        logger.warning(
            "Query reformulation failed (returning original): %s", exc, exc_info=True
        )
        return [query]
