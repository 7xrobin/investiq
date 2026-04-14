"""
SourceDocument — tracks ingested corpus sources (one row per source, not per chunk).

Chunks live in pgvector; this table provides an admin-visible inventory of
what's been ingested, when, and how many chunks each source produced.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

SOURCE_TYPE_CHOICES = [
    ("regulatory", "Regulatory"),
    ("academic", "Academic"),
    ("news", "News"),
    ("other", "Other"),
]

JURISDICTION_CHOICES = [
    ("DE", "Germany"),
    ("EU", "European Union"),
    ("UK", "United Kingdom"),
    ("US", "United States"),
    ("GLOBAL", "Global"),
]

LANGUAGE_CHOICES = [
    ("en", "English"),
    ("de", "German"),
]


class SourceDocument(models.Model):
    """
    Metadata record for each ingested source document.

    One row per source (PDF or URL). Chunk count reflects the number of
    pgvector rows produced during the last ingestion run.
    """

    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default="regulatory",
        verbose_name=_("Source Type"),
    )
    author = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Author / Issuing Body"),
    )
    title = models.CharField(
        max_length=500,
        verbose_name=_("Title"),
    )
    year = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Publication Year"),
    )
    jurisdiction = models.CharField(
        max_length=10,
        choices=JURISDICTION_CHOICES,
        default="DE",
        verbose_name=_("Jurisdiction"),
    )
    url = models.URLField(
        blank=True,
        default="",
        max_length=2048,
        verbose_name=_("Source URL"),
    )
    language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default="en",
        verbose_name=_("Language"),
    )
    tags = models.JSONField(
        default=list,
        blank=True,
        verbose_name=_("Tags"),
        help_text=_("List of string tags for filtering and categorisation."),
    )
    last_ingested = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Ingested"),
        help_text=_("Timestamp of the most recent successful ingestion."),
    )
    chunk_count = models.IntegerField(
        default=0,
        verbose_name=_("Chunk Count"),
        help_text=_("Number of pgvector chunks produced from this source."),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("Inactive sources are excluded from corpus refresh."),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Source Document")
        verbose_name_plural = _("Source Documents")
        ordering = ["-last_ingested", "title"]
        unique_together = [("title", "url")]

    def __str__(self):
        year_str = f" ({self.year})" if self.year else ""
        return f"{self.title}{year_str} [{self.jurisdiction}]"
