"""
Retire the demo dataset before going live.

    python manage.py remove_demo_data            # deactivate demo users, delete sample content
    python manage.py remove_demo_data --delete   # also delete the demo user accounts
    python manage.py remove_demo_data --dry-run  # report only

The seeded accounts share one published password (DemoPass123!), so they must
never survive into a real deployment. This command:

  * deactivates (or, with --delete, removes) the five demo users — but never
    the account you are running as the only superuser: it refuses to leave the
    installation without an active superuser or administrator;
  * deletes the sample documents, risks, meeting series, champion group,
    calendar events, the seeded access review and the nine seeded audit-log
    rows, matching them by the exact names bootstrap_demo created;
  * drops the back-filled readiness history (points dated before today);
  * leaves the framework/control libraries, folders, roles, and the control
    statuses/owners intact (those are yours to reset from the Controls page).

Idempotent: safe to run again.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from accounts.management.commands.bootstrap_demo import (
    ACCESS_REVIEW_PATTERN, DEMO_PACKAGE_NAME, DEMO_USERS, DEMO_VENDOR_NAMES, SAMPLE_DOCS,
)

DEMO_USERNAMES = [u[0] for u in DEMO_USERS]
DEMO_RISKS = [
    "MFA not enforced for contractor accounts",
    "Incident response plan review overdue",
    "Payment processor SOC 2 report expired",
    "Public-read ACL on legacy assets bucket",
]
DEMO_SERIES = ["Security Steering Committee", "Risk Review"]
DEMO_GROUPS = ["Security Champions"]
DEMO_EVENTS = [
    "SOC 2 Type II audit fieldwork",
    "ISO 27001 surveillance audit",
    "Quarterly access review",
]
DEMO_AUDIT_IPS = ["10.0.0.4", "10.0.0.11", "10.0.0.23"]


class Command(BaseCommand):
    help = "Deactivate/delete the demo accounts and remove the sample content."

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true",
                            help="Delete the demo user accounts instead of deactivating them.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change.")

    @transaction.atomic
    def handle(self, *args, **opts):
        from audit.models import AuditLog
        from calendar_app.models import CalendarEvent
        from documents.models import Document
        from attestations.models import EvidencePackage
        from governance.models import AccessReview, ChampionGroup, MeetingSeries, Risk

        User = get_user_model()
        dry = opts["dry_run"]
        delete = opts["delete"]

        demo_users = list(
            User.objects.filter(username__in=DEMO_USERNAMES, email__endswith="@example.com")
        )
        # Guard: the org must keep at least one active superuser/administrator
        # that is NOT one of the demo accounts.
        survivors = (
            User.objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | Q(role__can_manage_users=True))
            .exclude(pk__in=[u.pk for u in demo_users])
        )
        if demo_users and not survivors.exists():
            raise CommandError(
                "Refusing: no administrator other than the demo accounts exists. "
                "Create your own first (python manage.py createsuperuser), then re-run."
            )

        verb = "would" if dry else "will"
        docs = Document.objects.filter(name__in=[d[1] for d in SAMPLE_DOCS], owner__username="owen")
        risks = Risk.objects.filter(title__in=DEMO_RISKS)
        series = MeetingSeries.objects.filter(name__in=DEMO_SERIES)
        groups = ChampionGroup.objects.filter(name__in=DEMO_GROUPS)
        events = CalendarEvent.objects.filter(title__in=DEMO_EVENTS)
        audit_rows = AuditLog.objects.filter(ip_address__in=DEMO_AUDIT_IPS, detail__regex=r"^[a-z]")
        # Only the seeded review, and only while a demo account owns it — a real
        # review an operator started in the same quarter must survive.
        reviews = AccessReview.objects.filter(
            name__regex=ACCESS_REVIEW_PATTERN, created_by__username__in=DEMO_USERNAMES
        )
        packages = EvidencePackage.objects.filter(
            name=DEMO_PACKAGE_NAME, created_by__username__in=DEMO_USERNAMES
        )
        # Vendors cascade to their assessments, shared responsibility rows and
        # RACI rows; a risk that named one is kept and simply loses the link.
        from compliance.models import Responsibility
        from vendors.models import Vendor
        vendors = Vendor.objects.filter(name__in=DEMO_VENDOR_NAMES, created_by__username__in=DEMO_USERNAMES)
        raci = Responsibility.objects.filter(created_by__username__in=DEMO_USERNAMES)

        self.stdout.write(f"Demo users ({'delete' if delete else 'deactivate'}): "
                          f"{', '.join(u.username for u in demo_users) or 'none'}")
        self.stdout.write(f"Sample vendors {verb} be deleted: {vendors.count()}")
        self.stdout.write(f"Seeded RACI rows {verb} be deleted: {raci.count()}")
        self.stdout.write(f"Sample documents {verb} be deleted: {docs.count()}")
        self.stdout.write(f"Sample risks {verb} be deleted: {risks.count()}")
        self.stdout.write(f"Sample meeting series {verb} be deleted: {series.count()}")
        self.stdout.write(f"Sample champion groups {verb} be deleted: {groups.count()}")
        self.stdout.write(f"Sample calendar events {verb} be deleted: {events.count()}")
        self.stdout.write(f"Seeded audit rows {verb} be deleted: {audit_rows.count()}")
        self.stdout.write(f"Seeded access reviews {verb} be deleted: {reviews.count()}")
        self.stdout.write(f"Seeded evidence packages {verb} be deleted: {packages.count()}")
        if dry:
            self.stdout.write(self.style.WARNING("Dry run — nothing changed."))
            return

        from analytics.models import ReadinessSnapshot
        from django.utils import timezone
        history = ReadinessSnapshot.objects.filter(date__lt=timezone.localdate())
        self.stdout.write(f"Seeded readiness history points deleted: {history.count()}")
        history.delete()
        for doc in docs:
            for version in doc.versions.all():
                version.file.delete(save=False)
            doc.file.delete(save=False)
            doc.delete()
        risks.delete()
        series.delete()
        groups.delete()
        events.delete()
        reviews.delete()
        packages.delete()
        audit_rows.delete()
        raci.delete()
        vendors.delete()

        for user in demo_users:
            if delete:
                user.delete()
            else:
                user.is_active = False
                user.set_unusable_password()
                user.save(update_fields=["is_active", "password"])
        self.stdout.write(self.style.SUCCESS(
            "Demo data removed. The published demo password no longer works on this install."
        ))
