"""Housekeeping tasks for authentication state."""
from celery import shared_task
from django.core.management import call_command


@shared_task(name="accounts.tasks.flush_expired_tokens")
def flush_expired_tokens():
    """Prune expired rows from the JWT blacklist tables (SimpleJWT keeps every
    rotated refresh token until this runs). Scheduled weekly by Celery beat;
    cron deployments can run ``manage.py flushexpiredtokens`` instead."""
    call_command("flushexpiredtokens")
    return True
