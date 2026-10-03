"""Regression tests for the defects the 0.9.5ma documentation audit found.
Each class names the documented promise the code must keep; tests marked
"Guard" cover behaviour that must not change."""
import os
import tempfile
from io import StringIO
from unittest import mock

from django.contrib import admin
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import models
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from accounts import oidc
from accounts.models import OidcIdentity, Role, User
from attestations.models import (
    EvidencePackage,
    PackageControl,
    PackageEvidence,
    PackageGrant,
)
from attestations.tests import ASSERTION, PackageTestBase
from documents.models import Document
from governance.models import AccessReview
from testutils import APITestBase, make_roles, make_user

DEMO_NAMES = ["admin", "mia", "owen", "aria", "val"]


def _admin_request(user):
    request = RequestFactory().get("/admin/")
    request.user = user
    return request


def _admin_client(user):
    c = Client()
    c.force_login(user)
    return c


class DemoPasswordPolicyTests(TestCase):
    """install-1-06: DEMO_PASSWORD is set on all five demo accounts, the
    superuser `admin` among them, so it must meet the password policy that
    every other password meets."""

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_root = override_settings(MEDIA_ROOT=media.name)
        media_root.enable()
        self.addCleanup(media_root.disable)
        call_command("seed_frameworks", "--with-folders", verbosity=0, stdout=StringIO())

    @staticmethod
    def boot(password):
        with mock.patch.dict(os.environ, {"DEMO_PASSWORD": password}):
            out = StringIO()
            call_command("bootstrap_demo", stdout=out)
            return out.getvalue()

    def test_a_weak_password_is_refused_before_any_account_exists(self):
        with self.assertRaises(CommandError) as caught:
            self.boot("admin")
        self.assertIn("password policy", str(caught.exception))
        self.assertIn("too short", str(caught.exception))
        # Checked first, so no account is left behind without a password.
        self.assertFalse(User.objects.filter(username__in=DEMO_NAMES).exists())

    def test_every_account_that_shares_it_is_checked(self):
        # Long and uncommon, but it is mia's address.
        with self.assertRaises(CommandError) as caught:
            self.boot("mia@example.com!")
        self.assertIn("too similar", str(caught.exception))

    def test_a_refresh_sets_no_password_and_checks_none(self):
        """Guard: a container that boots with the old, weak value keeps
        booting once the accounts exist, because nothing is set."""
        self.boot("Correct-Horse-Battery-9")
        out = self.boot("admin")
        self.assertIn("existing accounts kept their password", out)
        self.assertTrue(User.objects.get(username="admin").check_password("Correct-Horse-Battery-9"))


