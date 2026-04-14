"""
Signal handlers for the core app.
Auto-creates UserProfile whenever a new User is saved.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User, UserProfile


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create a UserProfile the first time a User is saved."""
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Keep the profile saved in sync with the User."""
    if hasattr(instance, "profile"):
        instance.profile.save()
