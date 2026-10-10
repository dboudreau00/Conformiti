"""Daily readiness snapshot (Celery beat; cron installs can call
``manage.py record_readiness`` instead)."""
import logging

from celery import shared_task

from accounts import tenancy

from .snapshots import record_today

logger = logging.getLogger(__name__)


@shared_task(name="analytics.tasks.record_readiness_snapshot")
def record_readiness_snapshot():
    """One snapshot per workspace per day."""
    result = {}
    for workspace in tenancy.for_each_workspace():
        # A failure in one workspace must not leave the later ones unrecorded.
        try:
            snap = record_today(force=True)
            result[workspace.slug] = snap.pct if snap else None
        except Exception:
            logger.exception("Readiness snapshot failed for workspace %s", workspace.slug)
            result[workspace.slug] = None
    return result