class RoleEditLastAdministratorTests(APITestBase):
    """G10: the API "will never leave the organisation without an active
    administrator", so role edits are guarded as well as user edits. Taking
    can_manage_users off a custom role must not leave the workspace with
    none."""

    def setUp(self):
        super().setUp()
        self.ops = Role.objects.create(name="Ops Admin", can_manage_users=True)
        self.boss = make_user("boss", self.ops)
        # ada, the only other administrator, is away.
        self.admin.is_active = False
        self.admin.save()

    def test_the_last_administrators_role_keeps_user_management(self):
        c = self.client_for(self.boss)
        r = c.patch(f"/api/roles/{self.ops.pk}/", {"can_manage_users": False}, format="json")
        self.assertEqual(r.status_code, 403, r.data)
        self.assertIn("no active administrator", str(r.data))
        self.ops.refresh_from_db()
        self.assertTrue(self.ops.can_manage_users)

    def test_another_administrator_lets_it_go(self):
        """Guard: the refusal is about the last administrator, nothing more."""
        make_user("second", self.roles["Administrator"])
        c = self.client_for(self.boss)
        r = c.patch(f"/api/roles/{self.ops.pk}/", {"can_manage_users": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.ops.refresh_from_db()
        self.assertFalse(self.ops.can_manage_users)


class AdminTakesNoFileTests(APITestBase):
    """XD-16: every upload is said to be size-capped, type-checked and
    scanned, so the Django admin must not store whatever it is sent or clear
    the scanner's quarantine."""

    FILE_MODELS = {"Document", "DocumentVersion", "FormTemplate", "MeetingMinute"}

    def test_no_admin_form_takes_a_file(self):
        request = _admin_request(self.admin)
        checked = set()
        for model, model_admin in admin.site._registry.items():
            admins = [(model, model_admin)] + [
                (inline.model, inline(model, admin.site)) for inline in model_admin.inlines]
            for target, target_admin in admins:
                files = [f.name for f in target._meta.get_fields()
                         if isinstance(f, models.FileField)]
                if not files:
                    continue
                checked.add(target.__name__)
                if target is model:
                    form = target_admin.get_form(request, None)
                else:
                    form = target_admin.get_formset(request, None).form
                for name in files:
                    self.assertNotIn(name, form.base_fields, f"{target.__name__}.{name}")
        self.assertTrue(self.FILE_MODELS <= checked, checked)

    def test_the_scan_verdict_is_not_the_admins_to_change(self):
        form = admin.site._registry[Document].get_form(_admin_request(self.admin), None)
        for name in ("scan_status", "scan_signature", "scanned_at", "quarantined_at"):
            self.assertNotIn(name, form.base_fields)

    def test_a_document_cannot_be_added_through_the_admin(self):
        c = _admin_client(self.admin)
        r = c.post("/admin/documents/document/add/", {
            "folder": self.tree.ctrl1.pk, "name": "probe",
            "file": SimpleUploadedFile("evil.html", b"<script>alert(1)</script>"),
            "status": "draft", "review_cadence": "annual", "version": 1,
        })
        self.assertEqual(r.status_code, 403)
        self.assertFalse(Document.objects.filter(name="probe").exists())


class CompletedAccessReviewTests(APITestBase):
    """R1-04: "A completed review is read-only evidence from that moment."
    The review itself, not only its rows, must refuse renaming, re-noting and
    deletion with every row."""

    def setUp(self):
        super().setUp()
        self.review = AccessReview.objects.create(
            name="Q3 review", notes="All kept.", created_by=self.admin,
            status=AccessReview.Status.COMPLETED, completed_at=timezone.now())

    def test_the_api_neither_edits_nor_deletes_it(self):
        c = self.client_for(self.admin)
        url = f"/api/access-reviews/{self.review.pk}/"
        self.assertEqual(c.patch(url, {"notes": "Rewritten."}, format="json").status_code, 400)
        self.assertEqual(c.delete(url).status_code, 400)
        self.review.refresh_from_db()
        self.assertEqual(self.review.notes, "All kept.")

    def test_the_django_admin_neither_edits_nor_deletes_it(self):
        model_admin = admin.site._registry[AccessReview]
        request = _admin_request(self.admin)
        self.assertFalse(model_admin.has_change_permission(request, self.review))
        self.assertFalse(model_admin.has_delete_permission(request, self.review))
        r = _admin_client(self.admin).post(
            f"/admin/governance/accessreview/{self.review.pk}/delete/", {"post": "yes"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(AccessReview.objects.filter(pk=self.review.pk).exists())

    def test_a_review_in_progress_can_still_be_discarded(self):
        """Guard."""
        draft = AccessReview.objects.create(name="Mistake", created_by=self.admin)
        r = self.client_for(self.admin).delete(f"/api/access-reviews/{draft.pk}/")
        self.assertEqual(r.status_code, 204)


class DemotedAuditorTests(PackageTestBase):
    """SEC-05: grants are "re-evaluated on every request, so deactivating or
    demoting the account closes it immediately". Demotion must close reads
    as well as conclusions."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        self.item = PackageEvidence.objects.get()

    def test_demoting_the_auditor_closes_the_package(self):
        c = self.client_for(self.auditor)
        self.assertEqual(len(c.get("/api/evidence-packages/").data["results"]), 1)
        self.auditor.role = self.roles["Viewer"]
        self.auditor.save()
        self.assertEqual(c.get("/api/evidence-packages/").data["results"], [])
        self.assertEqual(c.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 404)
        self.assertEqual(c.get(f"/api/package-evidence/{self.item.pk}/file/").status_code, 404)


class SealedBytesTests(PackageTestBase):
    """R2-03: "The package freezes: the assessed organisation can no longer
    change what the auditor is looking at." A new version after the seal must
    not reach the auditor through the package."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        self.item = PackageEvidence.objects.get()
        self.auditor_client = self.client_for(self.auditor)

    def new_version(self, content):
        r = self.manager_client.post(
            f"/api/documents/{self.doc.pk}/new_version/",
            {"file": SimpleUploadedFile("policy-v2.txt", content)}, format="multipart")
        self.assertEqual(r.status_code, 200, getattr(r, "data", r))

    def test_the_auditor_reads_the_sealed_bytes_after_a_new_version(self):
        self.new_version(b"rewritten after the seal")
        r = self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/file/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b"".join(r.streaming_content), b"policy bytes")

    def test_the_export_and_verify_agree_with_the_seal(self):
        import io
        import json
        import zipfile

        self.new_version(b"rewritten after the seal")
        r = self.client_for(self.auditor).get(
            f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["X-Conformiti-Integrity"], "ok")
        zf = zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content)))
        path = json.loads(zf.read("manifest.json"))["controls"][0]["evidence"][0]["path"]
        self.assertEqual(zf.read(path), b"policy bytes")
        v = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/verify/")
        self.assertTrue(v.data["ok"], v.data)

    def test_a_file_the_package_did_not_seal_is_refused_not_served(self):
        # Replaced outside new_version, so no archived copy holds the pin.
        self.doc.file.save("swapped.txt", ContentFile(b"not what was sealed"), save=True)
        r = self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/file/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            self.auditor_client.get(f"/api/package-evidence/{self.item.pk}/preview/").status_code,
            400)

    def test_a_draft_still_asks_for_a_refresh(self):
        """Guard: before the seal a new version is drift, as it always was."""
        draft = EvidencePackage.objects.create(name="Next year", created_by=self.manager)
        self.package = draft
        self.add_control()
        self.new_version(b"a newer policy")
        r = self.manager_client.post(f"/api/evidence-packages/{draft.pk}/seal/",
                                     {"assertion": ASSERTION}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(len(r.data["drifted"]), 1)


class PackagesReadOnlyInAdminTests(PackageTestBase):
    """R2-04: conclusions "nobody at the assessed organisation can edit", the
    digests the manifest is signed over and the grants must not be editable
    in the Django admin."""

    def test_the_admin_changes_no_part_of_a_package(self):
        self.add_control()
        self.seal()
        self.issue_to(self.auditor)
        request = _admin_request(self.admin)
        for model in (EvidencePackage, PackageControl, PackageEvidence, PackageGrant):
            model_admin = admin.site._registry[model]
            obj = model.objects.first()
            self.assertIsNotNone(obj, model.__name__)
            self.assertFalse(model_admin.has_add_permission(request), model.__name__)
            self.assertFalse(model_admin.has_change_permission(request, obj), model.__name__)
            self.assertFalse(model_admin.has_delete_permission(request, obj), model.__name__)
        row = PackageControl.objects.get()
        r = _admin_client(self.admin).post(
            f"/admin/attestations/packagecontrol/{row.pk}/change/",
            {"design_conclusion": "effective", "auditor_note": "Signed off."})
        self.assertEqual(r.status_code, 403)
        row.refresh_from_db()
        self.assertEqual(row.auditor_note, "")


class SsoIssuerSpellingTests(APITestBase):
    """install-1-13: link_oidc_identity stores the issuer without a trailing
    "/", so sign-in must treat both spellings as one issuer. Otherwise the
    documented pre-link never matches a provider whose issuer ends in one
    (Entra ID's SAML entity id is https://sts.windows.net/<tenant>/)."""

    ISSUER = "https://sts.windows.net/tenant-id/"

    def cfg(self):
        return oidc.Config(
            issuer=self.ISSUER, client_id="", client_secret="", scopes="", label="",
            redirect_uri="", allowed_domains=(), auto_provision=False,
            default_role="Viewer", link_by_email=False, require_verified_email=False)

    def test_a_hand_made_link_matches_an_issuer_ending_in_a_slash(self):
        call_command("link_oidc_identity", "val", "name-id-val", "--issuer", self.ISSUER,
                     stdout=StringIO())
        user, _how = oidc.resolve_user(
            {"iss": self.ISSUER, "sub": "name-id-val", "email": ""}, self.cfg())
        self.assertEqual(user, self.viewer)

    def test_one_identity_held_by_two_accounts_is_refused(self):
        OidcIdentity.objects.create(user=self.viewer, issuer=self.ISSUER.rstrip("/"),
                                    subject="shared")
        OidcIdentity.objects.create(user=self.owner, issuer=self.ISSUER, subject="shared")
        with self.assertRaises(oidc.OidcError):
            oidc.resolve_user({"iss": self.ISSUER, "sub": "shared", "email": ""}, self.cfg())

    def test_linking_looks_for_a_clash_under_both_spellings(self):
        OidcIdentity.objects.create(user=self.owner, issuer=self.ISSUER, subject="taken")
        with self.assertRaises(CommandError):
            call_command("link_oidc_identity", "val", "taken", "--issuer", self.ISSUER,
                         stdout=StringIO())


class EntrypointDemoPasswordTests(TestCase):
    """A refused DEMO_PASSWORD leaves the Docker boot running without the
    demo, as a refused DJANGO_SUPERUSER_PASSWORD does, rather than stopping
    it. The entrypoint knows the refusal by the command's own words."""

    def test_the_entrypoint_matches_the_refusal_the_command_raises(self):
        from pathlib import Path

        from accounts.management.commands.bootstrap_demo import check_demo_password

        source = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(
            encoding="utf-8")
        marker = "DEMO_PASSWORD does not meet the password policy"
        with self.assertRaises(CommandError) as caught:
            check_demo_password("admin")
        self.assertTrue(str(caught.exception).startswith(marker))
        self.assertIn(f'*"{marker}"*', source)


class ViewerRoleDescriptionTests(TestCase):
    """The built-in Viewer description must not say "Read-only access to
    granted folders". The role reads the programme-wide records as well and
    writes risk notes, so that wording would understate it in an access
    review."""

    def test_the_description_says_what_the_role_does(self):
        viewer = make_roles()["Viewer"]
        self.assertNotIn("Read-only", viewer.description)
        self.assertIn("risk", viewer.description)
