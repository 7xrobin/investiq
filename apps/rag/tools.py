"""
LangChain tools for the Investiq agent.

Goal management and portfolio simulation — side-effects the LLM can trigger
mid-conversation. Retrieval is not a tool; it runs unconditionally in agent.py.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

def _fetch_active_goal_card(user_id: int) -> dict | None:
    """Return the user's current active goal as a card-ready dict, or None."""
    from apps.goals.models import InvestmentGoal, RISK_TOLERANCE_CHOICES

    goal = (
        InvestmentGoal.objects.filter(user_id=user_id, is_active=True)
        .order_by("-created_at")
        .first()
    )
    if goal is None:
        return None

    risk_display = (
        dict(RISK_TOLERANCE_CHOICES).get(goal.risk_tolerance, "")
        if goal.risk_tolerance
        else ""
    )
    return {
        "id": goal.pk,
        "goal_description": goal.goal_description or "",
        "horizon_years": goal.horizon_years,
        "risk_tolerance": goal.risk_tolerance,
        "risk_tolerance_display": risk_display,
        "target_return_pct": goal.target_return_pct,
        "monthly_savings_eur": goal.monthly_savings_eur,
        "created_at": goal.created_at.isoformat(),
    }

_UPDATABLE_GOAL_FIELDS = frozenset(
    {"horizon_years", "risk_tolerance", "target_return_pct", "monthly_savings_eur", "goal_description"}
)


def make_goal_tools(user_id: int, conversation_id: int) -> list:
    """Goal tools with user context captured in closures — not passed by the LLM."""

    @tool
    def save_investment_goal(
        goal_description: str,
        horizon_years: int | None = None,
        risk_tolerance: str | None = None,
        target_return_pct: float | None = None,
        monthly_savings_eur: float | None = None,
    ) -> str:
        """Save or update the user's investment goal from information shared in conversation.

        Call this when the user explicitly states investment objectives, time horizon,
        risk tolerance, target return, or monthly savings amount. All fields except
        goal_description are optional. risk_tolerance must be 'low', 'medium', or 'high'.
        """
        from django.contrib.auth import get_user_model

        from apps.chat.models import Conversation
        from apps.goals.extractor import upsert_goal

        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return "Error: Could not find user — goal not saved."

        conversation = Conversation.objects.filter(pk=conversation_id).first()
        goal_data = {
            "horizon_years": horizon_years,
            "risk_tolerance": risk_tolerance,
            "target_return_pct": target_return_pct,
            "monthly_savings_eur": monthly_savings_eur,
            "goal_description": goal_description,
        }
        goal = upsert_goal(user=user, conversation=conversation, goal_data=goal_data)
        if goal is None:
            return "No meaningful goal data provided — goal was not saved."

        logger.info("save_investment_goal: created goal pk=%d for user=%d", goal.pk, user_id)
        return f"Investment goal saved. {goal.to_context_string()}"

    @tool
    def update_investment_goal(field: str, value: str) -> str:
        """Update a single field on the user's active investment goal.

        field must be one of: horizon_years, risk_tolerance, target_return_pct,
        monthly_savings_eur, goal_description. value is coerced to the correct type.
        """
        from django.contrib.auth import get_user_model

        from apps.goals.models import InvestmentGoal

        if field not in _UPDATABLE_GOAL_FIELDS:
            return (
                f"'{field}' is not a valid goal field. "
                f"Choose from: {', '.join(sorted(_UPDATABLE_GOAL_FIELDS))}"
            )

        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return "Error: Could not find user."

        goal = (
            InvestmentGoal.objects.filter(user=user, is_active=True)
            .order_by("-created_at")
            .first()
        )
        if goal is None:
            return "No active investment goal found. Use save_investment_goal to create one first."

        try:
            if field == "horizon_years":
                setattr(goal, field, int(value))
            elif field in ("target_return_pct", "monthly_savings_eur"):
                setattr(goal, field, float(value))
            elif field == "risk_tolerance":
                v = value.lower().strip()
                if v not in ("low", "medium", "high"):
                    return "risk_tolerance must be 'low', 'medium', or 'high'."
                setattr(goal, field, v)
            else:
                setattr(goal, field, value)

            goal.save(update_fields=[field, "updated_at"])
        except (ValueError, TypeError) as exc:
            return f"Could not update {field}: {exc}"

        logger.info("update_investment_goal: updated %s on goal pk=%d", field, goal.pk)
        return f"Updated {field}. {goal.to_context_string()}"

    return [save_investment_goal, update_investment_goal]


