"""
Core models: custom User extending AbstractUser + UserProfile.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


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

RISK_TOLERANCE_CHOICES = [
    ("low", "Low — capital preservation priority"),
    ("medium", "Medium — balanced growth and safety"),
    ("high", "High — growth-oriented, accepts volatility"),
]


class User(AbstractUser):
    """
    Custom user model for Investiq.

    Stores jurisdiction preference so that the RAG retriever can be
    pre-filtered without requiring the user to select it every session.
    """

    preferred_jurisdiction = models.CharField(
        max_length=10,
        choices=JURISDICTION_CHOICES,
        default="DE",
        verbose_name=_("Preferred Jurisdiction"),
        help_text=_("Primary regulatory jurisdiction the user invests under."),
    )
    preferred_language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default="en",
        verbose_name=_("Preferred Language"),
    )

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["-date_joined"]

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def has_profile(self) -> bool:
        return hasattr(self, "profile")

    @property
    def active_goals(self):
        """Return all active investment goals for this user."""
        return self.investment_goals.filter(is_active=True)


class UserProfile(models.Model):
    """
    Extended profile data that supplements the User model.

    Created automatically via post_save signal on User creation.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("User"),
    )
    risk_tolerance = models.CharField(
        max_length=10,
        choices=RISK_TOLERANCE_CHOICES,
        blank=True,
        default="",
        verbose_name=_("Risk Tolerance"),
    )
    investment_horizon_years = models.IntegerField(
        null=True,
        blank=True,
        verbose_name=_("Investment Horizon (years)"),
        help_text=_("How many years until the user plans to draw down investments."),
    )
    monthly_savings_eur = models.FloatField(
        null=True,
        blank=True,
        verbose_name=_("Monthly Savings (EUR)"),
    )
    bio = models.TextField(
        blank=True,
        verbose_name=_("Bio"),
        help_text=_("Free-form background — used as additional context for the RAG assistant."),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User Profile")
        verbose_name_plural = _("User Profiles")

    def __str__(self):
        return f"Profile({self.user})"
