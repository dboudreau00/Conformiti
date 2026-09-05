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

# The seeded vendors, matched by name in both directions.
DEMO_VENDOR_NAMES = ["Amazon Web Services", "Okta", "Stripe", "Brightline Security Ltd"]

# (control_id, doc name, cadence, review offset in days from today)
SAMPLE_DOCS = [
    ("CC6.1", "Access Control Policy", "annual", 45),
    ("CC6.2", "User Access Provisioning Procedure", "annual", 6),      # due soon
    ("CC7.4", "Incident Response Plan", "semiannual", -3),             # overdue
    ("A.5.1", "Information Security Policy", "annual", 20),
    ("A.8.13", "Backup and Restore Procedure", "quarterly", 12),
    ("1.3", "Network Segmentation Standard", "annual", 90),
    ("12.1", "PCI Information Security Policy", "annual", 1),          # due tomorrow
    ("A.8.8", "Penetration Test Report", "annual", 120),               # a real PDF
    ("A.7.2", "Data Centre Badge Reader Photo", "annual", 200),         # a real PNG
]


def _demo_pdf(title, subtitle):
    """A small, valid single-page PDF built by hand -- so the demo has one
    file the in-browser viewer renders natively, not just text."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = (
        f"BT /F1 22 Tf 72 720 Td ({esc(title)}) Tj "
        f"0 -30 Td /F1 12 Tf ({esc(subtitle)}) Tj "
        f"0 -40 Td /F1 11 Tf (Scope: external perimeter, customer portal and API.) Tj "
        f"0 -16 Td (Findings: 0 critical, 0 high, 2 medium, 3 low.) Tj "
        f"0 -16 Td (Medium findings remediated and retested within SLA.) Tj ET"
    ).encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def _demo_png(width=480, height=300):
    """A small RGB gradient PNG (stdlib only) standing in for a photo."""
    import struct
    import zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = bytearray()
    for y in range(height):
        rows.append(0)   # filter: none
        for x in range(width):
            band = 40 if (x // 24 + y // 24) % 2 else 0
            rows += bytes((60 + band + x * 150 // width, 90 + band + y * 120 // height, 140 + band))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


def sample_bytes(name, control_id):
    """(extension, bytes) for a seeded document: two real binaries, text otherwise."""
    if name == "Penetration Test Report":
        return ".pdf", _demo_pdf(name, "Brightline Security Ltd - external test, annual")
    if name == "Data Centre Badge Reader Photo":
        return ".png", _demo_png()
    return ".txt", f"{name}\nControl: {control_id}\n(demo file)\n".encode("utf-8")


class Command(BaseCommand):
    help = "Create demo users, permissions, documents and calendar events."

    def handle(self, *args, **opts):
        self._users()
        self._permissions()
        self._control_program()
        self._documents()
        self._evidence()
        self._risks()
        self._vendors()
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
            ext, payload = sample_bytes(name, control_id)
            doc.file.save(f"{name}{ext}", ContentFile(payload), save=False)
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
            "Penetration Test Report": [("pci_dss_v4", "11.4"), ("soc2", "CC7.1")],
            "Data Centre Badge Reader Photo": [("pci_dss_v4", "9.2")],
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

    def _vendors(self):
        """Four third parties in the states the register is built to show:
        a critical cloud provider with a full shared responsibility matrix, an
        identity provider whose SOC 2 report is about to lapse, a payment
        processor whose report already has (the seeded vendor risk points at
        it), and a freshly onboarded pen-test firm with no matrix yet -- which
        is what raises the onboarding prompt in the notification tray."""
        from compliance.models import Responsibility
        from governance.models import Risk
        from vendors.models import SharedResponsibility, Vendor, VendorAssessment

        mia = User.objects.filter(username="mia").first()
        owen = User.objects.filter(username="owen").first()
        val = User.objects.filter(username="val").first()
        today = timezone.localdate()

        def ctrl(fw, cid):
            return Control.objects.filter(category__framework__key=fw, control_id=cid).first()

        VENDORS = [
            dict(name="Amazon Web Services", category="Cloud hosting", website="https://aws.amazon.com",
                 tier="critical", data_handled="customer PII, cardholder data (tokenised)",
                 services="EC2, RDS, S3 and KMS in eu-west-1", owner=mia, review_cadence="annual",
                 last_reviewed=today - timedelta(days=200),
                 assessments=[
                     ("soc2_type2", "SOC 2 Type II (Spring report)", -120, 245, "satisfactory"),
                     ("pci_aoc", "PCI DSS 4.0 AOC — service provider", -90, 275, "satisfactory"),
                 ],
                 matrix=[
                     ("pci_dss_v4", "1.3", "shared",
                      "Edge network controls, DDoS protection and the physical boundary of every AWS region.",
                      "Security groups, network ACLs and VPC segmentation between the CDE and everything else."),
                     ("soc2", "CC6.6", "shared",
                      "Protection of the AWS global network and its perimeter.",
                      "Perimeter rules for our own workloads: WAF policy, ingress allow-lists, bastion access."),
                     ("soc2", "A1.2", "provider",
                      "Multi-AZ infrastructure redundancy and durability of managed services.", ""),
                     ("iso27001", "A.8.13", "shared",
                      "Snapshot and replication capability for RDS and S3.",
                      "Backup schedules, retention and quarterly restore tests of our data."),
                     ("pci_dss_v4", "12.1", "customer", "",
                      "Our information security policy governs how we use the platform; AWS has no part in it."),
                 ]),
            dict(name="Okta", category="Identity provider", website="https://www.okta.com",
                 tier="high", data_handled="workforce identities, authentication events",
                 services="Workforce Identity Cloud (SSO, MFA, lifecycle)", owner=owen, review_cadence="annual",
                 last_reviewed=today - timedelta(days=300),
                 assessments=[("soc2_type2", "SOC 2 Type II", -340, 25, "satisfactory")],   # expiring
                 matrix=[
                     ("soc2", "CC6.1", "shared",
                      "Authentication service, MFA factors and session management.",
                      "Which factors are required, who is enrolled, and the access policy per application."),
                     ("soc2", "CC6.2", "shared",
                      "Lifecycle APIs and SCIM provisioning.",
                      "Joiner/mover/leaver process and the approvals that drive it."),
                     ("iso27001", "A.5.15", "provider",
                      "Role-based access within the Okta tenant itself.", ""),
                     ("iso27001", "A.5.18", "shared",
                      "Provisioning and deprovisioning connectors.",
                      "Timely removal of leavers and periodic access reviews."),
                 ]),
            dict(name="Stripe", category="Payment processing", website="https://stripe.com",
                 tier="critical", data_handled="cardholder data (never touches our systems)",
                 services="Payments, Radar, Billing", owner=mia, review_cadence="annual",
                 last_reviewed=today - timedelta(days=380),
                 assessments=[
                     ("soc2_type2", "SOC 2 Type II", -420, -40, "satisfactory"),           # expired
                     ("pci_aoc", "PCI DSS Level 1 AOC", -60, 305, "satisfactory"),
                 ],
                 matrix=[
                     ("pci_dss_v4", "12.10", "shared",
                      "Incident response for the Stripe platform, including notification to merchants.",
                      "Our own IR plan for integration and account compromise."),
                     ("pci_dss_v4", "7.1", "customer", "",
                      "Who in our organisation may access the Stripe dashboard and API keys."),
                 ]),
            dict(name="Brightline Security Ltd", category="Penetration testing", website="https://brightline.example",
                 tier="low", data_handled="test findings only", services="Annual external penetration test",
                 owner=owen, review_cadence="annual", last_reviewed=None,
                 assessments=[("pentest", "External penetration test", -14, 351, "exceptions")],
                 matrix=[]),   # freshly onboarded: no matrix -> onboarding prompt
        ]
        made = 0
        for spec in VENDORS:
            assessments = spec.pop("assessments")
            matrix = spec.pop("matrix")
            vendor, created = Vendor.objects.get_or_create(
                name=spec["name"], defaults=dict(spec, created_by=mia))
            if not created:
                continue
            made += 1
            vendor.compute_next_review()
            vendor.save(update_fields=["next_review_date"])
            for kind, title, issued, expires, result in assessments:
                VendorAssessment.objects.create(
                    vendor=vendor, kind=kind, title=title, result=result, reviewed_by=mia,
                    issued_at=today + timedelta(days=issued),
                    expires_at=today + timedelta(days=expires),
                    findings="Two medium findings, both remediated within SLA." if result == "exceptions" else "",
                )
            for fw, cid, resp, provider, customer in matrix:
                control = ctrl(fw, cid)
                if control:
                    SharedResponsibility.objects.get_or_create(
                        vendor=vendor, control=control,
                        defaults=dict(responsibility=resp, provider_statement=provider,
                                      customer_statement=customer, updated_by=mia))

        stripe = Vendor.objects.filter(name="Stripe").first()
        if stripe:
            Risk.objects.filter(title="Payment processor SOC 2 report expired", vendor__isnull=True).update(vendor=stripe)

        # A few explicit RACI rows on top of what the register implies.
        okta = Vendor.objects.filter(name="Okta").first()
        for control, party, role, note in [
            (ctrl("soc2", "CC6.1"), mia, "accountable", "Programme owner for logical access"),
            (ctrl("soc2", "CC6.1"), owen, "responsible", "Runs the quarterly access review"),
            (ctrl("soc2", "CC6.1"), val, "informed", "Operations lead"),
            (ctrl("iso27001", "A.5.1"), mia, "accountable", ""),
            (ctrl("pci_dss_v4", "12.10"), owen, "responsible", "Incident commander"),
            (ctrl("pci_dss_v4", "12.10"), okta, "consulted", "Identity events feed the IR timeline"),
        ]:
            if control is None or party is None:
                continue
            key = {"vendor": party} if isinstance(party, Vendor) else {"user": party}
            Responsibility.objects.get_or_create(control=control, role=role, **key,
                                                 defaults={"note": note, "created_by": mia})
        self.stdout.write(f"  Vendors created: {made} (register now {Vendor.objects.count()})")

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

        # A population and three sampled items on the access-control row, so
        # the operating-effectiveness workpaper is not blank on a fresh install.
        # Listed before sealing, so they are part of the manifest.
        from attestations.models import PackageSample
        sampled = package.controls.filter(control_ref="CC6.2").first() \
            or package.controls.order_by("control_ref").first()
        if sampled:
            sampled.population_size = 42
            sampled.population_source = "Okta deprovisioning report, FY period"
            sampled.sampling_method = PackageControl.Sampling.RANDOM
            sampled.save(update_fields=["population_size", "population_source", "sampling_method"])
            artefact = sampled.evidence.order_by("pk").first()
            for identifier, ref in (("u-1042", "row 7"), ("u-1077", "row 19"), ("u-1113", "row 31")):
                PackageSample.objects.create(
                    package_control=sampled, identifier=identifier,
                    description="Leaver's access removed within one business day",
                    population_ref=f"{ref} of the export", evidence=artefact,
                    evidence_name=artefact.document_name if artefact else "",
                    selected_by=mia or admin,
                    selected_by_name=(mia or admin).get_full_name(), selected_at=timezone.now(),
                )

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
        # Two of the three sampled items already tested by the auditor: one
        # pass, one exception, one still open.
        if sampled and aria:
            results = {"u-1042": ("pass", ""),
                       "u-1077": ("fail", "Access removed 4 business days after termination (SLA: 1).")}
            for sample in sampled.samples.all():
                if sample.identifier in results:
                    sample.result, sample.exception_note = results[sample.identifier]
                    sample.tested_by, sample.tested_by_name, sample.tested_at = aria, aria.get_full_name(), now
                    sample.save(update_fields=["result", "exception_note", "tested_by", "tested_by_name", "tested_at"])
            sampled.sampling_note = "25 of 42 leavers selected at random from the deprovisioning report."
            sampled.save(update_fields=["sampling_note"])

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
