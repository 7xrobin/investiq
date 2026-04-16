"""Admin registration for core models."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = _("Profile")
    fields = ("risk_tolerance", "investment_horizon_years", "monthly_savings_eur", "bio")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "preferred_jurisdiction",
        "preferred_language",
        "is_staff",
        "date_joined",
    )
    list_filter = ("preferred_jurisdiction", "preferred_language", "is_staff", "is_active")
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            _("Investiq"),
            {"fields": ("preferred_jurisdiction", "preferred_language")},
        ),
    )
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("-date_joined",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "risk_tolerance", "investment_horizon_years", "monthly_savings_eur")
    list_filter = ("risk_tolerance",)
    search_fields = ("user__username", "user__email")
    raw_id_fields = ("user",)
