"""
config package — makes Celery app available when Django starts.
"""
from celery_app import app as celery_app

__all__ = ("celery_app",)
