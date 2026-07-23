"""Celery entrypoint. Run: celery -A config worker -B -l info"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("conformiti")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
