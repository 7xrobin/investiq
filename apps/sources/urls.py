"""URL patterns for the sources app (admin-only tax source management)."""
from django.urls import path

from . import views

app_name = "sources"

urlpatterns = [
    path("", views.TaxSourceListView.as_view(), name="tax_list"),
    path("add/", views.TaxSourceAddView.as_view(), name="tax_add"),
    path("<int:pk>/delete/", views.TaxSourceDeleteView.as_view(), name="tax_delete"),
    path("status/", views.TaxSourceStatusView.as_view(), name="tax_status"),
]
