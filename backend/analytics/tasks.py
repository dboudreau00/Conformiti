"""Daily readiness snapshot (Celery beat; cron installs can call
``manage.py record_readiness`` instead)."""
from celery import shared_task

from .snapshots import record_today


@shared_task(name="analytics.tasks.record_readiness_snapshot")
def record_readiness_snapshot():
    snap = record_today(force=True)
    return snap.pct if snap else None
