"""URL patterns for the chat app."""
from django.urls import path

from . import views

app_name = "chat"

urlpatterns = [
    path("", views.ChatView.as_view(), name="index"),
    path("stream/", views.StreamView.as_view(), name="stream"),
    path("history/<int:conversation_id>/", views.ConversationHistoryView.as_view(), name="history"),
    path("conversations/", views.ConversationListView.as_view(), name="conversations"),
]
