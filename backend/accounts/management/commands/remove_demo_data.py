"""Retire the demo dataset. Idempotent: a later run resets no status, deletes no readiness history and no sample row,
because what changed since the retirement is the operator's. The retirement record stops ``bootstrap_demo`` seeding it
back. A row is the demo's only when the seeder recorded it or a demo account made it: a real row that shares a demo
name, or has no creator, stays, and a workspace that never held the demo loses nothing."""
from functools import reduce
from operator import or_

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts import tenancy
from accounts.management.commands.bootstrap_demo import (
    ACCESS_REVIEW_PATTERN, DEMO_PACKAGE_NAME, DEMO_USERS, DEMO_VENDOR_NAMES, PROGRAMME_MARK,
    PROGRAMME_OBJECT_TYPE, PROGRAMME_ORDER, RETIRED_ACTION, RETIRED_OBJECT_TYPE, REVIVED_ACTION,
    SAMPLE_DOCS, SEEDED_OBJECT_TYPE, SEEDED_SEED_MARK, own_administrator_present, programme_fingerprint,
    programme_values,
    retirement_recorded,
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
# The nine rows bootstrap_demo seeds, as (ip, object type, detail): a real row from the same address is not one of them.
DEMO_AUDIT_ROWS = [
    ("10.0.0.4", "users", "created account tess (Viewer)"),
    ("10.0.0.11", "documents", "marked reviewed: Access Control Policy"),
    ("10.0.0.23", "documents", "uploaded evidence: backup-restore-log.pdf"),
    ("10.0.0.11", "risks", "opened risk: Laptop disk encryption gaps"),
    ("10.0.0.11", "risks", "status open -> mitigating"),
    ("10.0.0.4", "users", "role change: val -> Viewer"),
    ("10.0.0.23", "control-evidence", "linked doc 3 to CC6.1"),
    ("10.0.0.11", "calendar", "scheduled: Q3 access review kickoff"),
    ("10.0.0.4", "folder-permissions", "revoked folder grant for val"),
]

PROGRAMME_READ = "read"              # these controls still hold the demo's status
PROGRAMME_UNREADABLE = "unreadable"  # a live programme that cannot be read back
PROGRAMME_LEFT_BEHIND = "left"       # an older release retired the demo and kept its statuses

# Keyed by the cause _programme_resets found: the warning names the one that applies, so the operator is not sent
# looking for a change that never happened.
_OLDER_RELEASE = ("The demo was seeded by an older release, which kept no record of the "
                  "statuses it set; only the controls the demo accounts own show where it set "
                  "them, and ")
UNREADABLE_BECAUSE = {
    "library": ("Some controls that existed when the demo was seeded have since been removed "
                "from the control library or reordered in it."),
    "record": "The demo's record of the statuses it set cannot be read.",
    "accounts": _OLDER_RELEASE + "no demo account is left.",
    "owners": _OLDER_RELEASE + "no control is owned by a demo account any more.",
    "moved": (_OLDER_RELEASE + "those are no longer the controls it gave them (controls were "
              "added or removed, or owners changed, since it was seeded)."),
}


def _owners_where_the_programme_put_them(walk, demo_by_pk):
    """True when some control in ``walk`` has a demo owner and every such control sits where the programme put that
    owner: the evidence that ``walk`` is the order the programme walked."""
    seen = False
    for i, control in enumerate(walk):
        name = demo_by_pk.get(control.owner_id)
        if name is None:
            continue
        if programme_values(i)[1] != name:
            return False
        seen = True
    return seen


def _still_as_seeded(walk):
    """The pks in ``walk`` whose status still matches the programme's for that position; changed ones are left alone."""
    pks = []
    for i, control in enumerate(walk):
        status = programme_values(i)[0]
        if status is not None and control.status == status:
            pks.append(control.pk)
    return pks


def _seeded_records():
    """``(pks by kind, whether any record exists)`` for the rows the seeder recorded since the last retirement. Older
    ones name rows the retirement deleted, whose numbers a database may hand out again."""
    from audit.models import AuditLog

    since = (AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE, action=RETIRED_ACTION)
             .order_by("-pk").values_list("pk", flat=True).first()) or 0
    pks = {}
    found = False
    for kind, detail in (AuditLog.objects.filter(object_type=SEEDED_OBJECT_TYPE, pk__gt=since)
                         .values_list("object_id", "detail")):
        found = True
        listed = detail.rpartition(":")[2].split(",")
        pks.setdefault(kind, set()).update(int(n) for n in listed if n.strip().isdigit())
    return pks, found


