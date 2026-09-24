"""The first administrator, made the way every install guide says to.

The clean-install run found that ``manage.py createsuperuser`` produced an
account that could sign in to /admin/ and was then shown the sign-in form
again. The command runs with no workspace active, so the account belonged to
none, and the session's user lookup inside a request is pinned to the
workspace that request resolves to, which a row with no workspace never
matches. The same run found the command's "Bypass password validation"
answer let that account keep a password the installation refuses everywhere
else, and the users list paginating in no particular order.

The test runner keeps the Default workspace active for the whole suite, which
is why nothing caught the first of these: here the command runs with nothing
active, as it does on a real installation.
"""
import io
import os
import shlex
import shutil
import subprocess
import warnings
from pathlib import Path
from unittest import mock, skipUnless

from django.contrib.auth.management.commands import createsuperuser as stock
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import User
from testutils import PASSWORD, APITestBase, make_user


class _TTY:
    """What the interactive command checks before it prompts."""

    def isatty(self):
        return True


def _createsuperuser(username="root", password=PASSWORD, **options):
    """``createsuperuser --noinput`` as the entrypoint and the guides run it:
    nothing active, the password from the environment."""
    env = {"DJANGO_SUPERUSER_PASSWORD": password} if password is not None else {}
    with tenancy.unscoped(), mock.patch.dict(os.environ, env):
        call_command("createsuperuser", interactive=False, username=username,
                     email=f"{username}@test.local", verbosity=0, **options)


def _exists(username):
    with tenancy.unscoped():
        return User.objects.filter(username=username).exists()


class FirstAdministratorTests(APITestBase):
    def test_the_command_attaches_the_account_to_the_first_workspace(self):
        _createsuperuser()
        with tenancy.unscoped():
            root = User.objects.get(username="root")
        self.assertTrue(root.is_superuser)
        self.assertEqual(root.workspace_id, tenancy.default_workspace().pk)

    def test_the_account_can_use_the_admin(self):
        _createsuperuser()
        client = APIClient()
        r = client.post("/admin/login/", {"username": "root", "password": PASSWORD, "next": "/admin/"})
        self.assertEqual(r.status_code, 302, getattr(r, "content", b"")[:400])
        self.assertEqual(r["Location"], "/admin/")
        r = client.get("/admin/")
        self.assertEqual(r.status_code, 200, r.get("Location"))
        self.assertContains(r, "Site administration")
        # A changelist of the user model and one of a tenant model.
        r = client.get("/admin/accounts/user/")
        self.assertEqual(r.status_code, 200, r.get("Location"))
        self.assertContains(r, "root")
        r = client.get("/admin/accounts/role/")
        self.assertEqual(r.status_code, 200, r.get("Location"))
        self.assertContains(r, "Administrator")

        # And the application, in the same browser: the admin's session
        # cookie travels with every API request.
        r = client.post("/api/auth/token/", {"username": "root", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        bearer = f"Bearer {r.data['access']}"
        r = client.get("/api/users/me/", HTTP_AUTHORIZATION=bearer)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["username"], "root")
        r = client.get("/api/workspaces/current/", HTTP_AUTHORIZATION=bearer)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data["slug"], tenancy.DEFAULT_SLUG)

    def test_a_workspace_that_is_active_still_wins(self):
        """A command run inside a workspace files the account there, as it
        always has."""
        from accounts.models import Workspace

        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-first")
        with tenancy.scoped(beta), mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
            call_command("createsuperuser", interactive=False, username="broot",
                         email="broot@test.local", verbosity=0)
        with tenancy.unscoped():
            self.assertEqual(User.objects.get(username="broot").workspace_id, beta.pk)


class FirstAdministratorPasswordTests(APITestBase):
    def test_noinput_refuses_a_password_the_policy_refuses(self):
        with self.assertRaises(CommandError) as caught:
            _createsuperuser(password="short")
        self.assertIn("too short", str(caught.exception))
        self.assertFalse(_exists("root"))

    def test_noinput_without_a_password_still_makes_an_account_that_cannot_sign_in(self):
        _createsuperuser(password=None)
        with tenancy.unscoped():
            self.assertFalse(User.objects.get(username="root").has_usable_password())

    def test_the_interactive_path_offers_no_bypass_and_asks_again(self):
        """Django asked "Bypass password validation and create user anyway?",
        and a yes was then refused by the policy, throwing away the username
        and email already typed. The command now says the policy has no
        bypass and asks for another password, keeping what was typed."""
        err = io.StringIO()
        asked = []

        def typed(prompt=""):
            asked.append(prompt)
            if prompt.startswith("Username"):
                return "root"
            if prompt.startswith("Email"):
                return "root@test.local"
            return "y"  # what the clean-install run answered to the bypass

        with tenancy.unscoped(), \
                mock.patch.object(stock.getpass, "getpass",
                                  side_effect=["short", "short", PASSWORD, PASSWORD]), \
                mock.patch("builtins.input", side_effect=typed):
            call_command("createsuperuser", interactive=True, stdin=_TTY(), stderr=err,
                         verbosity=0)
        self.assertEqual([p.split()[0].rstrip(":") for p in asked], ["Username", "Email"],
                         "asked for the username and email once, and nothing else")
        self.assertIn("too short", err.getvalue())
        self.assertIn("password policy has no bypass", err.getvalue())
        with tenancy.unscoped():
            user = User.objects.get(username="root")
        self.assertEqual(user.email, "root@test.local")
        self.assertTrue(user.check_password(PASSWORD))

    def test_the_command_is_ours_not_djangos(self):
        """Django finds a command in the first installed app that has it, so
        the override only runs while accounts comes before django.contrib.auth."""
        from django.core.management import get_commands

        self.assertEqual(get_commands()["createsuperuser"], "accounts")

    def test_the_interactive_path_with_a_good_password_works(self):
        with tenancy.unscoped(), \
                mock.patch.object(stock.getpass, "getpass", side_effect=[PASSWORD, PASSWORD]):
            call_command("createsuperuser", interactive=True, username="root",
                         email="root@test.local", stdin=_TTY(), verbosity=0)
        with tenancy.unscoped():
            self.assertTrue(User.objects.get(username="root").check_password(PASSWORD))


