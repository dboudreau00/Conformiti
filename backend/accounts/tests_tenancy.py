"""Workspaces (0.9.0): one installation, several organisations, each seeing
only its own. The suite's fixtures live in the Default workspace (the test
runner activates it); these tests add a second organisation, Beta, and
check that nothing crosses the line in either direction."""
from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from accounts import tenancy
from accounts.models import Role, User, Workspace
from analytics.models import ReadinessSnapshot
from audit.models import AuditLog
from compliance.management.commands.seed_frameworks import BUILTIN_ROLES
from compliance.models import Control, Framework
from documents.models import Document, Folder
from governance.models import MeetingSeries, Risk
from testutils import PASSWORD, APITestBase, Tree, make_doc, make_roles, make_user
from vendors.models import Vendor


class TwoWorkspaces(APITestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.alpha = tenancy.current()
        cls.beta = Workspace.objects.create(name="Beta Ltd", slug="beta")
        with tenancy.scoped(cls.beta):
            cls.b_roles = make_roles()
            cls.b_admin = make_user("bea", cls.b_roles["Administrator"])
            cls.b_manager = make_user("ben", cls.b_roles["Compliance Manager"])
            cls.b_tree = Tree()
            cls.b_doc = make_doc(cls.b_tree.ctrl1, cls.b_admin, name="Beta policy", days=-3)
            cls.b_risk = Risk.objects.create(title="Beta risk", owner=cls.b_admin)
            cls.b_vendor = Vendor.objects.create(name="Beta vendor")
            cls.b_series = MeetingSeries.objects.create(name="Beta board")
        cls.a_doc = make_doc(cls.tree.ctrl1, cls.admin, name="Alpha policy", days=-3)
        cls.a_risk = Risk.objects.create(title="Alpha risk", owner=cls.admin)
        cls.a_vendor = Vendor.objects.create(name="Alpha vendor")
        cls.a_series = MeetingSeries.objects.create(name="Alpha board")

    @staticmethod
    def ids(response):
        data = response.data
        rows = data["results"] if isinstance(data, dict) and "results" in data else data
        return {r["id"] for r in rows}


# --------------------------------------------------------------------------- #
# The manager
# --------------------------------------------------------------------------- #
class ManagerScopingTests(TwoWorkspaces):
    def test_active_workspace_filters_every_query(self):
        self.assertEqual(set(Framework.objects.values_list("workspace_id", flat=True)), {self.alpha.pk})
        self.assertEqual(Document.objects.count(), 1)
        with tenancy.scoped(self.beta):
            self.assertEqual(Framework.objects.count(), 1)
            self.assertEqual(Framework.objects.get().workspace_id, self.beta.pk)
            self.assertEqual(list(Document.objects.values_list("name", flat=True)), ["Beta policy"])
        with tenancy.unscoped():
            self.assertEqual(Framework.objects.count(), 2)

    def test_import_time_queryset_is_pinned_when_chained(self):
        """A `queryset = Model.objects.all()` built with nothing active (a
        viewset's class attribute) is scoped as soon as DRF calls .all()."""
        with tenancy.unscoped():
            stale = Document.objects.all()
        self.assertEqual(stale.all().count(), 1)
        self.assertEqual(stale.filter(name="Beta policy").count(), 0)
        self.assertIsNone(stale.filter(pk=self.b_doc.pk).first())

    def test_queryset_evaluates_in_the_workspace_active_when_it_runs(self):
        with tenancy.scoped(self.beta):
            docs = Document.objects.all()
            self.assertEqual(list(docs.values_list("name", flat=True)), ["Beta policy"])
        # The same queryset under Default shows Default's rows, and none with nothing active.
        self.assertEqual(list(docs.all().values_list("name", flat=True)), ["Alpha policy"])
        with tenancy.unscoped():
            self.assertEqual(docs.all().count(), 0)

    def test_related_managers_stay_in_the_workspace(self):
        self.assertEqual(self.tree.framework.categories.count(), 1)
        with tenancy.scoped(self.beta):
            self.assertEqual(self.b_tree.framework.categories.count(), 1)
            # Forward FK access works regardless of the active workspace.
        self.assertEqual(self.b_doc.folder.workspace_id, self.beta.pk)

    def test_save_takes_workspace_from_the_parent(self):
        """Filing into a Beta folder while Default is active lands in Beta:
        the parent decides, the active workspace only fills the gap."""
        doc = Document(folder=self.b_tree.ctrl2, name="Filed under beta", owner=self.admin)
        doc.file.save("x.txt", ContentFile(b"x"), save=False)
        doc.save()
        self.assertEqual(doc.workspace_id, self.beta.pk)
        risk = Risk.objects.create(title="No parent, so the active workspace")
        self.assertEqual(risk.workspace_id, self.alpha.pk)

    def test_save_with_nothing_to_go_on_refuses(self):
        with tenancy.unscoped():
            with self.assertRaises(tenancy.NoActiveWorkspace):
                Risk.objects.create(title="orphan")
            entry = AuditLog.objects.create(action="probe", object_type="test")
            about_bea = AuditLog.objects.create(action="probe", object_type="test", user=self.b_admin)
        self.assertIsNone(entry.workspace_id)  # nullable models may have none
        # Since 0.9.2 an entry belongs to the workspace the action HAPPENED
        # in, not to the actor: a superuser switched into another tenant is
        # acting on that tenant, and its administrators have to see it. With
        # nothing active and nothing passed, there is no workspace to record.
        self.assertIsNone(about_bea.workspace_id)
        with tenancy.scoped(self.beta):
            in_beta = AuditLog.objects.create(action="probe", object_type="test", user=self.admin)
        self.assertEqual(in_beta.workspace_id, self.beta.pk)
        self.assertFalse(Risk.objects.filter(title="orphan").exists())
        # The operator sees installation-level entries; a workspace administrator does not.
        r = self.client_for(self.admin).get("/api/audit-log/", {"action": "probe"})
        self.assertIn(entry.pk, self.ids(r))
        self.assertIn(about_bea.pk, self.ids(r))   # no workspace: an operator-level row
        self.assertNotIn(in_beta.pk, self.ids(r))  # Beta's row is Beta's
        r = self.client_for(self.b_manager).get("/api/audit-log/", {"action": "probe"})
        self.assertEqual(self.ids(r), {in_beta.pk})

    def test_bulk_create_fills_the_workspace(self):
        with tenancy.scoped(self.beta):
            rows = Risk.objects.bulk_create([Risk(title="b1"), Risk(title="b2")])
        self.assertEqual({r.workspace_id for r in rows}, {self.beta.pk})
        self.assertFalse(Risk.objects.filter(title__in=["b1", "b2"]).exists())

    def test_default_workspace_exists_after_migration(self):
        self.assertEqual(Workspace.objects.get(slug="default").pk, self.alpha.pk)
        self.assertEqual(self.admin.workspace_id, self.alpha.pk)


# --------------------------------------------------------------------------- #
# The API
# --------------------------------------------------------------------------- #
LIST_ROUTES = [
    "/api/frameworks/", "/api/controls/", "/api/folders/", "/api/documents/",
    "/api/risks/", "/api/vendors/", "/api/meeting-series/", "/api/users/", "/api/roles/",
]


class ApiIsolationTests(TwoWorkspaces):
    def test_every_list_shows_only_the_callers_workspace(self):
        beta_ids = {}
        with tenancy.scoped(self.beta):
            for route, model in [
                ("/api/frameworks/", Framework), ("/api/controls/", Control), ("/api/folders/", Folder),
                ("/api/documents/", Document), ("/api/risks/", Risk), ("/api/vendors/", Vendor),
                ("/api/meeting-series/", MeetingSeries), ("/api/users/", User), ("/api/roles/", Role),
            ]:
                beta_ids[route] = set(model.objects.values_list("id", flat=True))
                self.assertTrue(beta_ids[route], route)
        client = self.client_for(self.admin)
        for route in LIST_ROUTES:
            with self.subTest(route=route):
                r = client.get(route)
                self.assertEqual(r.status_code, 200, r.data)
                self.assertFalse(self.ids(r) & beta_ids[route], f"{route} leaked Beta rows")
                self.assertTrue(self.ids(r), f"{route} returned nothing for Default")

    def test_beta_admin_sees_only_beta(self):
        client = self.client_for(self.b_admin)
        r = client.get("/api/documents/")
        self.assertEqual([d["name"] for d in r.data["results"]], ["Beta policy"])
        r = client.get("/api/users/")
        self.assertEqual({u["username"] for u in r.data["results"]}, {"bea", "ben"})
        r = client.get("/api/users/me/")
        self.assertEqual(r.data["workspace_detail"], {"id": self.beta.pk, "name": "Beta Ltd", "slug": "beta"})

    def test_foreign_row_by_id_is_404(self):
        client = self.client_for(self.admin)
        for route, obj in [
            (f"/api/frameworks/{self.b_tree.framework.pk}/", self.b_tree.framework),
            (f"/api/documents/{self.b_doc.pk}/", self.b_doc),
            (f"/api/risks/{self.b_risk.pk}/", self.b_risk),
            (f"/api/vendors/{self.b_vendor.pk}/", self.b_vendor),
            (f"/api/users/{self.b_admin.pk}/", self.b_admin),
        ]:
            with self.subTest(route=route):
                self.assertEqual(client.get(route).status_code, 404)
                self.assertIn(client.patch(route, {"name": "x"}, format="json").status_code, (404, 405))

    def test_post_referencing_a_foreign_row_is_400(self):
        client = self.client_for(self.manager)
        r = client.post("/api/risks/", {"title": "Points at Beta", "control": self.b_tree.c1.pk}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn("control", r.data)
        r = client.post("/api/risks/", {"title": "Points home", "control": self.tree.c1.pk}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(Risk.objects.get(pk=r.data["id"]).workspace_id, self.alpha.pk)

    def test_non_superuser_header_is_ignored(self):
        client = self.client_for(self.manager)
        r = client.get("/api/frameworks/", HTTP_X_WORKSPACE="beta")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.ids(r), {self.tree.framework.pk})

    def test_superuser_switches_with_the_header(self):
        client = self.client_for(self.admin)
        r = client.get("/api/frameworks/", HTTP_X_WORKSPACE="beta")
        self.assertEqual(self.ids(r), {self.b_tree.framework.pk})
        r = client.get("/api/frameworks/", HTTP_X_WORKSPACE=str(self.beta.pk))
        self.assertEqual(self.ids(r), {self.b_tree.framework.pk})
        r = client.get("/api/workspaces/current/", HTTP_X_WORKSPACE="beta")
        self.assertEqual((r.data["slug"], r.data["can_switch"]), ("beta", True))
        r = client.get("/api/workspaces/current/")
        self.assertEqual(r.data["slug"], "default")
        # What the superuser creates while switched lands in Beta.
        r = client.post("/api/risks/", {"title": "Raised in Beta"}, format="json", HTTP_X_WORKSPACE="beta")
        self.assertEqual(r.status_code, 201, r.data)
        with tenancy.unscoped():
            self.assertEqual(Risk.objects.get(pk=r.data["id"]).workspace_id, self.beta.pk)

    def test_unknown_workspace_in_header_is_403(self):
        r = self.client_for(self.admin).get("/api/frameworks/", HTTP_X_WORKSPACE="nowhere")
        self.assertEqual(r.status_code, 403)
        self.assertIn("nowhere", str(r.data["detail"]))

    def test_account_without_a_workspace_is_refused(self):
        lost = make_user("lost", self.roles["Viewer"])
        # save() would put it straight back into the active workspace; that
        # is the point of save(), so detach at the database.
        User.objects.filter(pk=lost.pk).update(workspace=None)
        lost.refresh_from_db()
        r = self.client_for(lost).get("/api/frameworks/")
        self.assertEqual(r.status_code, 403)
        self.assertIn("not attached", str(r.data["detail"]))

    def test_archived_workspace_refuses_its_people_but_not_the_superuser(self):
        # A token issued before the archive stops working; a new sign-in is refused.
        r = APIClient().post("/api/auth/token/", {"username": "bea", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        bearer = f"Bearer {r.data['access']}"
        self.assertEqual(APIClient().get("/api/frameworks/", HTTP_AUTHORIZATION=bearer).status_code, 200)
        self.beta.is_active = False
        self.beta.save(update_fields=["is_active"])
        r = APIClient().get("/api/frameworks/", HTTP_AUTHORIZATION=bearer)
        self.assertEqual(r.status_code, 401)
        self.assertIn("archived", str(r.data["detail"]))
        r = APIClient().post("/api/auth/token/", {"username": "bea", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 401, r.data)
        self.assertIn("archived", str(r.data["detail"]))
        # The superuser may still look, by name.
        r = self.client_for(self.admin).get("/api/frameworks/", HTTP_X_WORKSPACE="beta")
        self.assertEqual(r.status_code, 403)
        self.assertIn("archived", str(r.data["detail"]))

    def test_names_are_unique_per_workspace_not_per_installation(self):
        client = self.client_for(self.admin)
        r = client.post("/api/frameworks/", {"key": "tfw", "name": "Duplicate"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)
        r = client.post("/api/frameworks/", {"key": "shared", "name": "Shared key"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        r = client.post("/api/frameworks/", {"key": "shared", "name": "Shared key"}, format="json",
                        HTTP_X_WORKSPACE="beta")
        self.assertEqual(r.status_code, 201, r.data)
        with tenancy.unscoped():
            self.assertEqual(Framework.objects.filter(key="shared").count(), 2)
        r = client.post("/api/roles/", {"name": "Administrator"}, format="json")
        self.assertEqual(r.status_code, 400, r.data)

    def test_login_audit_entry_is_stamped_with_the_persons_workspace(self):
        r = APIClient().post("/api/auth/token/", {"username": "bea", "password": PASSWORD}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        with tenancy.unscoped():
            entry = AuditLog.objects.filter(user=self.b_admin, action="login").latest("timestamp")
        self.assertEqual(entry.workspace_id, self.beta.pk)
        # ... and Beta's administrator can see it, Default's cannot.
        r = self.client_for(self.b_admin).get("/api/audit-log/", {"action": "login"})
        self.assertIn(entry.pk, self.ids(r))
        r = self.client_for(self.admin).get("/api/audit-log/", {"action": "login"})
        self.assertNotIn(entry.pk, self.ids(r))


# --------------------------------------------------------------------------- #
# The workspace API
# --------------------------------------------------------------------------- #
class WorkspaceApiTests(TwoWorkspaces):
    def test_people_see_their_own_workspace_only(self):
        r = self.client_for(self.b_manager).get("/api/workspaces/")
        self.assertEqual([w["slug"] for w in r.data["results"]], ["beta"])
        self.assertEqual(self.client_for(self.b_manager).post("/api/workspaces/", {"name": "X"}).status_code, 403)
        r = self.client_for(self.admin).get("/api/workspaces/")
        self.assertEqual({w["slug"] for w in r.data["results"]}, {"default", "beta"})
        self.assertEqual({w["slug"]: w["users"] for w in r.data["results"]}["beta"], 2)

    def test_superuser_creates_a_workspace_with_its_roles(self):
        client = self.client_for(self.admin)
        r = client.post("/api/workspaces/", {"name": "Gamma Inc", "with_frameworks": False}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["slug"], "gamma-inc")
        gamma = Workspace.objects.get(slug="gamma-inc")
        with tenancy.scoped(gamma):
            self.assertEqual(Role.objects.count(), len(BUILTIN_ROLES))
            self.assertEqual(Framework.objects.count(), 0)
            self.assertEqual(User.objects.count(), 0)
        # A person created while switched there joins it.
        r = client.post("/api/users/", {"username": "gail", "email": "gail@gamma.example", "password": PASSWORD},
                        format="json", HTTP_X_WORKSPACE="gamma-inc")
        self.assertEqual(r.status_code, 201, r.data)
        with tenancy.unscoped():
            self.assertEqual(User.objects.get(username="gail").workspace, gamma)
        self.assertFalse(User.objects.filter(username="gail").exists())  # not in Default

    def test_creating_with_frameworks_seeds_the_library(self):
        r = self.client_for(self.admin).post("/api/workspaces/", {"name": "Delta", "slug": "delta"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        with tenancy.scoped(Workspace.objects.get(slug="delta")):
            self.assertGreater(Framework.objects.count(), 0)
            self.assertGreater(Control.objects.count(), 100)
            self.assertTrue(Folder.objects.filter(is_framework_root=True).exists())
        # Default's library is untouched.
        self.assertEqual(Framework.objects.count(), 1)

    def test_archiving_rules(self):
        client = self.client_for(self.admin)
        r = client.patch(f"/api/workspaces/{self.alpha.pk}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 403)
        r = client.patch(f"/api/workspaces/{self.beta.pk}/", {"is_active": False}, format="json")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(Workspace.objects.get(pk=self.beta.pk).is_active)
        self.assertEqual(client.delete(f"/api/workspaces/{self.beta.pk}/").status_code, 405)
        r = client.patch(f"/api/workspaces/{self.alpha.pk}/", {"slug": "renamed"}, format="json")
        self.assertEqual(r.status_code, 400)


# --------------------------------------------------------------------------- #
# Jobs and commands
# --------------------------------------------------------------------------- #
class JobsTests(TwoWorkspaces):
    def test_morning_scans_run_in_every_workspace(self):
        from notifications.tasks import run_all_scans

        result = run_all_scans(dry_run=True)
        self.assertEqual(set(result), {"default", "beta"})
        self.assertEqual(result["default"]["documents"], 1)
        self.assertEqual(result["beta"]["documents"], 1)
        self.beta.is_active = False
        self.beta.save(update_fields=["is_active"])
        self.assertEqual(set(run_all_scans(dry_run=True)), {"default"})

    def test_readiness_snapshot_per_workspace(self):
        call_command("record_readiness", verbosity=0)
        with tenancy.unscoped():
            self.assertEqual(ReadinessSnapshot.objects.filter(date=timezone.localdate()).count(), 2)
            self.assertEqual(set(ReadinessSnapshot.objects.values_list("workspace_id", flat=True)),
                             {self.alpha.pk, self.beta.pk})

    def test_digest_is_computed_in_the_persons_workspace(self):
        from notifications.tasks import run_digests

        self.b_admin.digest = User.Digest.DAILY
        self.b_admin.save(update_fields=["digest"])
        self.assertEqual(run_digests(), 1)
        body = mail.outbox[-1].body
        self.assertIn("Beta policy", body)
        self.assertNotIn("Alpha policy", body)

    def test_seed_frameworks_targets_one_workspace(self):
        call_command("seed_frameworks", "--roles-only", "--workspace", "beta", verbosity=0)
        with tenancy.scoped(self.beta):
            self.assertEqual(Role.objects.count(), len(BUILTIN_ROLES))
        with self.assertRaises(CommandError):
            call_command("seed_frameworks", "--roles-only", "--workspace", "nope", verbosity=0)

    def test_for_each_workspace_activates_each(self):
        seen = {ws.slug: Document.objects.count() for ws in tenancy.for_each_workspace()}
        self.assertEqual(seen, {"default": 1, "beta": 1})
        self.assertEqual(tenancy.current_id(), self.alpha.pk)  # restored afterwards
