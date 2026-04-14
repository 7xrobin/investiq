"""Admin for source documents — provides corpus management UI."""
from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import SourceDocument


@admin.register(SourceDocument)
class SourceDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "author",
        "source_type",
        "jurisdiction",
        "language",
        "year",
        "chunk_count",
        "last_ingested",
        "is_active",
        "url_link",
    )
    list_filter = ("source_type", "jurisdiction", "language", "is_active")
    search_fields = ("title", "author", "url")
    ordering = ("-last_ingested",)
    readonly_fields = ("created_at", "last_ingested", "chunk_count")
    list_editable = ("is_active",)
    list_per_page = 50

    fieldsets = (
        (
            _("Document Details"),
            {"fields": ("title", "author", "year", "source_type", "url", "language")},
        ),
        (
            _("Classification"),
            {"fields": ("jurisdiction", "tags")},
        ),
        (
            _("Ingestion Status"),
            {"fields": ("last_ingested", "chunk_count", "is_active", "created_at")},
        ),
    )

    @admin.display(description=_("URL"))
    def url_link(self, obj):
        if obj.url:
            return format_html('<a href="{}" target="_blank">Open</a>', obj.url)
        return "—"

    actions = ["mark_inactive", "mark_active"]

    @admin.action(description=_("Mark selected sources as inactive"))
    def mark_inactive(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description=_("Mark selected sources as active"))
    def mark_active(self, request, queryset):
        queryset.update(is_active=True)
