"""Sealed packages, signing and the verifier: the 0.9.5oc review (SEA-01, 02, 05, 06, 07, 08, 09).

Grants are a separate access path from folder permissions (.claude/rules/packages.md): the tests here that touch
grants say so by asserting on PackageGrant rows and on what a grantee can read, never on FolderPermission."""
import hashlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric import ed25519
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import Workspace
from attestations import signing, verifier
from attestations.models import EvidencePackage, PackageGrant, SigningKey
from attestations.tests import PackageTestBase
from attestations.tests_signing import SigningKeyMixin
from audit.models import AuditLog
from testutils import make_user


def run_verifier(root, *args):
    return subprocess.run([sys.executable, "verify.py", *args, "."], cwd=root,
                          capture_output=True, text=True, timeout=300)


class ExportedBundleMixin:
    def export(self):
        r = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/export/")
        self.assertEqual(r.status_code, 200)
        return zipfile.ZipFile(io.BytesIO(b"".join(r.streaming_content) if r.streaming else r.content))

    @staticmethod
    def resign_file_list(root, key):
        """What a forger does after editing a member: rebuild SHA256SUMS to match, then sign it with a key of their
        own and ship that key as sums-key.pub."""
        sums = Path(root, "SHA256SUMS")
        rebuilt = []
        for line in sums.read_text().splitlines():
            if line.strip():
                _digest, name = line.split("  ", 1)
                rebuilt.append(f"{hashlib.sha256(Path(root, name).read_bytes()).hexdigest()}  {name}")
        body = ("\n".join(rebuilt) + "\n").encode()
        sums.write_bytes(body)
        Path(root, "SHA256SUMS.sig").write_text(signing.base64.b64encode(key.sign(body)).decode() + "\n")
        Path(root, "sums-key.pub").write_text(signing.public_pem(key.public_key()))


