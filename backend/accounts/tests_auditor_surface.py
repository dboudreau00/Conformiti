"""What an external auditor can reach, enumerated rather than assumed.

The shipped "Auditor" role is described as "sees only granted folders", and
until 0.9.4 it was a full reader of the whole programme: every permission
class in the product granted reads to *any* authenticated account, and an
auditor is an authenticated account. The risk register, the vendor file, the
control library, the user directory and the shared calendar were all open to
someone the organisation had invited to look at one engagement.

The fix is deny-by-default, and this suite is what keeps it that way. It walks
the DRF routers of every installed app rather than a list written by hand, so
a viewset added later cannot quietly land on the auditor's side of the line:
an unclassified prefix fails here before it ships.
"""
import importlib

from django.apps import apps
from django.conf import settings

from testutils import APITestBase

# Reachable by an external auditor, and why. Contents are still scoped -- an
# auditor sees the packages issued to them and the folders granted with them,
# which is a different question from whether the route answers at all.
ALLOWED = {
    "evidence-packages": "the engagement itself",
    "package-controls": "the workpaper rows they conclude on",
    "package-evidence": "the artefacts pinned for them",
    "package-samples": "the sample items they test",
    "package-grants": "the grant they hold",
    "pbc-requests": "their own request list",
    "pbc-items": "the lines of it",
    "folders": "granted folders only (documents.access decides)",
    "documents": "granted folders only (documents.access decides)",
    "access-reviews": "an access review is an audit artefact",
    "access-review-items": "its rows",
    "audit-log": "the trail is what an auditor is here to read",
    "workspaces": "their own, to name it on screen",
}

# Refused outright: the organisation's own programme, not the engagement.
DENIED = {
    "roles": "the capability model",
    "users": "the staff directory",
    "frameworks": "the control library",
    "controls": "the control library",
    "crosswalk": "the control library",
    "control-evidence": "every control's evidence, not just the package's",
    "responsibilities": "who does what across the whole programme",
    "folder-permissions": "who else can see a folder is the organisation's business",
    "form-templates": "blank internal forms",
    "meeting-series": "the governance calendar",
    "meeting-minutes": "what was said in management meetings",
    "champion-groups": "internal ownership structure",
    "group-members": "internal ownership structure",
    "risks": "the whole book of open risk",
    "risk-notes": "the running commentary on it",
    "calendar": "who is meeting whom, and when",
    "vendors": "the third-party file",
    "vendor-assessments": "third-party assurance",
    "questionnaire-invites": "live links sent to vendors",
    "integrations/jira/boards": "the remediation backlog",
}


def registered_prefixes():
    """Every DRF router prefix in every installed app of this project."""
    found = set()
    here = str(settings.BASE_DIR)
    for config in apps.get_app_configs():
        if not str(config.path).startswith(here):
            continue  # a third-party app living in site-packages
        try:
            module = importlib.import_module(f"{config.name}.urls")
        except ModuleNotFoundError:
            continue
        for value in vars(module).values():
            for prefix, _viewset, _basename in getattr(value, "registry", []):
                found.add(prefix)
    return found


class AuditorSurfaceTests(APITestBase):
    def setUp(self):
        super().setUp()
        self.client_ = self.client_for(self.auditor)

    def test_every_registered_collection_is_classified(self):
        """A new viewset has to be a decision, not an accident."""
        unclassified = registered_prefixes() - set(ALLOWED) - set(DENIED)
        self.assertEqual(unclassified, set(), (
            "These collections are registered but nobody has decided whether an "
            "external auditor may read them. Add each to ALLOWED or DENIED in "
            "accounts/tests_auditor_surface.py, with the reason."
        ))

    def test_the_programme_is_refused(self):
        for prefix, why in sorted(DENIED.items()):
            with self.subTest(prefix=prefix, why=why):
                r = self.client_.get(f"/api/{prefix}/")
                self.assertEqual(r.status_code, 403, f"/api/{prefix}/ -> {r.status_code}: {why}")

    def test_the_engagement_is_reachable(self):
        for prefix in sorted(ALLOWED):
            with self.subTest(prefix=prefix):
                r = self.client_.get(f"/api/{prefix}/")
                self.assertEqual(r.status_code, 200, f"/api/{prefix}/ -> {r.status_code}")

    def test_the_organisation_still_reads_its_own_programme(self):
        """The refusal is about the role, not about the route."""
        manager = self.client_for(self.manager)
        for prefix in sorted(DENIED):
            with self.subTest(prefix=prefix):
                self.assertEqual(manager.get(f"/api/{prefix}/").status_code, 200, prefix)

    def test_the_analytics_summary_is_refused(self):
        """Not a router prefix, but the same disclosure: readiness, coverage
        and ownership for the whole organisation."""
        self.assertEqual(self.client_.get("/api/analytics/summary/").status_code, 403)
        self.assertEqual(self.client_for(self.manager).get("/api/analytics/summary/").status_code, 200)

    def test_an_auditor_still_manages_their_own_account(self):
        for path in ("/api/users/me/", "/api/auth/webauthn/", "/api/notifications/channels/"):
            with self.subTest(path=path):
                self.assertEqual(self.client_.get(path).status_code, 200, path)
