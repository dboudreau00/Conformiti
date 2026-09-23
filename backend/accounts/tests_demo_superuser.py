"""The demo seed's advice on a first boot that also creates DJANGO_SUPERUSER_*.

backend/entrypoint.sh seeds the demo before it creates the DJANGO_SUPERUSER_*
account, so the seed used to tell the operator to run createsuperuser a few
log lines before the container made that account itself, and the boot banner
after it then said only remove_demo_data. The entrypoint now passes
--superuser-follows in that case, and the seed leaves the advice to the banner.
"""
import os
import shutil
import subprocess
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock, skipUnless

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from accounts import tenancy
from accounts.management.commands.bootstrap_demo import own_administrator_present
from testutils import PASSWORD, make_user

ENTRYPOINT = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")


class SeedAdviceTests(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"DEMO_PASSWORD": "DemoPass123!"})
        env.start()
        self.addCleanup(env.stop)
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        media_root = override_settings(MEDIA_ROOT=media.name)
        media_root.enable()
        self.addCleanup(media_root.disable)

    @staticmethod
    def seed(*args):
        out = StringIO()
        call_command("bootstrap_demo", *args, stdout=out)
        return out.getvalue()

    def test_with_the_superuser_next_the_seed_does_not_name_createsuperuser(self):
        out = self.seed("--superuser-follows")
        self.assertIn("Sign in as  admin", out)
        self.assertNotIn("createsuperuser", out)
        self.assertIn("boot banner", out)

        # What the entrypoint does next. After it, the banner's question (the
        # same function) has the answer that makes it say remove_demo_data only.
        with tenancy.unscoped(), mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
            call_command("createsuperuser", interactive=False, username="operator",
                         email="operator@test.local", verbosity=0)
        self.assertTrue(own_administrator_present(tenancy.default_workspace()))

    def test_the_flag_changes_nothing_once_an_own_administrator_exists(self):
        make_user("root", superuser=True)
        out = self.seed("--superuser-follows")
        self.assertIn("Retire these accounts before real use: manage.py remove_demo_data", out)
        self.assertNotIn("boot banner", out)

    def test_without_the_flag_createsuperuser_still_comes_first(self):
        """By hand, or on a boot with no DJANGO_SUPERUSER_*: nothing else will
        make the account, so the advice names it."""
        out = self.seed()
        self.assertLess(out.index("manage.py createsuperuser"), out.index("manage.py remove_demo_data"))


def _posix_bash():
    """A bash that runs a script in this process's environment, or None.
    On Windows, System32's bash.exe starts WSL instead."""
    found = shutil.which("bash")
    if found and os.name == "nt" and "system32" in found.lower():
        return None
    return found


class EntrypointSeedFlagTests(SimpleTestCase):
    def test_the_seed_runs_before_the_superuser_step(self):
        """The order that makes the flag necessary."""
        self.assertLess(ENTRYPOINT.index("python manage.py bootstrap_demo"),
                        ENTRYPOINT.index("python manage.py createsuperuser --noinput"))

    @skipUnless(_posix_bash(), "needs bash")
    def test_the_flag_is_passed_exactly_when_the_superuser_step_will_run(self):
        """The SEED_DEMO_DATA branch run in bash, with ``python`` replaced by a
        stub that prints its arguments."""
        block = ENTRYPOINT[ENTRYPOINT.index('case "${SEED_DEMO_DATA'):]
        block = block[:block.index("\nesac\n") + len("\nesac\n")]
        script = ("set -euo pipefail\n"
                  "log() { :; }\n"
                  "python() { printf '%s\\n' \"$*\"; }\n"
                  f"{block}")
        base = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_SUPERUSER_")}
        flag = "manage.py bootstrap_demo --superuser-follows"
        cases = [
            ({"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_PASSWORD": "x"}, flag),
            ({"DJANGO_SUPERUSER_USERNAME": "root"}, "manage.py bootstrap_demo"),
            ({"DJANGO_SUPERUSER_PASSWORD": "x"}, "manage.py bootstrap_demo"),
            ({"DJANGO_SUPERUSER_USERNAME": "", "DJANGO_SUPERUSER_PASSWORD": "x"},
             "manage.py bootstrap_demo"),
            ({}, "manage.py bootstrap_demo"),
        ]
        for env, expected in cases:
            with self.subTest(env=env):
                r = subprocess.run([_posix_bash(), "-c", script],
                                   env={**base, "SEED_DEMO_DATA": "true", **env},
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), expected, r.stderr)
        r = subprocess.run([_posix_bash(), "-c", script],
                           env={**base, "SEED_DEMO_DATA": "false"},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "", "no seed, no flag")
