
"""URL patterns for the goals app."""
from django.urls import path

from . import views

app_name = "goals"

urlpatterns = [
    path("", views.GoalListView.as_view(), name="list"),
    path("extract/", views.GoalExtractView.as_view(), name="extract"),
    path("<int:pk>/deactivate/", views.GoalDeactivateView.as_view(), name="deactivate"),
]