@tool
def simulate_portfolio_returns(
    initial_amount_eur: float,
    monthly_contribution_eur: float,
    annual_return_pct: float,
    years: int,
) -> str:
    """Simulate portfolio growth using compound interest with monthly contributions.

    Use when the user asks for a future value projection or 'what would €X grow to'.
    Always append the §63 WpHG disclaimer after presenting the result.

    FV = PV*(1+r)^n + PMT*(((1+r)^n - 1) / r),  r = annual_return_pct/100/12
    """
    if years <= 0 or years > 100:
        return "years must be between 1 and 100."
    if annual_return_pct < -50 or annual_return_pct > 100:
        return "annual_return_pct seems outside a realistic range (-50 to 100)."

    r = annual_return_pct / 100 / 12

    header = (
        f"Portfolio simulation: €{initial_amount_eur:,.0f} initial, "
        f"€{monthly_contribution_eur:,.0f}/month, "
        f"{annual_return_pct:.1f}% p.a. over {years} years\n"
    )
    lines = [header, f"{'Year':>4}  {'Portfolio Value':>16}  {'Total Contributed':>18}"]
    lines.append("-" * 42)

    for yr in range(1, years + 1):
        n = yr * 12
        if r == 0:
            fv = initial_amount_eur + monthly_contribution_eur * n
        else:
            fv = (
                initial_amount_eur * (1 + r) ** n
                + monthly_contribution_eur * (((1 + r) ** n - 1) / r)
            )
        contributed = initial_amount_eur + monthly_contribution_eur * n
        lines.append(f"{yr:>4}  €{fv:>14,.0f}  €{contributed:>16,.0f}")

    return "\n".join(lines)


@tool
def calculate_required_investment(
    target_amount_eur: float,
    years: int,
    annual_return_pct: float,
    initial_amount_eur: float = 0.0,
) -> str:
    """Work out how much the user must invest to reach a target amount.

    Use when the user asks "how much do I need to invest to reach €X in Y years"
    or "what monthly amount gets me to my goal". Computes both the required
    monthly contribution (given any starting lump sum) and the required one-off
    lump sum today (with no monthly contributions). Always append the §63 WpHG
    disclaimer after presenting the result.

    Inverse of simulate_portfolio_returns:
      FV = PV*(1+r)^n + PMT*(((1+r)^n - 1) / r),  r = annual_return_pct/100/12
    Solved for PMT and, separately, for PV.
    """
    if years <= 0 or years > 100:
        return "years must be between 1 and 100."
    if annual_return_pct < -50 or annual_return_pct > 100:
        return "annual_return_pct seems outside a realistic range (-50 to 100)."
    if target_amount_eur <= 0:
        return "target_amount_eur must be a positive number."

    r = annual_return_pct / 100 / 12
    n = years * 12
    growth = (1 + r) ** n  # future-value factor for the lump sum

    # Future value already secured by the starting lump sum.
    fv_from_initial = initial_amount_eur * growth
    remaining = target_amount_eur - fv_from_initial

    if remaining <= 0:
        return (
            f"Your initial €{initial_amount_eur:,.0f} alone grows to "
            f"€{fv_from_initial:,.0f} at {annual_return_pct:.1f}% p.a. over {years} years — "
            f"already above your €{target_amount_eur:,.0f} target. No monthly "
            f"contribution is required.\n\n"
            "Disclaimer (§63 WpHG): This is an illustrative projection, not "
            "investment advice. Returns are not guaranteed."
        )

    # Required monthly contribution to cover the remaining gap.
    if r == 0:
        required_monthly = remaining / n
    else:
        annuity_factor = (growth - 1) / r
        required_monthly = remaining / annuity_factor

    # Required one-off lump sum today instead (no monthly contributions).
    required_lump_sum = target_amount_eur / growth

    monthly_contributed = required_monthly * n + initial_amount_eur

    return (
        f"To reach €{target_amount_eur:,.0f} in {years} years at "
        f"{annual_return_pct:.1f}% p.a.:\n\n"
        f"• Starting from €{initial_amount_eur:,.0f}, invest about "
        f"€{required_monthly:,.0f} per month "
        f"(€{monthly_contributed:,.0f} contributed in total over {years} years).\n"
        f"• Or invest a single lump sum of about €{required_lump_sum:,.0f} today "
        f"and contribute nothing further.\n\n"
        "Disclaimer (§63 WpHG): This is an illustrative projection, not "
        "investment advice. Returns are not guaranteed."
    )


def make_all_tools(user_id: int, conversation_id: int) -> list:
    return [
        *make_goal_tools(user_id, conversation_id),
        simulate_portfolio_returns,
        calculate_required_investment,
    ]
