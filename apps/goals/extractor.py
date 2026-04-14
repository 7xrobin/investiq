"""
Investment goal extractor — uses LLM to parse structured goals from free text.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from langchain_openai import ChatOpenAI

from apps.rag.prompts import GOAL_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


def extract_goals(text: str) -> dict[str, Any]:
    """
    Run GOAL_EXTRACTION_PROMPT against the provided text and return parsed data.

    Uses a low-temperature LLM call to reliably produce JSON output. Falls
    back gracefully to a dict of None values on any parse or API error.

    Args:
        text: Free-form user text containing potential investment goal signals.

    Returns:
        Dict with keys: horizon_years, risk_tolerance, target_return_pct,
        monthly_savings_eur, goal_description. Values are typed or None.
    """
    empty_result: dict[str, Any] = {
        "horizon_years": None,
        "risk_tolerance": None,
        "target_return_pct": None,
        "monthly_savings_eur": None,
        "goal_description": "",
    }

    if not text or not text.strip():
        return empty_result

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.0,  # Deterministic for structured extraction.
        openai_api_key=settings.OPENAI_API_KEY,
    )

    chain = GOAL_EXTRACTION_PROMPT | llm

    try:
        response = chain.invoke({"user_text": text.strip()})
        raw = response.content.strip()

        # Strip markdown code fences if model wrapped output.
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(lines[1:-1]).strip()

        parsed: dict[str, Any] = json.loads(raw)

    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("Goal extraction JSON parse error: %s | raw=%r", exc, raw if "raw" in dir() else "")
        return empty_result
    except Exception as exc:
        logger.error("Goal extraction LLM error: %s", exc, exc_info=True)
        return empty_result

    # Sanitise types.
    result: dict[str, Any] = {}

    horizon = parsed.get("horizon_years")
    result["horizon_years"] = int(horizon) if horizon is not None else None

    risk = parsed.get("risk_tolerance")
    result["risk_tolerance"] = (
        str(risk).lower() if risk in ("low", "medium", "high") else None
    )

    target = parsed.get("target_return_pct")
    try:
        result["target_return_pct"] = float(target) if target is not None else None
    except (ValueError, TypeError):
        result["target_return_pct"] = None

    savings = parsed.get("monthly_savings_eur")
    try:
        result["monthly_savings_eur"] = float(savings) if savings is not None else None
    except (ValueError, TypeError):
        result["monthly_savings_eur"] = None

    result["goal_description"] = str(parsed.get("goal_description", "")).strip()

    logger.debug("Extracted goals from text: %r", result)
    return result


def upsert_goal(user, conversation, goal_data: dict[str, Any]):
    """
    Create or update an InvestmentGoal from extracted goal data.

    TODO: Make goals multiple goals possible
    Deactivates all previous active goals for this user before creating the
    new one, ensuring only one active goal exists at a time.

    Args:
        user: User instance.
        conversation: Conversation instance (can be None).
        goal_data: Dict returned by extract_goals().

    Returns:
        The newly created or updated InvestmentGoal instance.
    """
    from .models import InvestmentGoal

    # Skip if no meaningful data was extracted.
    has_data = any(
        goal_data.get(k) is not None
        for k in ("horizon_years", "risk_tolerance", "target_return_pct", "monthly_savings_eur")
    ) or bool(goal_data.get("goal_description"))

    if not has_data:
        logger.debug("upsert_goal: no meaningful goal data found, skipping.")
        return None

    # Deactivate existing active goals.
    InvestmentGoal.objects.filter(user=user, is_active=True).update(is_active=False)

    # Create new active goal.
    goal = InvestmentGoal.objects.create(
        user=user,
        conversation=conversation,
        horizon_years=goal_data.get("horizon_years"),
        risk_tolerance=goal_data.get("risk_tolerance"),
        target_return_pct=goal_data.get("target_return_pct"),
        monthly_savings_eur=goal_data.get("monthly_savings_eur"),
        goal_description=goal_data.get("goal_description", ""),
        is_active=True,
    )
    logger.info("Created InvestmentGoal pk=%d for user=%s", goal.pk, user)
    return goal
