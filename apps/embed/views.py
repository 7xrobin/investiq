"""
Views for the Embed app — staff-only UI for uploading PDFs and submitting URLs
to the Chroma vector store.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.views import View

from apps.sources.models import SourceDocument

logger = logging.getLogger(__name__)

_PDF_DIR = None  # resolved lazily to avoid import-time settings access


def _pdf_dir() -> Path:
    global _PDF_DIR
    if _PDF_DIR is None:
        from django.conf import settings
        _PDF_DIR = Path(settings.BASE_DIR) / "data" / "pdfs"
        _PDF_DIR.mkdir(parents=True, exist_ok=True)
    return _PDF_DIR


def _staff_required(view_func):
    """Return 403 JSON if the user is not staff."""
    def wrapper(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return JsonResponse({"error": "Staff access required."}, status=403)
        return view_func(self, request, *args, **kwargs)
    return wrapper


class EmbedIndexView(LoginRequiredMixin, View):
    def get(self, request):
        if not request.user.is_staff:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        sources = SourceDocument.objects.order_by("-last_ingested")
        sources_data = list(sources.values(
            "id", "title", "source_type", "jurisdiction",
            "chunk_count", "last_ingested", "is_active",
        ))
        for s in sources_data:
            if s["last_ingested"]:
                s["last_ingested"] = s["last_ingested"].isoformat()
        return render(request, "embed/index.html", {
            "sources": sources,
            "sources_json": json.dumps(sources_data),
        })


class EmbedPDFView(LoginRequiredMixin, View):
    @_staff_required
    def post(self, request):
        pdf_file = request.FILES.get("pdf")
        jurisdiction = request.POST.get("jurisdiction", "DE")

        if not pdf_file:
            return JsonResponse({"error": "No PDF file provided."}, status=400)

        # Title is optional — pipeline will auto-extract it from the document.
        title = request.POST.get("title", "").strip()
        filename = f"{slugify(title) or 'document'}-{pdf_file.name}"
        dest = _pdf_dir() / filename
        with open(dest, "wb") as f:
            for chunk in pdf_file.chunks():
                f.write(chunk)

        # Pass only what the user explicitly provided; pipeline fills the rest.
        metadata = {
            "jurisdiction": jurisdiction,
            "title": title,
            "source_type": request.POST.get("source_type", ""),
            "author": request.POST.get("author", ""),
            "year": int(request.POST.get("year") or 0) or None,
            "language": request.POST.get("language", ""),
            "url": "",
        }

        from apps.embed.pipeline import embed_pdf
        t = threading.Thread(target=embed_pdf, args=(str(dest), metadata), daemon=True)
        t.start()

        return JsonResponse({"status": "started", "title": title or pdf_file.name})


class EmbedURLView(LoginRequiredMixin, View):
    @_staff_required
    def post(self, request):
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body."}, status=400)

        url = body.get("url", "").strip()
        jurisdiction = body.get("jurisdiction", "DE")

        if not url or not url.startswith("http"):
            return JsonResponse({"error": "A valid URL starting with http is required."}, status=400)

        # Pass only what the user explicitly provided; pipeline fills the rest.
        metadata = {
            "jurisdiction": jurisdiction,
            "title": body.get("title", "").strip(),
            "source_type": body.get("source_type", ""),
            "author": body.get("author", "").strip(),
            "year": int(body.get("year") or 0) or None,
            "language": body.get("language", ""),
        }

        from apps.embed.pipeline import embed_url
        t = threading.Thread(target=embed_url, args=(url, metadata), daemon=True)
        t.start()

        return JsonResponse({"status": "started", "url": url})


class EmbedStatusView(LoginRequiredMixin, View):
    @_staff_required
    def get(self, request):
        sources = list(
            SourceDocument.objects.order_by("-last_ingested").values(
                "id", "title", "source_type", "jurisdiction",
                "chunk_count", "last_ingested", "is_active",
            )
        )
        for s in sources:
            if s["last_ingested"]:
                s["last_ingested"] = s["last_ingested"].isoformat()
        return JsonResponse({"sources": sources})
