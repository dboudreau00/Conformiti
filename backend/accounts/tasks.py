from celery import shared_task
from django.core.management import call_command


@shared_task(name="accounts.tasks.flush_expired_tokens")
def flush_expired_tokens():
    """Prune expired rows from the JWT blacklist tables, which SimpleJWT otherwise never trims."""
    call_command("flushexpiredtokens")
    return True
