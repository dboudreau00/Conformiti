"""Deployment-level behaviour: secret-key handling, demo-data retirement,
the full seed + demo bootstrap, and integration hardening."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import MfaDevice
from config import fieldcrypto
from testutils import APITestBase, make_user


def _raw_secret(user):
    """The stored column, bypassing the decrypting descriptor."""
    return MfaDevice.objects.filter(user=user).values_list("secret", flat=True).first()

BACKEND = Path(__file__).resolve().parent.parent


def _run_check(env_overrides):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "POSTGRES_", "CACHE_URL"))}
    env.update(env_overrides)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "manage.py", "check"], cwd=BACKEND, env=env,
        capture_output=True, text=True, timeout=120,
    )


class SecretKeyBootTests(SimpleTestCase):
    def test_production_refuses_placeholder_key(self):
        r = _run_check({"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "change-me-to-a-long-random-string"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DJANGO_SECRET_KEY", r.stderr)
        r = _run_check({"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY": "tooshort"})
        self.assertNotEqual(r.returncode, 0)

    def test_production_generates_and_persists_a_key_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "nested" / "django_secret_key"
            env = {"DJANGO_DEBUG": "false", "DJANGO_SECRET_KEY_FILE": str(key_file),
                   "DJANGO_SECRET_KEY": "change-me-to-a-long-random-string", "EMAIL_PROVIDER": "console"}
            r = _run_check(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            first = key_file.read_text().strip()
            self.assertGreaterEqual(len(first), 64)
            r = _run_check(env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(key_file.read_text().strip(), first)  # stable across boots


class DemoDataTests(TestCase):
    def test_bootstrap_then_remove(self):
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        with tempfile.TemporaryDirectory() as media:
            from django.test import override_settings
            with override_settings(MEDIA_ROOT=media):
                call_command("bootstrap_demo", verbosity=0)
                User = get_user_model()
                self.assertTrue(User.objects.get(username="admin").check_password("DemoPass123!"))
                from documents.models import Document
                from governance.models import Risk
                self.assertEqual(Document.objects.count(), 9)   # 7 text + a PDF + a PNG
                self.assertEqual(Risk.objects.count(), 4)
                from analytics.models import ReadinessSnapshot
                from calendar_app.models import CalendarEvent
                from compliance.models import Control as _Control
                self.assertGreater(_Control.objects.filter(status="implemented").count(), 40)
                self.assertGreater(_Control.objects.filter(owner__isnull=False).count(), 60)
                self.assertEqual(ReadinessSnapshot.objects.count(), 6)
                self.assertEqual(CalendarEvent.objects.count(), 3)
                # health reports the demo accounts
                from config.health import demo_accounts_present
                self.assertTrue(demo_accounts_present())
                # idempotent — and it never clobbers a status an operator changed
                _Control.objects.filter(status="implemented").update(status="not_started")
                call_command("bootstrap_demo", verbosity=0)
                self.assertEqual(Document.objects.count(), 9)
                self.assertEqual(CalendarEvent.objects.count(), 3)
                self.assertEqual(ReadinessSnapshot.objects.count(), 6)
                self.assertEqual(_Control.objects.filter(status="implemented").count(), 0)

                # refuses to strand the install without an admin
                with self.assertRaises(CommandError):
                    call_command("remove_demo_data", verbosity=0)
                make_user("realadmin", superuser=True)
                call_command("remove_demo_data", verbosity=0)
                self.assertFalse(User.objects.get(username="admin").is_active)
                self.assertFalse(User.objects.get(username="mia").has_usable_password())
                self.assertEqual(Document.objects.count(), 0)
                self.assertEqual(Risk.objects.count(), 0)
                self.assertFalse(demo_accounts_present())
                self.assertEqual(ReadinessSnapshot.objects.count(), 1)  # only today's point survives
                from compliance.models import Responsibility
                from documents.models import FolderPermission
                from vendors.models import Vendor
                self.assertEqual(Vendor.objects.count(), 0)
                self.assertEqual(Responsibility.objects.count(), 0)
                self.assertFalse(FolderPermission.objects.filter(user__isnull=True).exists(),
                                 "the seeded role-wide grants are standing access; they must go")
                # the libraries survive
                from compliance.models import Control
                self.assertEqual(Control.objects.count(), 217)
                call_command("remove_demo_data", "--delete", verbosity=0)
                self.assertFalse(User.objects.filter(username="mia").exists())

    def test_a_superuser_with_no_workspace_counts_as_the_surviving_administrator(self):
        """The sequence the README documents: `createsuperuser`, then
        `remove_demo_data`. `createsuperuser` runs with no workspace active, so
        the account it makes belongs to none — and the guard, which runs inside
        one workspace, must still see it or the documented path dead-ends."""
        from accounts import tenancy

        call_command("seed_frameworks", "--with-folders", verbosity=0)
        with tempfile.TemporaryDirectory() as media:
            with override_settings(MEDIA_ROOT=media):
                call_command("bootstrap_demo", verbosity=0)
                User = get_user_model()
                platform = make_user("realadmin", superuser=True)
                # What createsuperuser leaves behind: no workspace at all.
                User.objects.filter(pk=platform.pk).update(workspace=None)
                with tenancy.unscoped():
                    self.assertIsNone(User.objects.get(pk=platform.pk).workspace_id)

                call_command("remove_demo_data", verbosity=0)  # must not raise
                self.assertFalse(User.objects.get(username="admin").is_active)

    def test_remove_still_finds_the_data_when_the_demo_accounts_are_already_gone(self):
        """An operator who deleted the demo users by hand first must not be
        left with the demo vendors, documents and RACI rows -- those rows
        lose their creator (SET_NULL) and used to slip through the match."""
        call_command("seed_frameworks", "--with-folders", verbosity=0)
        with tempfile.TemporaryDirectory() as media:
            from django.test import override_settings
            with override_settings(MEDIA_ROOT=media):
                call_command("bootstrap_demo", verbosity=0)
                from documents.models import Document
                from vendors.models import Vendor
                User = get_user_model()
                make_user("realadmin", superuser=True)
                User.objects.filter(username__in=["admin", "mia", "owen", "aria", "val"]).delete()
                self.assertGreater(Vendor.objects.count(), 0)
                call_command("remove_demo_data", verbosity=0)
                self.assertEqual(Vendor.objects.count(), 0)
                self.assertEqual(Document.objects.count(), 0)


# --------------------------------------------------------------------------- #
# Field encryption
# --------------------------------------------------------------------------- #
KEY_A = "test-key-alpha-000000000000000000000000"
KEY_B = "test-key-bravo-111111111111111111111111"


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A])
class FieldEncryptionTests(SimpleTestCase):
    """The primitive, independent of any model."""

    def setUp(self):
        self.aad = fieldcrypto.aad_for("accounts_mfadevice", "secret", 7)

    def test_roundtrip(self):
        env = fieldcrypto.encrypt("JBSWY3DPEHPK3PXP", self.aad)
        self.assertTrue(fieldcrypto.is_encrypted(env))
        self.assertEqual(fieldcrypto.decrypt(env, self.aad), "JBSWY3DPEHPK3PXP")

    def test_envelope_is_versioned_random_and_opaque(self):
        a = fieldcrypto.encrypt("same", self.aad)
        b = fieldcrypto.encrypt("same", self.aad)
        self.assertTrue(a.startswith("fc1$") and b.startswith("fc1$"))
        self.assertNotEqual(a, b, "a fresh nonce must be used per write")
        self.assertNotIn("same", a)
        self.assertNotIn(KEY_A, a, "the envelope must never carry key material")

    def test_aad_binds_the_ciphertext_to_the_row_and_column(self):
        env = fieldcrypto.encrypt("secret", self.aad)
        other_row = fieldcrypto.aad_for("accounts_mfadevice", "secret", 8)
        other_col = fieldcrypto.aad_for("accounts_mfadevice", "other", 7)
        other_table = fieldcrypto.aad_for("integrations_jiraintegration", "secret", 7)
        self.assertIsNone(fieldcrypto.decrypt(env, other_row))
        self.assertIsNone(fieldcrypto.decrypt(env, other_col))
        self.assertIsNone(fieldcrypto.decrypt(env, other_table))

    def test_tampering_is_detected(self):
        env = fieldcrypto.encrypt("secret", self.aad)
        prefix, kid, nonce, blob = env.split("$", 3)

        # Flip one bit of the ciphertext itself. Mutating the last base64
        # character is not enough: unpadded base64url leaves spare bits in the
        # final character, so some edits decode to identical bytes.
        raw = bytearray(fieldcrypto._unb64(blob))
        raw[0] ^= 0x01
        self.assertIsNone(fieldcrypto.decrypt(
            f"{prefix}${kid}${nonce}${fieldcrypto._b64(bytes(raw))}", self.aad))

        # A different nonce invalidates the tag too.
        other_nonce = fieldcrypto._b64(bytes(12))
        self.assertIsNone(fieldcrypto.decrypt(
            f"{prefix}${kid}${other_nonce}${blob}", self.aad))

        # And structurally broken envelopes fail closed rather than raising.
        for junk in ("fc1$xxxxxxxx$bad$bad", "fc1$onlytwo$parts", "fc1$"):
            self.assertIsNone(fieldcrypto.decrypt(junk, self.aad))

    def test_an_unknown_key_yields_none_rather_than_garbage(self):
        env = fieldcrypto.encrypt("secret", self.aad)
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B]):
            self.assertIsNone(fieldcrypto.decrypt(env, self.aad))

    def test_the_ring_decrypts_under_any_key_and_encrypts_under_the_newest(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B]):
            old = fieldcrypto.encrypt("secret", self.aad)
            old_id = fieldcrypto.envelope_key_id(old)
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A, KEY_B]):
            self.assertEqual(fieldcrypto.decrypt(old, self.aad), "secret")
            new = fieldcrypto.encrypt("secret", self.aad)
            self.assertEqual(fieldcrypto.envelope_key_id(new), fieldcrypto.key_ids()[0])
            self.assertNotEqual(fieldcrypto.envelope_key_id(new), old_id)

    def test_an_empty_ring_refuses_rather_than_storing_plaintext(self):
        with override_settings(FIELD_ENCRYPTION_KEYS=[]):
            with self.assertRaises(ImproperlyConfigured):
                fieldcrypto.encrypt("secret", self.aad)

    def test_legacy_plaintext_is_passed_through_on_read(self):
        self.assertEqual(fieldcrypto.decrypt("not-an-envelope", self.aad), "not-an-envelope")

    def test_ciphertext_length_covers_the_real_envelope(self):
        for n in (1, 16, 64, 255):
            env = fieldcrypto.encrypt("x" * n, self.aad)
            self.assertLessEqual(len(env), fieldcrypto.ciphertext_length(n))


class FieldKeyRingBootTests(SimpleTestCase):
    """How settings.py resolves the ring."""

    def test_an_explicit_key_wins_and_is_reported_as_such(self):
        r = _run_check({"DJANGO_FIELD_ENCRYPTION_KEY": KEY_A, "EMAIL_PROVIDER": "console"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_key_file_is_generated_and_persisted(self):
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "nested" / "field_key"
            env = {"DJANGO_FIELD_ENCRYPTION_KEY_FILE": str(key_file), "EMAIL_PROVIDER": "console"}
            self.assertEqual(_run_check(env).returncode, 0)
            first = key_file.read_text().strip()
            self.assertGreaterEqual(len(first), 32)
            self.assertEqual(_run_check(env).returncode, 0)
            self.assertEqual(key_file.read_text().strip(), first, "the key must be stable across boots")
            if os.name != "nt":
                self.assertEqual(oct(key_file.stat().st_mode)[-3:], "600")

    def test_a_placeholder_secret_key_is_never_used_to_derive_a_ring(self):
        """`dev-insecure-change-me` is published in this repository. Deriving a
        ring from it would make "encrypted at rest" a false claim, so settings
        must fall through to a generated key file instead."""
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "source.txt"
            code = (
                "import os, django; django.setup();"
                "from django.conf import settings;"
                f"open(r'{probe}', 'w').write(settings.FIELD_ENCRYPTION_KEY_SOURCE)"
            )
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("DJANGO_", "POSTGRES_", "CACHE_URL"))}
            env.update({"DJANGO_SETTINGS_MODULE": "config.settings",
                        "DJANGO_SECRET_KEY": "dev-insecure-change-me",
                        "EMAIL_PROVIDER": "console", "PYTHONIOENCODING": "utf-8"})
            r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(probe.read_text().strip(), "file")

    def test_a_strong_secret_key_may_derive_the_ring(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "source.txt"
            code = (
                "import os, django; django.setup();"
                "from django.conf import settings;"
                f"open(r'{probe}', 'w').write(settings.FIELD_ENCRYPTION_KEY_SOURCE)"
            )
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("DJANGO_", "POSTGRES_", "CACHE_URL"))}
            env.update({"DJANGO_SETTINGS_MODULE": "config.settings",
                        "DJANGO_SECRET_KEY": "x" * 60,
                        "EMAIL_PROVIDER": "console", "PYTHONIOENCODING": "utf-8"})
            r = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(probe.read_text().strip(), "secret-key")


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A])
class MigrationHelperTests(TestCase):
    """The migration path and the live field must agree byte for byte."""

    def test_encrypt_existing_rows_upgrades_legacy_plaintext(self):
        user = make_user("legacy")
        MfaDevice.objects.create(user=user, secret="JBSWY3DPEHPK3PXP")
        # Put the column back to plaintext, as a pre-0.3.0 database has it.
        MfaDevice.objects.filter(user=user).update(secret="JBSWY3DPEHPK3PXP")
        self.assertEqual(_raw_secret(user), "JBSWY3DPEHPK3PXP")

        moved = fieldcrypto.encrypt_existing_rows(
            connection, "accounts_mfadevice", "secret", "user_id")
        self.assertEqual(moved, 1)
        self.assertTrue(fieldcrypto.is_encrypted(_raw_secret(user)))
        # And the LIVE field reads it -- this is the AAD-divergence guard.
        self.assertEqual(MfaDevice.objects.get(user=user).secret, "JBSWY3DPEHPK3PXP")

    def test_encrypt_existing_rows_is_idempotent_and_reversible(self):
        user = make_user("legacy2")
        MfaDevice.objects.create(user=user, secret="SEEDSEEDSEEDSEED")
        MfaDevice.objects.filter(user=user).update(secret="SEEDSEEDSEEDSEED")

        fieldcrypto.encrypt_existing_rows(connection, "accounts_mfadevice", "secret", "user_id")
        once = _raw_secret(user)
        self.assertEqual(
            fieldcrypto.encrypt_existing_rows(connection, "accounts_mfadevice", "secret", "user_id"),
            0, "a second pass must not re-wrap")
        self.assertEqual(_raw_secret(user), once)

        fieldcrypto.decrypt_existing_rows(connection, "accounts_mfadevice", "secret", "user_id")
        self.assertEqual(_raw_secret(user), "SEEDSEEDSEEDSEED")


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY_A])
class FieldKeyRotationTests(TestCase):
    def test_rotation_moves_rows_onto_the_newest_key(self):
        user = make_user("rot")
        MfaDevice.objects.create(user=user, secret="ROTATEROTATEROTA")
        old_id = fieldcrypto.envelope_key_id(_raw_secret(user))

        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B, KEY_A]):
            call_command("rotate_field_keys", verbosity=0)
            new_id = fieldcrypto.envelope_key_id(_raw_secret(user))
            self.assertNotEqual(new_id, old_id)
            self.assertEqual(new_id, fieldcrypto.key_ids()[0])

        # The old key alone can no longer read it; the new one alone can.
        with override_settings(FIELD_ENCRYPTION_KEYS=[KEY_B]):
            self.assertEqual(MfaDevice.objects.get(user=user).secret, "ROTATEROTATEROTA")

    def test_rotation_never_double_encrypts(self):
        user = make_user("rot2")
        MfaDevice.objects.create(user=user, secret="ONCEONLYONCEONLY")
        call_command("rotate_field_keys", verbosity=0)
        call_command("rotate_field_keys", verbosity=0)
        self.assertEqual(_raw_secret(user).count("fc1$"), 1)
        self.assertEqual(MfaDevice.objects.get(user=user).secret, "ONCEONLYONCEONLY")

    def test_status_reports_rows_per_key_and_changes_nothing(self):
        user = make_user("rot3")
        MfaDevice.objects.create(user=user, secret="STATUSSTATUSSTAT")
        before = _raw_secret(user)
        out = StringIO()
        call_command("rotate_field_keys", "--status", stdout=out)
        self.assertIn(fieldcrypto.key_ids()[0], out.getvalue())
        self.assertEqual(_raw_secret(user), before)


class ValidatorPortabilityTests(SimpleTestCase):
    """tools/validate.py runs on a bare checkout, before pip install.

    The CI `validate` job installs nothing, so any module the validator imports
    must depend on the standard library alone. Check 17 imports
    documents.clamav; importing documents.scanning instead broke that job while
    passing everywhere else.
    """

    def test_the_scanner_client_imports_without_django(self):
        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "import documents.clamav as c;"
            "assert len(c.eicar_bytes()) == 68;"
            "assert c.parse_response('stream: OK') is None;"
            "print('ok')"
        ) % str(BACKEND)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("DJANGO_", "PYTHONPATH"))}
        # -S and an empty PYTHONPATH is as close to "nothing installed" as we
        # can get without a second interpreter; the real guard is that this
        # module imports no third-party name at all.
        env["PYTHONPATH"] = ""
        r = subprocess.run([sys.executable, "-c", code], env=env,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_scanner_client_names_no_third_party_import(self):
        source = (BACKEND / "documents" / "clamav.py").read_text(encoding="utf-8")
        for banned in ("django", "rest_framework", "from .", "from documents"):
            self.assertNotIn(banned, source,
                             f"documents/clamav.py must stay stdlib-only ({banned!r})")


class ReadinessConfigTests(SimpleTestCase):
    def test_malformed_bands_refuse_to_boot(self):
        """A single bad value would otherwise take the whole control register
        down on first read, not at boot."""
        for bad in ("90", "90,70,40", "40,40,90", "40,70,900"):
            r = _run_check({"READINESS_BANDS": bad, "EMAIL_PROVIDER": "console"})
            self.assertNotEqual(r.returncode, 0, f"READINESS_BANDS={bad} should be refused")
            self.assertIn("READINESS_BANDS", r.stderr)

    def test_the_default_bands_boot(self):
        self.assertEqual(_run_check({"EMAIL_PROVIDER": "console"}).returncode, 0)
