"""
Retire the demo dataset before going live.

    python manage.py remove_demo_data            # deactivate demo users, delete sample content
    python manage.py remove_demo_data --delete   # also delete the demo user accounts
    python manage.py remove_demo_data --dry-run  # report only

The seeded accounts share one password generated at seed time, so they must
never survive into a real deployment. This command:

  * deactivates (or, with --delete, removes) the five demo users. It refuses
    to run until an administrator of your own exists (manage.py
    createsuperuser), so the installation is never left without one;
  * deletes the sample documents, risks, meeting series, champion group,
    calendar events, the seeded access review and the nine seeded audit-log
    rows, matching them by the exact names bootstrap_demo created;
  * undoes the demo's control programme. Every control a demo account owns
    is left with no owner, and every status the seeder set (Implemented, In
    progress, Not applicable) goes back to Not started unless someone has
    changed it since. The seeder records what it set in the audit log; for a
    demo seeded by an older release, which kept no record, its fixed pattern
    is read back instead, and only while the demo owners still sit exactly
    where it put them. When neither can be trusted no status changes, and the
    output says why;
  * drops the demo's readiness history (the back-filled points and those
    recorded since the seed, or since a `bootstrap_demo --force` seeded it
    again, all dated before today) and records today's point again from
    what is left;
  * leaves the framework/control libraries, folders and roles intact;
  * records the retirement in the audit log, which bootstrap_demo checks, so
    a container still started with SEED_DEMO_DATA=true does not seed the demo
    back into the workspace on its next boot.

Idempotent: safe to run again. A later run resets no status and deletes no
readiness history, because what changed after the retirement is yours.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts import tenancy
from accounts.management.commands.bootstrap_demo import (
    ACCESS_REVIEW_PATTERN, DEMO_PACKAGE_NAME, DEMO_USERS, DEMO_VENDOR_NAMES, PROGRAMME_MARK,
    PROGRAMME_OBJECT_TYPE, PROGRAMME_ORDER, RETIRED_ACTION, RETIRED_OBJECT_TYPE, REVIVED_ACTION,
    SAMPLE_DOCS, own_administrator_present, programme_fingerprint, programme_values,
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

# What _programme_resets found.
PROGRAMME_READ = "read"              # these controls still hold the demo's status
PROGRAMME_UNREADABLE = "unreadable"  # a live programme that cannot be read back
PROGRAMME_LEFT_BEHIND = "left"       # an older release retired the demo and kept its statuses

# Why a live programme cannot be read back: the warning names the cause that
# applies, so the operator is not sent looking for a change that never
# happened.
_OLDER_RELEASE = ("The demo was seeded by an older release, which kept no record of the "
                  "statuses it set; only the controls the demo accounts own show where it set "
                  "them, and ")
UNREADABLE_BECAUSE = {
    # The demo's record names the controls it walked, and they are not all
    # there in the same order.
    "library": ("Some controls that existed when the demo was seeded have since been removed "
                "from the control library or reordered in it."),
    # A record whose reference does not parse.
    "record": "The demo's record of the statuses it set cannot be read.",
    # No record, and nothing left to read the pattern back from.
    "accounts": _OLDER_RELEASE + "no demo account is left.",
    "owners": _OLDER_RELEASE + "no control is owned by a demo account any more.",
    # No record, and the demo owners sit where the pattern does not put them.
    # Without the record an added or removed control cannot be told apart
    # from owners changed by hand, so both are named.
    "moved": (_OLDER_RELEASE + "those are no longer the controls it gave them (controls were "
              "added or removed, or owners changed, since it was seeded)."),
}


def _owners_where_the_programme_put_them(walk, demo_by_pk):
    """True when at least one control in ``walk`` has a demo owner, and every
    one that has sits at a position where the programme made that account its
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
    """The pks of the controls in ``walk`` whose status is still the one the
    programme gave the position they hold. A status someone changed since
    differs from it and is left alone."""
    pks = []
    for i, control in enumerate(walk):
        status = programme_values(i)[0]
        if status is not None and control.status == status:
            pks.append(control.pk)
    return pks


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
        # Guard: the org must keep at least one active superuser/administrator
        # that is NOT one of the demo accounts. The test lives beside the
        # seeder (own_administrator_present), because the seeder's advice and
        # the container's boot banner ask it too: they tell an operator to
        # run createsuperuser first exactly when this would refuse.
        # `createsuperuser` now files its account in the first workspace that
        # is not archived (and accounts migration 0013 moved the ones older
        # releases left with none), but a superuser with no workspace at all
        # still counts: one detached by hand is still the administrator an
        # operator may have made before retiring the demo users. A role counts
        # the way User._cap reads it: an auditor role holds no capability,
        # whatever it stores.
        if demo_users and not own_administrator_present(workspace):
            raise CommandError(
                "Refusing: no administrator other than the demo accounts exists. "
                "Create your own first (python manage.py createsuperuser), then re-run."
            )
        # Whether this run is the one that retires the demo. A later run finds
        # its own record and leaves the statuses and the readiness history
        # alone: they are the operator's from the retirement on.
        retiring = not retirement_recorded()

        # "Created by a demo account" must also match rows whose creator was
        # already deleted (SET_NULL) by an earlier --delete run, or a second
        # run finds nothing and still reports success.
        demo_or_gone = Q(created_by__username__in=DEMO_USERNAMES) | Q(created_by__isnull=True)
        docs = Document.objects.filter(name__in=[d[1] for d in SAMPLE_DOCS]).filter(
            Q(owner__username="owen") | Q(owner__isnull=True))
        risks = Risk.objects.filter(title__in=DEMO_RISKS)
        series = MeetingSeries.objects.filter(name__in=DEMO_SERIES)
        groups = ChampionGroup.objects.filter(name__in=DEMO_GROUPS)
        events = CalendarEvent.objects.filter(title__in=DEMO_EVENTS)
        audit_rows = AuditLog.objects.filter(ip_address__in=DEMO_AUDIT_IPS, detail__regex=r"^[a-z]")
        # Only the seeded review, and only while a demo account owns it: a real
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
        from documents.models import FolderPermission
        from vendors.models import Vendor
        vendors = Vendor.objects.filter(name__in=DEMO_VENDOR_NAMES).filter(demo_or_gone)
        raci = Responsibility.objects.filter(demo_or_gone)
        # The two role-wide grants the seeder demonstrates RBAC with; left in
        # place they are standing access nobody asked for.
        seeded_grants = FolderPermission.objects.filter(user__isnull=True).filter(
            Q(role__name="Control Owner", folder__name__startswith="CC6 -", access_level="edit")
            | Q(role__name="Auditor", folder__is_framework_root=True, folder__name__icontains="27001",
                access_level="view"))
        # Counted before anything changes, then reported in the tense of what
        # happened: "would be" for a dry run, done for a real one.
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
        # Whether this workspace shows any sign of the demo at all. Run on an
        # installation that never seeded it, the command has no history and
        # no statuses of the demo's to take: they are all the operator's.
        demo_seen = bool(demo_users) or any(n for _, n in counts)
        history = self._demo_history(retiring and demo_seen)
        counts.append(("Seeded readiness history points", history.count()))

        # The control programme. Owners first: a control owned by an account
        # that can no longer sign in has no owner in any sense that matters.
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
            # Today's point counted the links, risks and statuses that just
            # went; the dashboard trend ends on it.
            record_today(force=True)
            # The record bootstrap_demo checks before seeding. Written once per
            # retirement: again only after a `bootstrap_demo --force` has seeded
            # the demo back since the last one. ip_address stays empty, so the
            # seeded-row match above can never delete it on a later run.
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
        if dry:
            self.stdout.write("Today's readiness point would be recorded again without the demo data.")
            self.stdout.write(self.style.WARNING("Dry run: nothing changed."))
            return
        self.stdout.write("Today's readiness point recorded again without the demo data.")
        self.stdout.write(self.style.SUCCESS(
            "Demo data removed. The demo accounts can no longer sign in, and later boots "
            "with SEED_DEMO_DATA=true leave this workspace alone."
        ))

    @staticmethod
    def _demo_history(demo_to_retire):
        """The readiness points the demo produced, all dated before today
        (today's is recorded again once the demo is gone): the back-filled
        months and every point recorded since the seed. After a `bootstrap_demo
        --force` revival, only the points from the revival's day on: the ones
        before it are the operator's, and the revival back-fills no months
        (bootstrap_demo._history), so none of the demo's sit before it. None
        on a later run, or where no demo was ever seeded."""
        from analytics.models import ReadinessSnapshot
        from audit.models import AuditLog

        if not demo_to_retire:
            return ReadinessSnapshot.objects.none()
        history = ReadinessSnapshot.objects.filter(date__lt=timezone.localdate())
        revived = (AuditLog.objects.filter(object_type=RETIRED_OBJECT_TYPE, action=REVIVED_ACTION)
                   .order_by("-pk").values_list("timestamp", flat=True).first())
        if revived is not None:
            # Seeded again with --force after an earlier retirement: the
            # points from before that are the operator's own history.
            history = history.filter(date__gte=timezone.localdate(revived))
        return history

    @staticmethod
    def _programme_resets(demo_by_pk, retiring, demo_seen):
        """What to do about the statuses the demo's control programme set.

        Returns (PROGRAMME_READ, pks, None) with the controls still holding
        the status the programme gave them (none once the programme was
        retired already, or where no demo was ever seeded);
        (PROGRAMME_UNREADABLE, [], why) for a live programme whose order can
        no longer be recovered, ``why`` keying UNREADABLE_BECAUSE; or
        (PROGRAMME_LEFT_BEHIND, pks, None) when an older release retired the
        demo without undoing it, which is reported and never reset: the
        operator's own work since then looks the same.
        """
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
            # The fingerprint proves the controls it walked are all there, in
            # the same order; controls added since have larger ids and fall
            # outside the walk.
            if mark and programme_fingerprint(c.pk for c in walk) == mark.group(2):
                return PROGRAMME_READ, _still_as_seeded(walk), None
            why = "library" if mark else "record"
        else:
            # Seeded by a release that kept no record: the whole register, in
            # the order the programme walks it.
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
