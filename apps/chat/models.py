"""
Chat models: Conversation, Message, Citation.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

JURISDICTION_CHOICES = [
    ("DE", "Germany"),
    ("EU", "European Union"),
    ("UK", "United Kingdom"),
    ("US", "United States"),
    ("GLOBAL", "Global"),
]

MESSAGE_ROLE_CHOICES = [
    ("user", "User"),
    ("assistant", "Assistant"),
]

SOURCE_TYPE_CHOICES = [
    ("regulatory", "Regulatory"),
    ("academic", "Academic"),
    ("news", "News"),
    ("other", "Other"),
]


class Conversation(models.Model):
    """A single chat session between a user and KyronInvest."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="conversations",
        verbose_name=_("User"),
    )
    jurisdiction = models.CharField(
        max_length=10,
        choices=JURISDICTION_CHOICES,
        default="DE",
        verbose_name=_("Jurisdiction"),
    )
    title = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Title"),
        help_text=_("Auto-generated from first user message if left blank."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Conversation")
        verbose_name_plural = _("Conversations")
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Conversation {self.pk} ({self.user})"

    def get_title_from_first_message(self) -> str:
        """Return first 80 chars of the first user message as a title."""
        first = self.messages.filter(role="user").order_by("created_at").first()
        if first:
            return first.content[:80]
        return f"Conversation {self.pk}"


class Message(models.Model):
    """A single turn (user or assistant) within a Conversation."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name=_("Conversation"),
    )
    role = models.CharField(
        max_length=10,
        choices=MESSAGE_ROLE_CHOICES,
        verbose_name=_("Role"),
    )
    content = models.TextField(verbose_name=_("Content"))
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Message")
        verbose_name_plural = _("Messages")
        ordering = ["created_at"]

    def __str__(self):
        preview = self.content[:60]
        return f"[{self.role}] {preview}"


class Citation(models.Model):
    """
    A source document chunk that was retrieved and cited in an assistant message.

    The chunk_text is surfaced in the left-panel "Sources & References" panel.
    """

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="citations",
        verbose_name=_("Message"),
    )
    source_title = models.CharField(max_length=500, verbose_name=_("Source Title"))
    source_author = models.CharField(max_length=255, blank=True, default="", verbose_name=_("Author"))
    source_year = models.IntegerField(null=True, blank=True, verbose_name=_("Year"))
    source_url = models.URLField(blank=True, default="", verbose_name=_("URL"))
    source_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Source ID"),
        help_text=_("Stable source identifier from embedding metadata."),
    )
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        default="regulatory",
        verbose_name=_("Source Type"),
    )
    page_number = models.IntegerField(null=True, blank=True, verbose_name=_("Page Number"))
    chunk_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name=_("Chunk ID"),
        help_text=_("Stable chunk identifier from embedding metadata."),
    )
    jurisdiction = models.CharField(
        max_length=10,
        choices=JURISDICTION_CHOICES,
        default="DE",
        verbose_name=_("Jurisdiction"),
    )
    relevance_score = models.FloatField(
        null=True,
        blank=True,
        verbose_name=_("Relevance Score"),
        help_text=_("Cosine similarity score from vector search (0–1)."),
    )
    chunk_text = models.TextField(
        verbose_name=_("Chunk Text"),
        help_text=_("The exact retrieved chunk displayed in the references panel."),
    )

    class Meta:
        verbose_name = _("Citation")
        verbose_name_plural = _("Citations")
        ordering = ["-relevance_score"]

    def __str__(self):
        return f"{self.source_title} ({self.source_year})"

    def to_dict(self) -> dict:
        return {
            "id": self.pk,
            "source_title": self.source_title,
            "source_author": self.source_author,
            "source_year": self.source_year,
            "source_url": self.source_url,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "page_number": self.page_number,
            "chunk_id": self.chunk_id,
            "jurisdiction": self.jurisdiction,
            "relevance_score": self.relevance_score,
            "chunk_text": self.chunk_text,
        }