class UserListOrderTests(APITestBase):
    def test_the_list_is_ordered_and_paginates_without_a_warning(self):
        for name in ("zed", "bob", "kim"):
            make_user(name)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            r = self.client_for(self.admin).get("/api/users/")
        self.assertEqual(r.status_code, 200, r.data)
        names = [row["username"] for row in r.data["results"]]
        self.assertEqual(names, sorted(names))
        self.assertFalse([w for w in caught if "Unordered" in w.category.__name__],
                         [str(w.message) for w in caught])


def _run_migration_0013():
    """accounts migration 0013's data step, against the live registry."""
    import importlib
    from types import SimpleNamespace

    from django.apps import apps
    from django.db import connection

    module = importlib.import_module("accounts.migrations.0013_attach_workspaceless_superusers")
    module.attach(apps, SimpleNamespace(connection=connection))


def _workspaceless(username, superuser=True):
    """An account the way an older release's createsuperuser left it."""
    with tenancy.unscoped():
        user = make_user(username, superuser=superuser)
        User.objects.filter(pk=user.pk).update(workspace=None)
        return User.objects.get(pk=user.pk)


def _workspace_of(user):
    with tenancy.unscoped():
        return User.objects.get(pk=user.pk).workspace_id


def _admin_home(username):
    """Sign in to /admin/ and load its index; the index status code."""
    client = APIClient()
    r = client.post("/admin/login/", {"username": username, "password": PASSWORD, "next": "/admin/"})
    if r.status_code != 302:
        return r.status_code
    return client.get("/admin/").status_code


class WorkspacelessSuperuserMigrationTests(APITestBase):
    """Accounts older releases' createsuperuser made with no workspace. The
    command no longer does that, but installations upgrading keep theirs, and
    each one still loops at /admin/ until migration 0013 attaches it."""

    def test_an_old_account_is_attached_and_can_use_the_admin(self):
        legacy = _workspaceless("legacy")
        self.assertIsNone(legacy.workspace_id)
        self.assertNotEqual(_admin_home("legacy"), 200, "the defect this migration repairs")

        _run_migration_0013()

        self.assertEqual(_workspace_of(legacy), tenancy.default_workspace().pk)
        self.assertEqual(_admin_home("legacy"), 200)

    def test_an_archived_first_workspace_is_passed_over(self):
        from accounts.models import Workspace

        Workspace.objects.filter(slug=tenancy.DEFAULT_SLUG).update(is_active=False)
        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-migrate")
        legacy = _workspaceless("legacy")

        _run_migration_0013()

        self.assertEqual(_workspace_of(legacy), beta.pk)

    def test_only_superusers_with_no_workspace_move_and_a_second_run_moves_nothing(self):
        from accounts.models import Workspace

        beta = Workspace.objects.create(name="Beta Ltd", slug="beta-stay")
        with tenancy.scoped(beta):
            placed = make_user("placed", superuser=True)
        stray = _workspaceless("stray", superuser=False)
        legacy = _workspaceless("legacy")

        _run_migration_0013()
        self.assertEqual(_workspace_of(placed), beta.pk)
        self.assertIsNone(_workspace_of(stray), "only superusers are attached")
        default = tenancy.default_workspace().pk
        self.assertEqual(_workspace_of(legacy), default)

        # Run again after the first workspace is archived: nothing has none
        # any more, so nothing moves.
        Workspace.objects.filter(pk=default).update(is_active=False)
        _run_migration_0013()
        self.assertEqual(_workspace_of(legacy), default)
        self.assertEqual(_workspace_of(placed), beta.pk)