class SubstitutedSumsKeyTests(ExportedBundleMixin, PackageTestBase):
    """SEA-01: the key that signs SHA256SUMS travels inside the bundle, so a bundle re-signed with a forger's key must
    not end with a clean exit."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.manifest_fp = signing.fingerprint(self.package.signing_public_key)

    def test_a_bundle_whose_file_list_was_re_signed_with_another_key_fails(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            Path(tmp, "controls.csv").write_bytes(Path(tmp, "controls.csv").read_bytes() + b"\nforged,row\n")
            forger = ed25519.Ed25519PrivateKey.generate()
            self.resign_file_list(tmp, forger)
            forger_fp = signing.fingerprint(forger.public_key())
            for extra in ((), ("--trust", forger_fp), ("--trust", self.manifest_fp)):
                with self.subTest(trust=extra):
                    r = run_verifier(tmp, *extra)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertNotIn("OK:", r.stdout)
                    self.assertNotIn("Both signatures verify", r.stdout)

    def test_the_failure_names_both_keys_and_says_what_to_do(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            forger = ed25519.Ed25519PrivateKey.generate()
            self.resign_file_list(tmp, forger)
            out = run_verifier(tmp).stdout
        self.assertIn("SHA256SUMS IS SIGNED BY A DIFFERENT KEY", out)
        self.assertIn(self.manifest_fp[:16], out)
        forger_fp = signing.fingerprint(forger.public_key())
        self.assertIn(forger_fp, out)
        # An honest rotation needs both keys trusted, so the advice names both.
        self.assertIn(f"--trust sha256:{self.manifest_fp} --trust sha256:{forger_fp}", out)

    def test_an_honest_bundle_still_exits_0_and_does_not_claim_more_than_was_checked(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            r = run_verifier(tmp)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Both signatures verify", r.stdout)
        self.assertIn("whose key that is", r.stdout)
        self.assertNotIn("the bundle is theirs", r.stdout)
        self.assertIn(f"--trust {self.manifest_fp}", r.stdout)

    def test_trusting_the_published_key_passes_and_says_so(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            for argument in (["--trust", self.manifest_fp], ["--trust", "sha256:" + self.manifest_fp.upper()],
                             [f"--trust={self.manifest_fp}"], ["--trust", "signing-key.pub"]):
                with self.subTest(argument=argument):
                    r = run_verifier(tmp, *argument)
                    self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                    self.assertIn("named with --trust", r.stdout)

    def test_trusting_another_key_fails_even_when_the_bundle_is_consistent(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            stranger = signing.fingerprint(ed25519.Ed25519PrivateKey.generate().public_key())
            r = run_verifier(tmp, "--trust", stranger)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("not one of the keys given to --trust", r.stdout)

    def test_trust_with_a_stripped_signature_fails_even_with_allow_unsigned(self):
        zf = self.export()
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            Path(tmp, "SHA256SUMS.sig").unlink()
            sums = Path(tmp, "SHA256SUMS")
            sums.write_text("".join(line for line in sums.read_text().splitlines(keepends=True)
                                    if "SHA256SUMS.sig" not in line))
            r = run_verifier(tmp, "--allow-unsigned", "--trust", self.manifest_fp)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("carries no signature", r.stdout)

    def test_a_bad_trust_argument_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            zf = self.export()
            zf.extractall(tmp)
            for argument in (["--trust"], ["--trust", "not-a-fingerprint"], ["--trust", "ab" * 8]):
                with self.subTest(argument=argument):
                    r = run_verifier(tmp, *argument)
                    self.assertEqual(r.returncode, 2, r.stdout)
                    self.assertIn("usage: verify.py", r.stdout)

    def test_the_readme_tells_the_reader_about_trust(self):
        text = self.export().read("README.txt").decode()
        self.assertIn("--trust", text)


class RotatedKeyBundleTests(SigningKeyMixin, ExportedBundleMixin, PackageTestBase):
    """SEA-01: an honest export made after a key rotation carries two keys; it passes only when both are trusted."""

    def test_an_export_after_a_rotation_needs_both_keys_trusted(self):
        self.add_control()
        self.seal()
        sealed_fp = signing.fingerprint(self.package.signing_public_key)
        call_command("rotate_signing_key", stdout=io.StringIO())
        zf = self.export()
        sums_fp = verifier.fingerprint(self._sums_key(zf))
        self.assertNotEqual(sums_fp, sealed_fp)
        readme = zf.read("README.txt").decode()
        self.assertIn(sums_fp, readme)
        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            self.assertEqual(run_verifier(tmp).returncode, 1)
            self.assertEqual(run_verifier(tmp, "--trust", sums_fp).returncode, 1)
            both = run_verifier(tmp, "--trust", sums_fp, "--trust", sealed_fp)
        self.assertEqual(both.returncode, 0, both.stdout + both.stderr)

    @staticmethod
    def _sums_key(zf):
        return verifier.read_public_key(zf.read("sums-key.pub").decode())

    def test_a_sealed_package_still_verifies_in_app_after_the_rotation(self):
        self.add_control()
        self.seal()
        call_command("rotate_signing_key", stdout=io.StringIO())
        self.assertEqual(signing.signature_status(self.package), "valid")


class SymlinkTests(ExportedBundleMixin, PackageTestBase):
    """SEA-09: the standalone verifier hashes regular files only."""

    @staticmethod
    def tiny_bundle(root, members=("notes.txt",)):
        Path(root, "manifest.json").write_text("{}")
        lines = [f"{hashlib.sha256(b'{}').hexdigest()}  manifest.json"]
        for name in members:
            path = Path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists() and not path.is_symlink():
                path.write_text("hello")
            lines.append(f"{hashlib.sha256(b'hello').hexdigest()}  {name}")
        Path(root, "SHA256SUMS").write_text("\n".join(lines) + "\n")

    def test_a_plain_bundle_passes_the_regular_file_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.tiny_bundle(tmp, ("notes.txt", "evidence/a.txt"))
            self.assertTrue(verifier.plain_file(tmp, "notes.txt"))
            self.assertTrue(verifier.plain_file(tmp, "evidence/a.txt"))
            self.assertFalse(verifier.plain_file(tmp, "evidence"))
            self.assertFalse(verifier.plain_file(tmp, "missing.txt"))
            self.assertEqual(verifier.main(tmp, allow_unsigned=True), 0)

    def test_a_listed_member_that_is_a_link_is_refused(self):
        """Stands in for a real symlink, which Windows will not create without a privilege."""
        with tempfile.TemporaryDirectory() as tmp:
            self.tiny_bundle(tmp)
            real_lstat = os.lstat

            def lstat(path, *args, **kwargs):
                result = real_lstat(path, *args, **kwargs)
                if str(path).endswith("notes.txt"):
                    values = list(result)
                    values[0] = stat.S_IFLNK | 0o777
                    return os.stat_result(values)
                return result

            out = io.StringIO()
            with mock.patch.object(verifier.os, "lstat", side_effect=lstat), \
                    mock.patch("sys.stdout", out):
                code = verifier.main(tmp, allow_unsigned=True)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("refused, not a regular file: notes.txt", out.getvalue())

    def test_a_real_symlink_is_refused_where_the_platform_allows_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp, "outside.txt")
            outside.write_text("hello")
            bundle = Path(tmp, "bundle")
            bundle.mkdir()
            self.tiny_bundle(bundle)
            Path(bundle, "notes.txt").unlink()
            try:
                os.symlink(outside, Path(bundle, "notes.txt"))
                os.symlink(bundle, Path(bundle, "loop"), target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("this platform will not create symbolic links for this account")
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = verifier.main(str(bundle), allow_unsigned=True)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("refused, not a regular file: notes.txt", out.getvalue())
        self.assertIn("refused a symbolic link to a directory: loop", out.getvalue())

    def test_a_directory_named_in_the_file_list_is_refused_not_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.tiny_bundle(tmp)
            Path(tmp, "notes.txt").unlink()
            Path(tmp, "notes.txt").mkdir()
            out = io.StringIO()
            with mock.patch("sys.stdout", out):
                code = verifier.main(tmp, allow_unsigned=True)
        self.assertEqual(code, 1, out.getvalue())

    def test_a_link_where_manifest_sig_belongs_is_a_problem_not_a_missing_signature(self):
        self.add_control()
        self.seal()
        with tempfile.TemporaryDirectory() as tmp:
            self.export().extractall(tmp)
            real_lstat = os.lstat

            def lstat(path, *args, **kwargs):
                result = real_lstat(path, *args, **kwargs)
                if str(path).endswith("manifest.sig"):
                    values = list(result)
                    values[0] = stat.S_IFLNK | 0o777
                    return os.stat_result(values)
                return result

            out = io.StringIO()
            with mock.patch.object(verifier.os, "lstat", side_effect=lstat), mock.patch("sys.stdout", out):
                code = verifier.main(tmp)
        self.assertEqual(code, 1, out.getvalue())
        self.assertIn("manifest.sig is not a regular file", out.getvalue())

    def test_a_real_bundle_still_verifies(self):
        self.add_control()
        self.seal()
        with tempfile.TemporaryDirectory() as tmp:
            self.export().extractall(tmp)
            self.assertEqual(run_verifier(tmp).returncode, 0)


class ReusedSlugTests(SigningKeyMixin, PackageTestBase):
    """SEA-02: a workspace slug that another workspace signed under cannot be given to a second workspace."""

    def setUp(self):
        super().setUp()
        self.acme = Workspace.objects.create(name="Acme", slug="acme")
        with tenancy.scoped(self.acme):
            self.acme_key = signing.current_key_info(create=True)["public_key"]
            signing.register_key(self.acme_key)
        self.admin_client = self.client_for(self.admin)

    def test_a_key_registered_to_another_workspace_stays_with_it(self):
        other = Workspace.objects.create(name="Other", slug="other")
        retired_at = timezone.now()
        SigningKey.objects.filter(public_key=self.acme_key).update(retired_at=retired_at)
        with tenancy.scoped(other):
            with self.assertRaises(ImproperlyConfigured):
                signing.register_key(self.acme_key)
        row = SigningKey.objects.get(public_key=self.acme_key)
        self.assertEqual(row.workspace_id, self.acme.pk)
        self.assertIsNotNone(row.retired_at, "the refused call must not un-retire the row either")

    def test_the_old_slug_cannot_be_given_to_a_new_workspace(self):
        self.acme.slug = "acme-holdings"
        self.acme.save()
        r = self.admin_client.post("/api/workspaces/", {"name": "Acme again", "slug": "acme"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("slug", r.data)
        self.assertFalse(Workspace.objects.filter(name="Acme again").exists())

    def test_the_old_slug_cannot_be_taken_by_renaming_another_workspace(self):
        self.acme.slug = "acme-holdings"
        self.acme.save()
        other = Workspace.objects.create(name="Other", slug="other")
        r = self.admin_client.patch(f"/api/workspaces/{other.pk}/", {"slug": "acme"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        other.refresh_from_db()
        self.assertEqual(other.slug, "other")

    def test_a_workspace_may_take_its_own_old_slug_back_and_keep_renaming_otherwise(self):
        self.acme.slug = "acme-holdings"
        self.acme.save()
        self.acme.slug = "acme"
        self.acme.save()
        self.acme.name = "Acme Corp"
        self.acme.save()
        r = self.admin_client.post("/api/workspaces/", {"name": "Fresh", "slug": "fresh-slug"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_a_workspace_that_never_signed_frees_its_slug(self):
        """Only a slug that holds a registered key is held: the rule must not lock every old name."""
        quiet = Workspace.objects.create(name="Quiet", slug="quiet")
        quiet.slug = "quiet-renamed"
        quiet.save()
        r = self.admin_client.post("/api/workspaces/", {"name": "Quiet two", "slug": "quiet"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)

    def test_sealing_under_a_key_that_belongs_elsewhere_is_a_400_and_seals_nothing(self):
        self.add_control()
        with tenancy.scoped(tenancy.current()):
            mine = signing.current_key_info(create=True)["public_key"]
        SigningKey.objects.update_or_create(
            public_key=mine, defaults={"key_id": signing.key_id(mine), "workspace": self.acme})
        r = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/seal/", {
            "assertion": "Management asserts the controls were in place throughout the period stated."},
            format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("another workspace", str(r.data))
        self.package.refresh_from_db()
        self.assertEqual(self.package.status, EvidencePackage.Status.DRAFT)
        self.assertEqual(SigningKey.objects.get(public_key=mine).workspace_id, self.acme.pk)

    def test_packages_sealed_before_still_verify(self):
        self.add_control()
        self.seal()
        self.assertEqual(signing.signature_status(self.package), "valid")
        self.acme.slug = "acme-holdings"
        self.acme.save()
        self.assertEqual(signing.signature_status(self.package), "valid")


class RegisterKeyRaceTests(PackageTestBase):
    """SEA-08: a second seal that loses the race to register the same key reuses the winner's row."""

    def test_losing_the_insert_race_returns_the_winners_row(self):
        with tenancy.scoped(tenancy.current()):
            key = signing.current_key_info(create=True)["public_key"]
        winner = signing.register_key(key)
        from django.db.models.query import QuerySet

        real_get = QuerySet.get
        missed = []

        def get(queryset, *args, **kwargs):
            # The select that both requests ran before either inserted: it found nothing.
            if queryset.model is SigningKey and "public_key" in kwargs and not missed:
                missed.append(True)
                raise SigningKey.DoesNotExist()
            return real_get(queryset, *args, **kwargs)

        with mock.patch.object(QuerySet, "get", get):
            row = signing.register_key(key)
        self.assertTrue(missed, "the simulated race did not run")
        self.assertEqual(row.pk, winner.pk)
        self.assertEqual(SigningKey.objects.filter(public_key=key).count(), 1)

    def test_a_different_key_with_the_same_short_id_is_still_refused(self):
        with tenancy.scoped(tenancy.current()):
            key = signing.current_key_info(create=True)["public_key"]
        signing.register_key(key)
        other = signing.public_b64(ed25519.Ed25519PrivateKey.generate().public_key())
        with mock.patch.object(signing, "key_id", return_value=signing.key_id(key)):
            with self.assertRaises(ImproperlyConfigured):
                signing.register_key(other)
        self.assertEqual(SigningKey.objects.get(key_id=signing.key_id(key)).public_key, key)


