from django.urls import path

from apps.embed.views import EmbedIndexView, EmbedPDFView, EmbedStatusView, EmbedURLView

app_name = "embed"

urlpatterns = [
    path("", EmbedIndexView.as_view(), name="index"),
    path("pdf/", EmbedPDFView.as_view(), name="pdf"),
    path("url/", EmbedURLView.as_view(), name="url"),
    path("status/", EmbedStatusView.as_view(), name="status"),
]
