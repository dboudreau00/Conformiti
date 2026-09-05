"""
Gaps in a vendor's assurance that somebody has to chase.

A SOC 2 report covers a period. When that period ends and the next report is
still being written, the provider issues a **bridge letter** stating that
nothing material changed in between -- and an auditor will ask to see it.
This module finds the vendors whose latest SOC report has lapsed with neither
a newer report nor a bridge letter on file, for the in-app feed and for the
emailed reminder.
"""
from django.db.models import Q
from django.utils import timezone

from .models import Vendor, VendorAssessment


def lapsed_soc_report(vendor, today=None):
    """The vendor's most recent SOC report if it has lapsed uncovered, else None."""
    today = today or timezone.localdate()
    rows = list(vendor.assessments.all())
    soc = [a for a in rows if a.kind in VendorAssessment.BRIDGEABLE and a.expires_at]
    if not soc:
        return None
    latest = max(soc, key=lambda a: a.expires_at)
    if latest.expires_at >= today:
        return None
    covered = any(
        a.kind in (*VendorAssessment.BRIDGEABLE, VendorAssessment.Kind.BRIDGE_LETTER)
        and a.expires_at and a.expires_at >= today
        for a in rows
    )
    return None if covered else latest


def bridge_letter_gaps(user=None, today=None):
    """``[(vendor, lapsed_report)]`` for live vendors -- those the user owns,
    or every one when they can manage frameworks (or no user is given)."""
    live = Vendor.objects.filter(status__in=("active", "offboarding")).prefetch_related("assessments")
    if user is not None and not (user.is_superuser or user.can_manage_frameworks):
        live = live.filter(owner=user)
    live = live.filter(Q(assessments__kind__in=VendorAssessment.BRIDGEABLE)).distinct()
    out = []
    for vendor in live.select_related("owner"):
        report = lapsed_soc_report(vendor, today)
        if report is not None:
            out.append((vendor, report))
    return out