class ReissueGrantTests(PackageTestBase):
    """SEA-05: issuing again to the same auditor renews the one grant."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.auditor_client = self.client_for(self.auditor)

    def grants(self):
        return PackageGrant.objects.filter(package=self.package, user=self.auditor)

    def test_issuing_again_after_a_revoke_restores_access_on_the_same_row(self):
        first = self.issue_to(self.auditor)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(self.manager_client.delete(f"/api/package-grants/{first.data['id']}/").status_code, 204)
        self.assertEqual(self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 404)

        again = self.issue_to(self.auditor, days=60)
        self.assertEqual(again.status_code, 201, again.data)
        self.assertEqual(again.data["id"], first.data["id"])
        self.assertTrue(again.data["is_live"])
        self.assertIsNone(again.data["revoked_at"])
        row = self.grants().get()
        self.assertIsNone(row.revoked_at)
        self.assertIsNone(row.revoked_by)
        self.assertEqual(self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 200)

    def test_issuing_again_after_expiry_renews_it(self):
        first = self.issue_to(self.auditor)
        self.grants().update(expires_at=timezone.now() - timezone.timedelta(days=1))
        self.assertEqual(self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 404)
        again = self.issue_to(self.auditor, days=20)
        self.assertEqual(again.status_code, 201, again.data)
        self.assertEqual(again.data["id"], first.data["id"])
        self.assertEqual(self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/").status_code, 200)

    def test_a_live_grant_can_be_extended(self):
        self.issue_to(self.auditor, days=10)
        before = self.grants().get().expires_at
        again = self.issue_to(self.auditor, days=90)
        self.assertEqual(again.status_code, 201, again.data)
        after = self.grants().get().expires_at
        self.assertGreater(after, before + timezone.timedelta(days=60))
        self.assertEqual(self.grants().count(), 1)

    def test_the_renewal_keeps_the_use_history_and_is_in_the_audit_trail(self):
        self.issue_to(self.auditor)
        self.grants().update(access_count=7)
        self.issue_to(self.auditor, days=40)
        self.assertEqual(self.grants().get().access_count, 7)
        self.assertTrue(AuditLog.objects.filter(
            object_type="evidence-packages", object_id=str(self.package.pk),
            detail__startswith=f"renewed package {self.package.pk} to {self.auditor.username}").exists())

    def test_the_ceiling_and_the_past_are_still_refused_on_a_renewal(self):
        self.issue_to(self.auditor)
        self.assertEqual(self.issue_to(self.auditor, days=9999).status_code, 400)
        self.assertEqual(self.issue_to(self.auditor, days=-1).status_code, 400)
        self.assertEqual(self.grants().count(), 1)

    def test_an_auditor_cannot_issue_or_renew_a_grant(self):
        self.issue_to(self.auditor)
        before = self.grants().get().expires_at
        r = self.auditor_client.post("/api/package-grants/", {
            "package": self.package.pk, "user": self.auditor.pk,
            "expires_at": (timezone.now() + timezone.timedelta(days=170)).isoformat()}, format="json")
        self.assertIn(r.status_code, (400, 403, 404), r.data)
        self.assertEqual(self.grants().get().expires_at, before)

    def test_a_package_of_another_workspace_cannot_be_issued_here(self):
        other = Workspace.objects.create(name="Other Org", slug="other-org")
        with tenancy.scoped(other):
            foreign = EvidencePackage.objects.create(
                name="Theirs", status=EvidencePackage.Status.SEALED, created_by=self.manager)
        r = self.manager_client.post("/api/package-grants/", {
            "package": foreign.pk, "user": self.auditor.pk}, format="json")
        self.assertIn(r.status_code, (400, 403, 404), r.data)
        with tenancy.unscoped():
            self.assertFalse(PackageGrant.objects.filter(package=foreign).exists())

    def test_two_requests_racing_to_issue_the_first_grant_end_as_one_row(self):
        """The loser's insert hits the unique pair; it must renew the winner's row, not answer 500."""
        from attestations.views import PackageGrantViewSet

        recipient = self.auditor
        expires = timezone.now() + timezone.timedelta(days=30)
        fields = dict(expires_at=expires, username=recipient.username, full_name="Aria", email="",
                      granted_by=self.manager, granted_by_name="Mia")

        winner = PackageGrant.objects.create(
            package=self.package, user=recipient, username=recipient.username,
            expires_at=timezone.now() + timezone.timedelta(days=5))

        class Racing:
            instance = None
            validated_data = {"note": "second"}

            def save(self, **kwargs):
                return PackageGrant.objects.create(package=recipient_package, user=recipient, **kwargs)

        recipient_package = self.package
        racing = Racing()
        from django.db.models.query import QuerySet

        real_first = QuerySet.first
        missed = []

        def first(queryset):
            # The lookup the loser ran before the winner's row was visible to it.
            if queryset.model is PackageGrant and not missed:
                missed.append(True)
                return None
            return real_first(queryset)

        with mock.patch.object(QuerySet, "first", first):
            grant, renewed = PackageGrantViewSet._issue_or_renew(racing, self.package, recipient, fields)
        self.assertTrue(missed)
        self.assertTrue(renewed)
        self.assertEqual(self.grants().count(), 1)
        self.assertEqual(grant.pk, winner.pk)
        self.assertEqual(self.grants().get().note, "second")
        self.assertEqual(racing.instance.pk, winner.pk)


class UnsealedKeyDirectoryTests(PackageTestBase):
    """SEA-06: a real slug that has sealed nothing answers like an unknown slug."""

    def test_a_real_slug_that_never_signed_matches_an_unknown_one(self):
        Workspace.objects.create(name="Beta Ltd", slug="beta-quiet")
        anon = APIClient()
        real = anon.get("/api/signing-keys/", {"workspace": "beta-quiet"})
        unknown = anon.get("/api/signing-keys/", {"workspace": "no-such-org"})
        self.assertEqual(real.status_code, unknown.status_code)
        self.assertEqual({**real.data, "workspace": None}, {**unknown.data, "workspace": None})
        self.assertFalse(real.data["enabled"])
        self.assertIsNone(real.data["current"])
        self.assertEqual(real.data["keys"], [])
        self.assertEqual(real.data["workspace"], "beta-quiet")

    def test_the_derived_public_key_of_an_organisation_that_never_sealed_is_not_published(self):
        quiet = Workspace.objects.create(name="Beta Ltd", slug="beta-quiet")
        with tenancy.scoped(quiet):
            derived = signing.current_key_info(create=True)["public_key"]
        self.assertNotIn(derived, str(APIClient().get("/api/signing-keys/", {"workspace": "beta-quiet"}).data))

    def test_an_organisation_that_has_sealed_still_publishes_its_keys(self):
        self.add_control()
        self.seal()
        body = APIClient().get("/api/signing-keys/", {"workspace": "default"}).data
        self.assertTrue(body["enabled"])
        self.assertEqual(body["current"]["key_id"], self.package.signing_key_id)
        self.assertEqual([k["key_id"] for k in body["keys"]], [self.package.signing_key_id])

    def test_a_single_organisation_before_its_first_seal_answers_with_nothing_published(self):
        body = APIClient().get("/api/signing-keys/").data
        self.assertIsNone(body["current"])
        self.assertEqual(body["keys"], [])


class SuccessorDisclosureTests(PackageTestBase):
    """SEA-07: a grantee is not told the name or status of a follow-on package they cannot open."""

    def setUp(self):
        super().setUp()
        self.add_control()
        self.seal()
        self.assertEqual(self.issue_to(self.auditor).status_code, 201)
        rolled = self.manager_client.post(f"/api/evidence-packages/{self.package.pk}/roll_forward/",
                                          {"name": "FY27 SOC 2 not issued"}, format="json")
        self.assertEqual(rolled.status_code, 201, rolled.data)
        self.draft_id = rolled.data["id"]
        self.auditor_client = self.client_for(self.auditor)

    def test_the_grantee_does_not_see_a_draft_successor(self):
        detail = self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["successors"], [])
        self.assertNotIn("FY27", str(detail.data))
        listing = self.auditor_client.get("/api/evidence-packages/").data
        rows = listing["results"] if isinstance(listing, dict) else listing
        self.assertEqual([r["successors"] for r in rows], [[]])
        self.assertEqual(self.auditor_client.get(f"/api/evidence-packages/{self.draft_id}/").status_code, 404)

    def test_the_organisation_still_sees_it(self):
        me = self.manager_client.get(f"/api/evidence-packages/{self.package.pk}/").data
        self.assertEqual([s["id"] for s in me["successors"]], [self.draft_id])
        self.assertEqual(me["successors"][0]["status"], "draft")

    def test_a_successor_the_grantee_may_read_is_listed(self):
        EvidencePackage.objects.filter(pk=self.draft_id).update(status=EvidencePackage.Status.SEALED)
        PackageGrant.objects.create(
            package_id=self.draft_id, user=self.auditor, username=self.auditor.username,
            expires_at=timezone.now() + timezone.timedelta(days=5))
        detail = self.auditor_client.get(f"/api/evidence-packages/{self.package.pk}/").data
        self.assertEqual([s["id"] for s in detail["successors"]], [self.draft_id])

    def test_a_grantee_of_the_successor_alone_is_not_told_about_the_draft_either(self):
        stranger = make_user("second-firm", self.roles["Auditor"])
        EvidencePackage.objects.filter(pk=self.draft_id).update(status=EvidencePackage.Status.SEALED)
        self.assertEqual(self.client_for(stranger).get(
            f"/api/evidence-packages/{self.package.pk}/").status_code, 404)