class Command(BaseCommand):
    help = ("Deactivate/delete the demo accounts, remove the sample content and undo the "
            "control statuses and owners the demo set.")

    def add_arguments(self, parser):
        parser.add_argument("--delete", action="store_true",
                            help="Delete the demo user accounts instead of deactivating them.")
        parser.add_argument("--dry-run", action="store_true", help="Report what would change.")
        tenancy.workspace_option(parser)

    @transaction.atomic
    def handle(self, *args, **opts):
        workspace = tenancy.from_option(opts)
        with tenancy.scoped(workspace):
            self._handle(opts, workspace)

    def _handle(self, opts, workspace):
        from analytics.snapshots import record_today
        from audit.models import AuditLog
        from calendar_app.models import CalendarEvent
        from compliance.models import Control
        from documents.models import Document
        from attestations.models import EvidencePackage
        from governance.models import AccessReview, ChampionGroup, MeetingSeries, Risk

        User = get_user_model()
        dry = opts["dry_run"]
        delete = opts["delete"]

        demo_users = list(
            User.objects.filter(username__in=DEMO_USERNAMES, email__endswith="@example.com")
        )
        # Never leave the installation without an administrator of its own; the seeder's advice and the boot banner
        # share this test, so all three say "run createsuperuser" exactly when this refuses.
        if demo_users and not own_administrator_present(workspace):
            raise CommandError(
                "Refusing: no administrator other than the demo accounts exists. "
                "Create your own first (python manage.py createsuperuser), then re-run."
            )
        # Only the run that retires the demo resets statuses and readiness history: afterwards they are the operator's.
        retiring = not retirement_recorded()

        demo_pks = [u.pk for u in demo_users]
        recorded, seed_recorded = _seeded_records()
        audit_rows = AuditLog.objects.filter(
            reduce(or_, (Q(ip_address=ip, object_type=otype, detail=detail) for ip, otype, detail in DEMO_AUDIT_ROWS)))
        # Proof that the demo was seeded in this workspace. Without it nothing below is the demo's, whatever it is
        # called or whoever made it.
        seeded_here = (bool(demo_pks) or seed_recorded or audit_rows.exists()
                       or AuditLog.objects.filter(object_type=PROGRAMME_OBJECT_TYPE).exists()
                       or AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE, action=REVIVED_ACTION).exists())
        # A demo seeded before the seeder recorded its rows (no seed mark since the last retirement; a later refresh may
        # have recorded what it re-created): rows whose creator was since deleted still count, as long as the demo is
        # proven to have been here.
        unrecorded_demo = retiring and seeded_here and SEEDED_SEED_MARK not in recorded

        def sample(model, kind, names=None, name_field=None, creator="created_by", also=Q()):
            """The rows the seeder recorded or a demo account made, narrowed to the demo's names. None once the demo
            was retired: what an operator made since is theirs."""
            if not retiring:
                return model.objects.none()
            marks = Q(pk__in=recorded.get(kind, ())) | Q(**{f"{creator}__in": demo_pks}) | also
            if unrecorded_demo:
                marks |= Q(**{f"{creator}__isnull": True})
            rows = model.objects.filter(marks)
            return rows.filter(**{f"{name_field}__in": names}) if name_field else rows

        # Older releases set only the owner of a sample document.
        docs = sample(Document, "documents", [d[1] for d in SAMPLE_DOCS], "name",
                      also=Q(created_by__isnull=True, owner__in=demo_pks))
        risks = sample(Risk, "risks", DEMO_RISKS, "title")
        series = sample(MeetingSeries, "series", DEMO_SERIES, "name", creator="owner")
        groups = sample(ChampionGroup, "groups", DEMO_GROUPS, "name", creator="owner")
        # The seeder sets no creator on events, so before it kept records only the title and a missing creator told
        # them apart.
        events = sample(CalendarEvent, "events", DEMO_EVENTS, "title")
        # Only while a demo account made it: a real review started in the same quarter must survive.
        in_scope = AccessReview.objects.all() if retiring else AccessReview.objects.none()
        reviews = in_scope.filter(name__regex=ACCESS_REVIEW_PATTERN, created_by__in=demo_pks)
        in_scope = EvidencePackage.objects.all() if retiring else EvidencePackage.objects.none()
        packages = in_scope.filter(name=DEMO_PACKAGE_NAME, created_by__in=demo_pks)
        # Vendors cascade to their assessments and RACI rows; a risk that named one is kept and loses the link.
        from compliance.models import Responsibility
        from documents.models import FolderPermission
        from vendors.models import Vendor
        vendors = sample(Vendor, "vendors", DEMO_VENDOR_NAMES, "name")
        raci = sample(Responsibility, "responsibilities")
        # The seeder's two role-wide RBAC grants: left behind they would be standing access nobody asked for. They
        # carry no creator, so the seeder's record is the mark; without one the shape alone is.
        seeded_grants = FolderPermission.objects.none()
        if retiring:
            seeded_grants = FolderPermission.objects.filter(user__isnull=True).filter(
                Q(role__name="Control Owner", folder__name__startswith="CC6 -", access_level="edit")
                | Q(role__name="Auditor", folder__is_framework_root=True, folder__name__icontains="27001",
                    access_level="view"))
            if not unrecorded_demo:
                seeded_grants = seeded_grants.filter(pk__in=recorded.get("grants", ()))
        # Counted before anything is deleted, so a real run can still report them.
        counts = [
            ("Sample vendors", vendors.count()),
            ("Seeded RACI rows", raci.count()),
            ("Seeded folder grants", seeded_grants.count()),
            ("Sample documents", docs.count()),
            ("Sample risks", risks.count()),
            ("Sample meeting series", series.count()),
            ("Sample champion groups", groups.count()),
            ("Sample calendar events", events.count()),
            ("Seeded audit rows", audit_rows.count()),
            ("Seeded access reviews", reviews.count()),
            ("Seeded evidence packages", packages.count()),
        ]
        # With no sign of the demo there is no history or status of its to take: all of it is the operator's.
        demo_seen = seeded_here or any(n for _, n in counts)
        recompute = retiring and demo_seen
        history = self._demo_history(recompute)
        counts.append(("Seeded readiness history points", history.count()))

        # A control owned by an account that can no longer sign in is effectively unowned.
        demo_by_pk = {u.pk: u.username for u in demo_users}
        demo_owned = Control.objects.filter(owner_id__in=list(demo_by_pk))
        programme, reset, unreadable = self._programme_resets(demo_by_pk, retiring, demo_seen)
        owned_count = demo_owned.count()

        if not dry:
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
            seeded_grants.delete()
            if programme == PROGRAMME_READ:
                Control.objects.filter(pk__in=reset).update(status=Control.Status.NOT_STARTED)
            demo_owned.update(owner=None)

            for user in demo_users:
                if delete:
                    user.delete()
                else:
                    user.is_active = False
                    user.set_unusable_password()
                    user.save(update_fields=["is_active", "password"])
            # Today's point counted the data that just went; the dashboard trend ends on it. Where nothing of the demo
            # was found, or it was retired already, nothing went and the trend is left as it is.
            if recompute:
                record_today(force=True)
            # The record bootstrap_demo checks before seeding. ip_address stays empty, so the seeded-row match above
            # can never delete it on a later run.
            if retiring:
                AuditLog.objects.create(
                    user=None, action=RETIRED_ACTION, object_type=RETIRED_OBJECT_TYPE,
                    detail="Demo dataset retired with remove_demo_data; it is not seeded here again.",
                )

        would = "that would be " if dry else ""
        action = "deleted" if delete else "deactivated"
        self.stdout.write(f"Demo users {would}{action}: "
                          f"{', '.join(u.username for u in demo_users) or 'none'}")
        for label, n in counts:
            self.stdout.write(f"{label} {would}deleted: {n}")
        if programme == PROGRAMME_READ:
            self.stdout.write(f"Seeded control statuses {would}reset to Not started: {len(reset)}")
        elif programme == PROGRAMME_UNREADABLE:
            self.stdout.write(self.style.WARNING(
                f"Seeded control statuses: not reset. {UNREADABLE_BECAUSE[unreadable]} The "
                f"statuses it set can no longer be told apart from yours. Review the statuses "
                f"on the Controls page."))
        else:
            self.stdout.write(self.style.WARNING(
                f"Seeded control statuses: not reset. An earlier release retired this demo and "
                f"left {len(reset)} controls with the status the demo gave them, and changes "
                f"made since cannot be told apart from those. Review the statuses on the "
                f"Controls page."))
        self.stdout.write(f"Controls owned by a demo account {would}left with no owner: {owned_count}")
        if not demo_seen:
            self.stdout.write("No sign that the demo dataset was loaded in this workspace: no sample row was touched.")
        if dry:
            if recompute:
                self.stdout.write("Today's readiness point would be recorded again without the demo data.")
            self.stdout.write(self.style.WARNING("Dry run: nothing changed."))
            return
        if recompute:
            self.stdout.write("Today's readiness point recorded again without the demo data.")
        self.stdout.write(self.style.SUCCESS(
            "Demo data removed. The demo accounts can no longer sign in, and later boots "
            "with SEED_DEMO_DATA=true leave this workspace alone."
        ))

    @staticmethod
    def _demo_history(demo_to_retire):
        """The demo's readiness points dated before today; after a ``bootstrap_demo --force`` revival only those from
        the revival's day on, and none on a later run or where no demo was ever seeded."""
        from analytics.models import ReadinessSnapshot
        from audit.models import AuditLog

        if not demo_to_retire:
            return ReadinessSnapshot.objects.none()
        history = ReadinessSnapshot.objects.filter(date__lt=timezone.localdate())
        revived = (AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE, action=REVIVED_ACTION)
                   .order_by("-pk").values_list("timestamp", flat=True).first())
        if revived is not None:
            # Seeded again with --force: the points from before that are the operator's own history.
            history = history.filter(date__gte=timezone.localdate(revived))
        return history

    @staticmethod
    def _programme_resets(demo_by_pk, retiring, demo_seen):
        """Returns ``(state, pks, why)``; ``why`` keys UNREADABLE_BECAUSE. PROGRAMME_LEFT_BEHIND is reported and never
        reset, because the operator's own work since then looks the same."""
        from audit.models import AuditLog
        from compliance.models import Control

        record = AuditLog.objects.filter(object_type=PROGRAMME_OBJECT_TYPE).order_by("-pk").first()
        if record is None and not demo_seen:
            return PROGRAMME_READ, [], None
        if record is not None:
            retired_since = AuditLog.objects.filter(
                object_type=RETIRED_OBJECT_TYPE, action=RETIRED_ACTION, pk__gt=record.pk).exists()
            if retired_since:
                return PROGRAMME_READ, [], None
            mark = PROGRAMME_MARK.fullmatch(record.object_id)
            walk = (list(Control.objects.filter(pk__lte=int(mark.group(1))).order_by(*PROGRAMME_ORDER))
                    if mark else [])
            # The fingerprint proves the walked controls are all there in the same order; later ones have larger ids.
            if mark and programme_fingerprint(c.pk for c in walk) == mark.group(2):
                return PROGRAMME_READ, _still_as_seeded(walk), None
            why = "library" if mark else "record"
        else:
            # An older release kept no record: the whole register, in the order the programme walks it.
            walk = list(Control.objects.order_by(*PROGRAMME_ORDER))
            if not demo_by_pk:
                why = "accounts"
            elif not any(c.owner_id in demo_by_pk for c in walk):
                why = "owners"
            else:
                why = "moved"
        if not _owners_where_the_programme_put_them(walk, demo_by_pk):
            if record is None and not retiring:
                return PROGRAMME_READ, [], None
            return PROGRAMME_UNREADABLE, [], why
        if record is None and not retiring:
            left = _still_as_seeded(walk)
            return (PROGRAMME_LEFT_BEHIND, left, None) if left else (PROGRAMME_READ, [], None)
        return PROGRAMME_READ, _still_as_seeded(walk), None
