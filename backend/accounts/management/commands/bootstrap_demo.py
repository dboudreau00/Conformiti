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
        self._documents()
        self._evidence()
        self._risks()
        self._events()
        self._governance()
        self._audit()
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
            CalendarEvent.objects.get_or_create(
                title=title, date=today + timedelta(days=offset),
                defaults=dict(event_type=etype),
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
