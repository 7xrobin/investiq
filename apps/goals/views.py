"""
Views for the investment goals app.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from .extractor import extract_goals, upsert_goal
from .models import InvestmentGoal

logger = logging.getLogger(__name__)


def _goal_to_dict(g: InvestmentGoal) -> dict:
    """Serialise an InvestmentGoal to the JSON shape used by the API."""
    return {
        "id": g.pk,
        "is_active": g.is_active,
        "horizon_years": g.horizon_years,
        "risk_tolerance": g.risk_tolerance,
        "target_return_pct": g.target_return_pct,
        "monthly_savings_eur": g.monthly_savings_eur,
        "goal_description": g.goal_description,
        "context_string": g.to_context_string(),
        "created_at": g.created_at.isoformat(),
    }


class GoalListView(LoginRequiredMixin, View):
    """
    GET /goals/ — render HTML goals page (empty state or active goal card).

    Content-negotiates: returns JSON when the Accept header requests it or
    when the ?format=json query param is set, preserving the existing API.
    """

    def get(self, request):
        goals = InvestmentGoal.objects.filter(user=request.user).order_by("-created_at")

        wants_json = (
            "application/json" in request.headers.get("Accept", "")
            or request.GET.get("format") == "json"
        )
        if wants_json:
            return JsonResponse({"goals": [_goal_to_dict(g) for g in goals]})

        active_goal = goals.filter(is_active=True).first()
        history = goals.filter(is_active=False)
        return render(request, "goals/list.html", {
            "active_goal": active_goal,
            "history": history,
        })


@method_decorator(csrf_exempt, name="dispatch")
class GoalExtractView(LoginRequiredMixin, View):
    """
    POST /goals/extract/ — extract goals from free text and upsert.

    Expected JSON body:
        {
            "text": "<user text describing goals>",
            "conversation_id": 42  # optional
        }
    """

    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        text = body.get("text", "").strip()
        if not text:
            return JsonResponse({"error": "text field is required."}, status=400)

        conversation_id = body.get("conversation_id")
        conversation = None
        if conversation_id:
            from apps.chat.models import Conversation

            conversation = Conversation.objects.filter(
                pk=conversation_id, user=request.user
            ).first()

        # Extract structured data from text.
        goal_data = extract_goals(text)
        logger.info("Extracted goal data for user=%s: %r", request.user, goal_data)

        # Persist.
        goal = upsert_goal(
            user=request.user,
            conversation=conversation,
            goal_data=goal_data,
        )

        if goal is None:
            return JsonResponse(
                {
                    "status": "no_data",
                    "message": "No investment goal information found in the provided text.",
                    "extracted": goal_data,
                }
            )

        return JsonResponse(
            {
                "status": "created",
                "goal": {
                    "id": goal.pk,
                    "is_active": goal.is_active,
                    "horizon_years": goal.horizon_years,
                    "risk_tolerance": goal.risk_tolerance,
                    "target_return_pct": goal.target_return_pct,
                    "monthly_savings_eur": goal.monthly_savings_eur,
                    "goal_description": goal.goal_description,
                    "context_string": goal.to_context_string(),
                },
            },
            status=201,
        )


@method_decorator(csrf_exempt, name="dispatch")
class GoalDeactivateView(LoginRequiredMixin, View):
    """
    POST /goals/<pk>/deactivate/ — deactivate a specific goal.
    """

    def post(self, request, pk: int):
        goal = get_object_or_404(InvestmentGoal, pk=pk, user=request.user)
        goal.is_active = False
        goal.save(update_fields=["is_active", "updated_at"])

        # Programmatic callers get JSON; browser form posts get a redirect back.
        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"status": "deactivated", "goal_id": goal.pk})
        return redirect("goals:list")
