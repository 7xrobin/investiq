"""
Root URL configuration for the investiq project.
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Django built-in auth views (login, logout, password reset, etc.)
    path("accounts/", include("django.contrib.auth.urls")),

    # Application routes
    path("chat/", include("apps.chat.urls", namespace="chat")),
    path("goals/", include("apps.goals.urls", namespace="goals")),
    path("embed/", include("apps.embed.urls", namespace="embed")),

    # Redirect root to chat
    path("", auth_views.LoginView.as_view(template_name="registration/login.html"), name="home"),
]
