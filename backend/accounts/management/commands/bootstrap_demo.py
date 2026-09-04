"""
Populate a demo dataset so the dashboard is immediately useful.

Run AFTER seeding frameworks and folders:

    python manage.py seed_frameworks --with-folders
    python manage.py bootstrap_demo

Creates:
  * admin (superuser) + one user per built-in role
  * example folder permissions (RBAC demonstration)
  * sample documents with varied review dates (upcoming, due soon, overdue)
  * a couple of audit-milestone calendar events
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import Role
from calendar_app.models import CalendarEvent
from compliance.models import Control
from documents.models import VIEW, EDIT, Document, Folder, FolderPermission

User = get_user_model()

DEMO_USERS = [
    ("admin", "Ada", "Admin", "Administrator", True),
    ("mia", "Mia", "Manager", "Compliance Manager", False),
    ("owen", "Owen", "Owner", "Control Owner", False),
    ("aria", "Aria", "Auditor", "Auditor", False),
    ("val", "Val", "Viewer", "Viewer", False),
]

# The seeded access review is named for the quarter it was created in, so both
# the seeder and remove_demo_data identify it by shape rather than by a literal.
ACCESS_REVIEW_PATTERN = r"^Q[1-4] [0-9]{4} access review$"

# The seeded evidence package, matched by name in both directions.
DEMO_PACKAGE_NAME = "SOC 2 Type II fieldwork"

# (control_id, doc name, cadence, review offset in days from today)
SAMPLE_DOCS = [
    ("CC6.1", "Access Control Policy", "annual", 45),
    ("CC6.2", "User Access Provisioning Procedure", "annual", 6),      # due soon
    ("CC7.4", "Incident Response Plan", "semiannual", -3),             # overdue
    ("A.5.1", "Information Security Policy", "annual", 20),
    ("A.8.13", "Backup and Restore Procedure", "quarterly", 12),
    ("1.3", "Network Segmentation Standard", "annual", 90),
    ("12.1", "PCI Information Security Policy", "annual", 1),          # due tomorrow
]


class Command(BaseCommand):
    help = "Create demo users, permissions, documents and calendar events."

    def handle(self, *args, **opts):
        self._users()
        self._permissions()
        self._control_program()
        self._documents()
        self._evidence()
        self._risks()
        self._events()
        self._governance()
        self._access_review()
        self._evidence_package()
        self._audit()
        self._history()
        self.stdout.write(self.style.SUCCESS(
            "Demo data ready. Log in as admin / DemoPass123!"
        ))

    def _users(self):
        for username, first, last, role_name, is_super in DEMO_USERS:
            role = Role.objects.filter(name=role_name).first()
            user, created = User.objects.get_or_create(
                username=username,
                defaults=dict(
                    first_name=first, last_name=last,
                    email=f"{username}@example.com", role=role,
                    is_staff=is_super, is_superuser=is_super, job_title=role_name,
                ),
            )
            if created:
                user.set_password("DemoPass123!")
                user.save()
        self.stdout.write(f"  Users: {User.objects.count()}")

    def _permissions(self):
        """Give the Control Owner edit on the SOC 2 CC6 folder and the Auditor
        view on the ISO 27001 root -- a concrete RBAC example."""
        owner_role = Role.objects.filter(name="Control Owner").first()
        auditor_role = Role.objects.filter(name="Auditor").first()

        cc6 = Folder.objects.filter(name__startswith="CC6 -").first()
        if cc6 and owner_role:
            FolderPermission.objects.get_or_create(
                folder=cc6, role=owner_role, user=None, access_level=EDIT
            )
        iso_root = Folder.objects.filter(is_framework_root=True,
                                         name__icontains="27001").first()
        if iso_root and auditor_role:
            FolderPermission.objects.get_or_create(
                folder=iso_root, role=auditor_role, user=None, access_level=VIEW
            )
        self.stdout.write(f"  Folder permissions: {FolderPermission.objects.count()}")

    def _documents(self):
        owner = User.objects.filter(username="owen").first()
        today = timezone.now().date()
        made = 0
        for control_id, name, cadence, offset in SAMPLE_DOCS:
            control = Control.objects.filter(control_id=control_id).first()
            folder = Folder.objects.filter(control=control).first() if control else None
            if not folder:
                continue
            if Document.objects.filter(name=name, folder=folder).exists():
                continue
            review_date = today + timedelta(days=offset)
            # Work backwards so last_reviewed + cadence lands on review_date.
            months = Document.CADENCE_MONTHS.get(cadence, 12)
            last_reviewed = review_date - timedelta(days=months * 30)
            doc = Document(
                folder=folder, control=control, name=name, owner=owner,
                created_by=owner, review_cadence=cadence,
                last_reviewed=last_reviewed,
                status=Document.Status.APPROVED,
                description=f"Sample {name} for {control_id}.",
            )
            doc.file.save(f"{name}.txt",
                          ContentFile(f"{name}\nControl: {control_id}\n(demo file)\n"),
                          save=False)
            doc.next_review_date = review_date
            doc.save()
            made += 1
        self.stdout.write(f"  Sample documents created: {made}")

    def _evidence(self):
        """Cross-framework evidence links for the seeded documents, so the
        reverse mapping demos the 'one document satisfies many controls' story
        (each doc's primary control comes from its folder; these add the rest)."""
        from compliance.models import ControlEvidence

        mia = User.objects.filter(username="mia").first()
        LINKS = {
            "Access Control Policy": [("iso27001", "A.5.15"), ("pci_dss_v4", "7.1")],
            "User Access Provisioning Procedure": [("iso27001", "A.5.18")],
            "Incident Response Plan": [("iso27001", "A.5.24"), ("pci_dss_v4", "12.10")],
            "Information Security Policy": [("soc2", "CC5.3"), ("pci_dss_v4", "12.1")],
            "Backup and Restore Procedure": [("soc2", "A1.2")],
            "Network Segmentation Standard": [("soc2", "CC6.6")],
            "PCI Information Security Policy": [("iso27001", "A.5.1")],
        }
        made = 0
        for doc_name, targets in LINKS.items():
            doc = Document.objects.filter(name=doc_name).first()
            if not doc:
                continue
            # Also record the document's own primary control as an explicit link.
            if doc.control_id:
                _, created = ControlEvidence.objects.get_or_create(
                    control=doc.control, document=doc,
                    defaults={"linked_by": mia, "note": "Primary control for this document"},
                )
                made += 1 if created else 0
            for fw_key, control_id in targets:
                control = Control.objects.filter(
                    category__framework__key=fw_key, control_id=control_id
                ).first()
                if not control:
                    continue
                _, created = ControlEvidence.objects.get_or_create(
                    control=control, document=doc,
                    defaults={"linked_by": mia, "note": "Cross-framework mapping"},
                )
                made += 1 if created else 0
        self.stdout.write(f"  Evidence links created: {made}")

    def _risks(self):
        """A small, realistic risk register: one overdue, one mitigating with a
        Jira key, one vendor risk, one closed — so every state demos."""
        from governance.models import Risk, RiskNote

        mia = User.objects.filter(username="mia").first()
        owen = User.objects.filter(username="owen").first()
        today = timezone.now().date()

        def ctrl(fw, cid):
            return Control.objects.filter(
                category__framework__key=fw, control_id=cid
            ).first()

        seeds = [
            dict(title="MFA not enforced for contractor accounts",
                 risk_type=Risk.Type.CONTROL_GAP, status=Risk.Status.MITIGATING,
                 likelihood=4, impact=4, owner=owen, control=ctrl("soc2", "CC6.1"),
                 due_date=today + timedelta(days=21), jira_key="SEC-341",
                 mitigation_plan="Extend Okta MFA policy to the contractor IdP group; verify with access review.",
                 description="External contractors authenticate without MFA, bypassing the workforce policy.",
                 note=("mia", "Vendor confirmed SAML config change scheduled for next sprint.")),
            dict(title="Incident response plan review overdue",
                 risk_type=Risk.Type.CONTROL_GAP, status=Risk.Status.OPEN,
                 likelihood=3, impact=4, owner=owen, control=ctrl("soc2", "CC7.4"),
                 due_date=today - timedelta(days=7),
                 mitigation_plan="Schedule tabletop exercise; refresh contact tree; re-approve plan.",
                 description="The IR plan passed its annual review date; escalation contacts may be stale."),
            dict(title="Payment processor SOC 2 report expired",
                 risk_type=Risk.Type.VENDOR, status=Risk.Status.OPEN,
                 likelihood=2, impact=4, owner=mia,
                 due_date=today + timedelta(days=30),
                 mitigation_plan="Request the current Type II report and bridge letter from the vendor.",
                 description="The most recent SOC 2 report on file for the payment processor lapsed last quarter."),
            dict(title="Public-read ACL on legacy assets bucket",
                 risk_type=Risk.Type.PENTEST, status=Risk.Status.CLOSED,
                 likelihood=4, impact=5, owner=owen,
                 mitigation_plan="Bucket policy replaced with CloudFront OAC; public ACLs blocked account-wide.",
                 description="Pen test found a legacy S3 bucket with public-read ACL exposing old marketing assets.",
                 note=("owen", "Fixed and verified; account-level Block Public Access enabled."),
                 closed=True),
        ]
        made = 0
        for spec in seeds:
            note = spec.pop("note", None)
            closed = spec.pop("closed", False)
            risk, created = Risk.objects.get_or_create(
                title=spec["title"],
                defaults=dict(spec, created_by=mia,
                              closed_at=timezone.now() if closed else None),
            )
            if created:
                made += 1
                if note:
                    author = User.objects.filter(username=note[0]).first()
                    RiskNote.objects.create(risk=risk, author=author, text=note[1])
        self.stdout.write(f"  Risks created: {made}")

    def _events(self):
        today = timezone.now().date()
        for title, offset, etype in [
            ("SOC 2 Type II audit fieldwork", 60, CalendarEvent.Type.AUDIT),
            ("ISO 27001 surveillance audit", 120, CalendarEvent.Type.AUDIT),
            ("Quarterly access review", 14, CalendarEvent.Type.TASK),
        ]:
            # Keyed by title only: keying on the (moving) date created a new
            # copy every time the seeder ran on a later day.
            CalendarEvent.objects.get_or_create(
                title=title, defaults=dict(event_type=etype, date=today + timedelta(days=offset)),
            )
        self.stdout.write(f"  Calendar events: {CalendarEvent.objects.count()}")

    def _governance(self):
        """Seed meeting cadences and a champion group (idempotent)."""
        from datetime import date

        from governance.models import ChampionGroup, GroupMember, MeetingMinute, MeetingSeries

        mia = User.objects.filter(username="mia").first()
        owen = User.objects.filter(username="owen").first()
        val = User.objects.filter(username="val").first()
        year = date.today().year

        steering, _ = MeetingSeries.objects.get_or_create(
            name="Security Steering Committee",
            defaults={
                "description": "Quarterly leadership review of the security program.",
                "required_per_year": 4,
                "owner": mia,
            },
        )
        for month, title in [(1, "Q1 security steering"), (4, "Q2 security steering"),
                             (6, "Pre-audit steering session")]:
            MeetingMinute.objects.get_or_create(
                series=steering, date=date(year, month, 15),
                defaults={
                    "title": title,
                    "attendees": "Ada Admin, Mia Manager, Owen Owner",
                    "notes": "Reviewed control implementation progress and open risks.",
                },
            )

        risk, _ = MeetingSeries.objects.get_or_create(
            name="Risk Review",
            defaults={
                "description": "Semi-annual review of the risk register.",
                "required_per_year": 2,
                "owner": mia,
            },
        )
        MeetingMinute.objects.get_or_create(
            series=risk, date=date(year, 3, 20),
            defaults={
                "title": "H1 risk register review",
                "attendees": "Mia Manager, Owen Owner",
                "notes": "Re-scored top risks; two treatments assigned.",
            },
        )

        champs, _ = ChampionGroup.objects.get_or_create(
            name="Security Champions",
            defaults={
                "purpose": "Inter-departmental champions who carry security practices "
                           "into their own teams and surface risks early.",
                "owner": mia,
            },
        )
        if owen:
            GroupMember.objects.get_or_create(
                group=champs, user=owen, defaults={"department": "Engineering"},
            )
        if val:
            GroupMember.objects.get_or_create(
                group=champs, user=val, defaults={"department": "Operations"},
            )

    def _access_review(self):
        """Seed one in-flight access review (idempotent).

        Without this the User audit screen is empty on a fresh install, so the
        feature looks unimplemented and the screenshot in the README shows
        something the demo does not actually produce. Left part-decided on
        purpose: an open review with work still to do is what the screen is
        for.
        """
        from governance.models import AccessReview, AccessReviewItem
        from governance.views import _snapshot_items

        # Matched by pattern, not by exact name: the name carries the quarter it
        # was seeded in, so a later run must recognise an earlier quarter's
        # review as "already seeded" instead of stacking another one.
        if AccessReview.objects.filter(name__regex=ACCESS_REVIEW_PATTERN).exists():
            self.stdout.write("  Access review: already present, left alone")
            return
        today = timezone.localdate()
        name = f"Q{(today.month - 1) // 3 + 1} {today.year} access review"
        admin = User.objects.filter(username="admin").first()
        review = AccessReview.objects.create(name=name, created_by=admin)
        _snapshot_items(review)

        # Decide every row but the last, so the progress meter reads 4/5 and
        # the "1 decision left" prompt has something to point at.
        decisions = {
            "admin": (AccessReviewItem.Decision.KEEP, "Break-glass administrator; MFA enforced."),
            "aria": (AccessReviewItem.Decision.KEEP, "External auditor, read-only for the audit window."),
            "mia": (AccessReviewItem.Decision.KEEP, "Programme owner."),
            "owen": (AccessReviewItem.Decision.MODIFY, "Drop edit on PCI folders after the migration."),
        }
        decided = 0
        for item in review.items.all():
            choice = decisions.get(item.username)
            if not choice:
                continue
            item.decision, item.decision_notes = choice
            item.decided_by = admin
            item.decided_at = timezone.now()
            item.save(update_fields=["decision", "decision_notes", "decided_by", "decided_at"])
            decided += 1
        self.stdout.write(
            f"  Access review: '{name}' seeded ({decided}/{review.items.count()} decided)"
        )

    def _evidence_package(self):
        """Seal one evidence package and issue it to the demo auditor.

        Without this the auditor workspace is an empty screen on a fresh
        install, and the feature that most distinguishes this product looks
        unimplemented. Sealed and issued on purpose: a draft would not show
        the manifest digest, and an unissued package would not show what an
        external auditor actually sees.
        """
        from datetime import timedelta

        from attestations.bundle import GENERATOR, assign_paths, build_manifest
        from attestations.manifest import canonical_bytes, sha256_hex
        from attestations.models import EvidencePackage, PackageControl, PackageGrant
        from attestations.snapshot import pin_document, snapshot_control
        from compliance.models import ControlEvidence

        if EvidencePackage.objects.filter(name=DEMO_PACKAGE_NAME).exists():
            self.stdout.write("  Evidence package: already present, left alone")
            return

        admin = User.objects.filter(username="admin").first()
        mia = User.objects.filter(username="mia").first()
        aria = User.objects.filter(username="aria").first()
        links = list(
            ControlEvidence.objects.select_related(
                "control__category__framework", "document", "linked_by"
            ).order_by("control__control_id")
        )
        if not links:
            self.stdout.write("  Evidence package: no linked evidence yet, skipped")
            return

        today = timezone.localdate()
        package = EvidencePackage.objects.create(
            name=DEMO_PACKAGE_NAME,
            engagement=f"FY{today.year} Type II",
            audit_firm="Northgate Assurance LLP",
            assurance_type=EvidencePackage.Assurance.TYPE_II,
            period_start=today - timedelta(days=180),
            period_end=today,
            scope_note="Controls supporting the Security trust services criterion.",
            created_by=mia or admin,
            created_by_name=(mia or admin).get_full_name(),
        )

        seen = set()
        for link in links:
            control = link.control
            if control.pk in seen:
                continue
            seen.add(control.pk)
            row = snapshot_control(package, control, mia or admin)
            for evidence_link in control.evidence_links.select_related("document", "linked_by"):
                pin_document(row, evidence_link.document, mia or admin, link=evidence_link)

        package.assertion = (
            "Management asserts that the controls described in this package were "
            "designed and implemented as described, and that the evidence attached "
            "is complete and accurate as at the date of sealing."
        )
        now = timezone.now()
        package.asserted_by = package.sealed_by = mia or admin
        package.asserted_by_name = package.sealed_by_name = (mia or admin).get_full_name()
        package.asserted_at = package.sealed_at = now
        package.status = EvidencePackage.Status.SEALED
        package.generator = GENERATOR
        package.save()

        assign_paths(package)
        package.refresh_from_db()
        raw = canonical_bytes(build_manifest(package))
        package.manifest_json = raw.decode("utf-8")
        package.manifest_sha256 = sha256_hex(raw)
        package.manifest_version = 1
        package.manifest_algorithm = "sha256"
        package.save(update_fields=[
            "manifest_json", "manifest_sha256", "manifest_version", "manifest_algorithm",
        ])

        # One row already concluded, so the workpaper is not uniformly blank.
        first = package.controls.order_by("ordinal").first()
        if first:
            first.design_conclusion = PackageControl.Conclusion.NO_EXCEPTIONS
            first.auditor_note = "Policy reviewed; approval evidence inspected."
            first.concluded_by = aria
            first.concluded_by_name = aria.get_full_name() if aria else ""
            first.concluded_at = now
            first.save()

        if aria:
            PackageGrant.objects.create(
                package=package, user=aria,
                username=aria.get_username(), full_name=aria.get_full_name(),
                email=aria.email,
                granted_by=mia or admin,
                granted_by_name=(mia or admin).get_full_name(),
                expires_at=now + timedelta(days=45),
                note="Fieldwork access for the Type II engagement.",
            )
        self.stdout.write(
            f"  Evidence package: '{DEMO_PACKAGE_NAME}' sealed "
            f"({package.controls.count()} control(s), {package.evidence_count} item(s)) "
            f"and issued to aria"
        )

    def _control_program(self):
        """Give the control libraries a plausible programme state — a spread of
        statuses and owners — so readiness, coverage and the sidebar badges
        have something to show. Applied only while every control is still
        untouched, so it never overwrites an operator's real statuses."""
        if Control.objects.exclude(status=Control.Status.NOT_STARTED).exists() \
                or Control.objects.filter(owner__isnull=False).exists():
            self.stdout.write("  Control programme: already set, left alone")
            return
        owners = {
            0: User.objects.filter(username="owen").first(),
            2: User.objects.filter(username="mia").first(),
            4: User.objects.filter(username="aria").first(),
        }
        implemented, in_progress, na = {0, 3, 6, 9, 12, 15, 18}, {1, 5, 10, 14, 20}, {24}
        touched = 0
        for i, control in enumerate(Control.objects.order_by("category__framework__key", "category__order", "control_id")):
            r = i % 25
            if r in implemented:
                control.status = Control.Status.IMPLEMENTED
            elif r in in_progress:
                control.status = Control.Status.IN_PROGRESS
            elif r in na:
                control.status = Control.Status.NOT_APPLICABLE
            control.owner = owners.get(i % 5) if (i % 5) in owners and i % 3 != 1 else None
            control.save(update_fields=["status", "owner"])
            touched += 1
        self.stdout.write(f"  Control programme: statuses/owners set on {touched} controls")

    def _history(self):
        """Back-fill five monthly readiness points so the dashboard trend has a
        shape on day one, then record today. Demo-only: remove_demo_data drops
        every snapshot dated before the day it runs."""
        from dateutil.relativedelta import relativedelta

        from analytics.models import ReadinessSnapshot
        from analytics.snapshots import record_today

        today = timezone.localdate()
        if ReadinessSnapshot.objects.filter(date__lt=today).exists():
            record_today(force=True)
            return
        now = record_today(force=True)
        if now is None:
            return
        made = 0
        for k in range(5, 0, -1):
            day = (today.replace(day=1) - relativedelta(months=k)).replace(day=15)
            factor = 0.55 + 0.09 * (5 - k)
            ReadinessSnapshot.objects.get_or_create(date=day, defaults=dict(
                total_controls=now.total_controls, applicable=now.applicable,
                implemented=int(round(now.implemented * factor)),
                in_progress=int(round(now.in_progress * (1.25 - 0.05 * (5 - k)))),
                with_evidence=int(round(now.with_evidence * factor)),
                evidence_links=int(round(now.evidence_links * factor)),
                documents_overdue=0, risks_open=now.risks_open,
            ))
            made += 1
        self.stdout.write(f"  Readiness history: {made} monthly points + today ({now.pct}%)")

    def _audit(self):
        """A short, plausible audit history so the viewer isn't empty on first
        visit. Real entries accrue automatically as people use the app."""
        from datetime import timedelta

        from django.utils import timezone

        from audit.models import AuditLog

        if AuditLog.objects.exists():
            return
        User = get_user_model()
        by = {u.username: u for u in User.objects.all()}
        now = timezone.now()
        rows = [
            (by.get("admin"), "create", "users",      "6", "created account tess (Viewer)",            "10.0.0.4",  9),
            (by.get("mia"),   "update", "documents",  "1", "marked reviewed: Access Control Policy",   "10.0.0.11", 8),
            (by.get("owen"),  "create", "documents",  "8", "uploaded evidence: backup-restore-log.pdf","10.0.0.23", 7),
            (by.get("mia"),   "create", "risks",      "2", "opened risk: Laptop disk encryption gaps", "10.0.0.11", 6),
            (by.get("mia"),   "update", "risks",      "2", "status open -> mitigating",                "10.0.0.11", 5),
            (by.get("admin"), "update", "users",      "3", "role change: val -> Viewer",               "10.0.0.4",  4),
            (by.get("owen"),  "create", "control-evidence", "12", "linked doc 3 to CC6.1",             "10.0.0.23", 3),
            (by.get("mia"),   "create", "calendar",   "5", "scheduled: Q3 access review kickoff",      "10.0.0.11", 2),
            (by.get("admin"), "delete", "folder-permissions", "9", "revoked folder grant for val",     "10.0.0.4",  1),
        ]
        for user, action, otype, oid, detail, ip, days_ago in rows:
            entry = AuditLog.objects.create(
                user=user, action=action, object_type=otype,
                object_id=oid, detail=detail, ip_address=ip,
            )
            # auto_now_add ignores a provided timestamp; stagger via update()
            AuditLog.objects.filter(pk=entry.pk).update(timestamp=now - timedelta(days=days_ago, hours=3))
        self.stdout.write("  audit: seeded 9 sample log entries")