def _posix_bash():
    """A bash that runs a script in this process's environment, or None.
    On Windows, System32's bash.exe starts WSL instead."""
    found = shutil.which("bash")
    if found and os.name == "nt" and "system32" in found.lower():
        return None
    return found


@skipUnless(_posix_bash(), "needs bash")
class EntrypointSuperuserTests(SimpleTestCase):
    """The DJANGO_SUPERUSER_* step of backend/entrypoint.sh, run in bash with
    ``python`` (and so createsuperuser) replaced by a stub. It used to discard
    the command's stderr and log "already exists" for every failure, so a
    password the policy refused left no administrator and a log that said
    there was one."""

    source = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")
    start = 'if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]'
    block = source[source.index(start):source.index("python manage.py generate_folder_tree")]

    def run_step(self, message="", status=0, **env):
        script = (
            "set -euo pipefail\n"
            "log() { printf '%s\\n' \"$*\"; }\n"
            f"python() {{ printf '%s\\n' {shlex.quote(message)} >&2; return {status}; }}\n"
            f"{self.block}\n"
            "echo BOOT-CONTINUES\n"
        )
        base = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_SUPERUSER_")}
        r = subprocess.run([_posix_bash(), "-c", script], env={**base, **env},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("BOOT-CONTINUES", r.stdout)
        return r.stdout

    both = {"DJANGO_SUPERUSER_USERNAME": "root", "DJANGO_SUPERUSER_PASSWORD": "changeme"}

    def test_a_refusal_is_logged_with_its_reason_and_the_boot_goes_on(self):
        out = self.run_step(
            "CommandError: Superuser not created. The password must pass this installation's "
            "password policy, with no bypass. This password is too short.", status=1, **self.both)
        self.assertIn("'root' was NOT created", out)
        self.assertIn("This password is too short.", out)
        self.assertIn("PASSWORD_MIN_LENGTH", out, "the policy advice follows a policy refusal")
        self.assertNotIn("already exists", out)

    def test_a_refusal_for_another_reason_gives_no_password_advice(self):
        out = self.run_step("CommandError: Enter a valid email address.", status=1, **self.both)
        self.assertIn("'root' was NOT created", out)
        self.assertIn("Enter a valid email address.", out)
        self.assertNotIn("password policy", out)
        self.assertNotIn("PASSWORD_MIN_LENGTH", out)
        self.assertIn("manage.py createsuperuser", out)

    def test_already_exists_only_when_the_username_is_taken(self):
        out = self.run_step("CommandError: Error: That username is already taken.", status=1, **self.both)
        self.assertIn("'root' already exists, leaving it alone", out)
        self.assertNotIn("NOT created", out)

    def test_a_new_account_is_reported_as_created(self):
        out = self.run_step(status=0, **self.both)
        self.assertIn("Superuser 'root' created", out)

    def test_half_the_pair_says_why_nothing_happened(self):
        out = self.run_step(DJANGO_SUPERUSER_USERNAME="root")
        self.assertIn("must both be set", out)
        self.assertEqual(self.run_step().strip(), "BOOT-CONTINUES", "unset: say nothing")

    def test_the_banner_reports_a_missing_administrator(self):
        self.assertIn("administrator_present()", self.source)
        self.assertIn("No administrator exists yet", self.source)


class EntrypointEmailFallbackTests(TestCase):
    """With DJANGO_SUPERUSER_EMAIL unset, the entrypoint's fallback address.
    It used to be admin@example.com, so a real administrator named admin was
    the demo administrator to /api/health/, the banner and remove_demo_data."""

    def test_an_admin_made_with_the_fallback_is_no_demo_account(self):
        import re

        from config.health import administrator_present, demo_accounts_present

        source = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text(encoding="utf-8")
        fallback = re.search(r'--email "\$\{DJANGO_SUPERUSER_EMAIL:-([^}]*)\}"', source).group(1)
        # The command validates the address, as it does on a real boot.
        with tenancy.unscoped(), mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": PASSWORD}):
            call_command("createsuperuser", interactive=False, username="admin",
                         email=fallback, verbosity=0)
        with tenancy.unscoped():
            self.assertEqual(User.objects.get(username="admin").email, fallback)
        self.assertFalse(demo_accounts_present())
        self.assertTrue(administrator_present())


class WorkspacelessSuperuserMigrationEmptyDatabaseTests(TestCase):
    """The same step on a database with no workspace at all."""

    def setUp(self):
        from accounts.models import Workspace

        with tenancy.unscoped():
            Workspace.objects.all().delete()

    def test_nothing_to_attach_creates_nothing(self):
        from accounts.models import Workspace

        _run_migration_0013()
        self.assertFalse(Workspace.objects.exists())

    def test_an_account_to_attach_gets_the_default_workspace_back(self):
        from accounts.models import Workspace

        legacy = _workspaceless("legacy")
        _run_migration_0013()
        default = Workspace.objects.get(slug=tenancy.DEFAULT_SLUG)
        self.assertEqual(_workspace_of(legacy), default.pk)
