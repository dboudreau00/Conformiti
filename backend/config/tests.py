"""Deployment-level behaviour: secret-key handling, demo-data retirement,
the full seed + demo bootstrap, and integration hardening."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from testutils import APITestBase, make_user

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
                self.assertEqual(Document.objects.count(), 7)
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
                self.assertEqual(Document.objects.count(), 7)
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
                # the libraries survive
                from compliance.models import Control
                self.assertEqual(Control.objects.count(), 217)
                call_command("remove_demo_data", "--delete", verbosity=0)
                self.assertFalse(User.objects.filter(username="mia").exists())

