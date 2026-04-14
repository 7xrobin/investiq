"""
Investment goal model — stores structured goals extracted from conversation.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

RISK_TOLERANCE_CHOICES = [
    ("low", "Low — capital preservation priority"),
    ("medium", "Medium — balanced growth and safety"),
    ("high", "High — growth-oriented, accepts volatility"),
]


class InvestmentGoal(models.Model):
    """
    Structured investment goal for a user, optionally tied to a conversation.

    Goals are extracted from natural-language text by the LLM (extractor.py).
    Only one goal is "active" per user at any time — the most recently
    created active goal is used to personalise RAG responses.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="investment_goals",
        verbose_name=_("User"),
    )
    conversation = models.ForeignKey(
        "chat.Conversation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="extracted_goals",
        verbose_name=_("Source Conversation"),
        help_text=_("The conversation from which this goal was extracted, if applicable."),
    )
    horizon_years = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Investment Horizon (years)"),
    )
    risk_tolerance = models.CharField(
        max_length=10,
        choices=RISK_TOLERANCE_CHOICES,
        null=True,
        blank=True,
        verbose_name=_("Risk Tolerance"),
    )
    target_return_pct = models.FloatField(
        null=True,
        blank=True,
        verbose_name=_("Target Annual Return (%)"),
    )
    monthly_savings_eur = models.FloatField(
        null=True,
        blank=True,
        verbose_name=_("Monthly Savings (EUR)"),
    )
    goal_description = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Goal Description"),
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active"),
        help_text=_("Only one active goal is used per user for personalisation."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Investment Goal")
        verbose_name_plural = _("Investment Goals")
        ordering = ["-created_at"]

    def __str__(self):
        parts = []
        if self.goal_description:
            parts.append(self.goal_description[:60])
        if self.horizon_years:
            parts.append(f"{self.horizon_years}yr")
        if self.risk_tolerance:
            parts.append(self.risk_tolerance)
        return f"Goal({self.user}) — " + ", ".join(parts) if parts else f"Goal {self.pk}"

    def to_context_string(self) -> str:
        """
        Format this goal as a compact natural-language string for the RAG prompt.
        """
        parts = []
        if self.goal_description:
            parts.append(f"Goal: {self.goal_description}")
        if self.horizon_years is not None:
            parts.append(f"Horizon: {self.horizon_years} years")
        if self.risk_tolerance:
            label = dict(RISK_TOLERANCE_CHOICES).get(self.risk_tolerance, self.risk_tolerance)
            parts.append(f"Risk tolerance: {label}")
        if self.target_return_pct is not None:
            parts.append(f"Target return: {self.target_return_pct:.1f}% per year")
        if self.monthly_savings_eur is not None:
            parts.append(f"Monthly savings: €{self.monthly_savings_eur:,.0f}")
        return " | ".join(parts) if parts else "No structured investment goals set."
