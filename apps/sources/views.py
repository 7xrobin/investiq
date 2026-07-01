"""
Admin-only UI for managing authoritative tax sources.

These are URLs the agent treats as the primary source of truth for tax
questions. Ingestion reuses the shared embed_url pipeline (apps.embed.pipeline)
with is_tax_authority=True, so chunks land in the same Chroma corpus but are
flagged for retrieval prioritisation.
"""
from __future__ import annotations

import json
import logging
import threading

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.sources.models import SourceDocument

logger = logging.getLogger(__name__)


def _staff_required(view_func):
    """Return 403 JSON if the user is not staff (mirrors apps.embed.views)."""
    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff access required."}, status=403)
        return view_func(self, request, *args, **kwargs)
    return wrapper


class TaxSourceListView(LoginRequiredMixin, View):
    """GET /tax-sources/ — staff-only page listing authoritative tax sources."""

    def get(self, request):
        if not request.user.is_staff:
            raise PermissionDenied

        sources_data = list(
            SourceDocument.objects.filter(is_tax_authority=True)
            .order_by("-last_ingested", "title")
            .values(
                "id", "title", "url", "jurisdiction",
                "chunk_count", "last_ingested", "is_active",
            )
        )
        for s in sources_data:
            if s["last_ingested"]:
                s["last_ingested"] = s["last_ingested"].isoformat()
        return render(request, "sources/tax_sources.html", {
            "sources_json": json.dumps(sources_data),
        })


class TaxSourceAddView(LoginRequiredMixin, View):
    """POST /tax-sources/add/ — ingest a URL as an authoritative tax source."""

    @_staff_required
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        url = body.get("url", "").strip()
        jurisdiction = body.get("jurisdiction", "DE")

        if not url or not url.startswith("http"):
            return JsonResponse(
                {"error": "A valid URL starting with http is required."}, status=400
            )

        # Pass only what the user explicitly provided; the pipeline fills the rest.
        # is_tax_authority=True is what marks every resulting chunk as tax truth.
        metadata = {
            "jurisdiction": jurisdiction,
            "title": body.get("title", "").strip(),
            "source_type": body.get("source_type", "regulatory"),
            "is_tax_authority": True,
        }

        from apps.embed.pipeline import embed_url

        t = threading.Thread(target=embed_url, args=(url, metadata), daemon=True)
        t.start()

        logger.info("Tax source ingestion started: %s (%s)", url, jurisdiction)
        return JsonResponse({"status": "started", "url": url})


class TaxSourceDeleteView(LoginRequiredMixin, View):
    """POST /tax-sources/<pk>/delete/ — deactivate a tax source.

    Sets is_active=False (mirrors GoalDeactivateView). Existing Chroma chunks
    are left in place; deactivated sources are excluded from corpus refresh.
    """

    @_staff_required
    def post(self, request, pk: int):
        source = get_object_or_404(SourceDocument, pk=pk, is_tax_authority=True)
        source.is_active = False
        source.save(update_fields=["is_active"])

        if "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"status": "deactivated", "source_id": source.pk})
        return redirect("sources:tax_list")


class TaxSourceStatusView(LoginRequiredMixin, View):
    """GET /tax-sources/status/ — JSON list for live polling of ingestion progress."""

    @_staff_required
    def get(self, request):
        sources = list(
            SourceDocument.objects.filter(is_tax_authority=True)
            .order_by("-last_ingested", "title")
            .values(
                "id", "title", "url", "jurisdiction",
                "chunk_count", "last_ingested", "is_active",
            )
        )
        for s in sources:
            if s["last_ingested"]:
                s["last_ingested"] = s["last_ingested"].isoformat()
        return JsonResponse({"sources": sources})
