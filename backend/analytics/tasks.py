"""Daily readiness snapshot (Celery beat; cron installs can call
``manage.py record_readiness`` instead)."""
from celery import shared_task

from accounts import tenancy

from .snapshots import record_today


@shared_task(name="analytics.tasks.record_readiness_snapshot")
def record_readiness_snapshot():
    """One snapshot per workspace per day."""
    result = {}
    for workspace in tenancy.for_each_workspace():
        snap = record_today(force=True)
        result[workspace.slug] = snap.pct if snap else None
    return result
