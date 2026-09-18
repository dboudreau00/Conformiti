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


# Actions on a denied collection that an external auditor may still reach,
# because they act on the caller's own account rather than on the
# organisation's programme. Everything else that declares its own
# permission_classes has to refuse them.
SELF_SERVICE_ACTIONS = {
    ("users", "me"): "their own profile, the same row /users/me/ returns",
    ("users", "change_password"): "changing your own password is self-service",
}


def registered_viewsets():
    """(prefix, viewset) for every DRF router registration in this project."""
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
            for prefix, viewset, _basename in getattr(value, "registry", []):
                found.add((prefix, viewset))
    return found


def registered_prefixes():
    """Every DRF router prefix in every installed app of this project."""
    return {prefix for prefix, _viewset in registered_viewsets()}


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

    def test_a_reachable_collection_still_answers_with_only_what_it_should(self):
        """Reaching a route and reading everything on it are two questions.
        "workspaces" is on the allowed list so the auditor can see whose
        engagement they are on, and until 0.9.5b that answer also carried the
        organisation's Slack and Teams webhook URLs, which are credentials
        (REVIEW_095.md, S-1). Being listed here is not a licence to disclose."""
        from accounts.models import Workspace

        workspace = Workspace.objects.get(pk=self.auditor.workspace_id)
        workspace.slack_webhook_url = "https://hooks.slack.com/services/T0/B0/secret"
        workspace.notification_email = "grc@example.com"
        workspace.save()
        for url in ("/api/workspaces/", "/api/workspaces/current/"):
            body = str(self.client_.get(url).data)
            self.assertNotIn("hooks.slack.com", body, url)
            self.assertNotIn("secret", body, url)
            self.assertNotIn("grc@example.com", body, url)

    def test_the_analytics_summary_is_refused(self):
        """Not a router prefix, but the same disclosure: readiness, coverage
        and ownership for the whole organisation."""
        self.assertEqual(self.client_.get("/api/analytics/summary/").status_code, 403)
        self.assertEqual(self.client_for(self.manager).get("/api/analytics/summary/").status_code, 200)

    def test_an_auditor_still_manages_their_own_account(self):
        for path in ("/api/users/me/", "/api/auth/webauthn/", "/api/notifications/channels/"):
            with self.subTest(path=path):
                self.assertEqual(self.client_.get(path).status_code, 200, path)


class AuditorActionSurfaceTests(APITestBase):
    """The list route is not the whole collection.

    ``permission_classes`` on an ``@action`` REPLACES the viewset's, it does
    not add to it, so one decorator can reopen a collection this suite has
    already classified as denied and the walk above will still pass: it only
    ever asked the list prefix. That is how the Jira issues proxy handed an
    issued external auditor the organisation's remediation backlog, board by
    sequential board, with the stored API token doing the fetching (0.9.5f).
    """

    def setUp(self):
        super().setUp()
        self.client_ = self.client_for(self.auditor)

    def test_no_action_reopens_a_denied_collection(self):
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        open_to_auditor = set()
        for prefix, viewset in sorted(registered_viewsets(), key=lambda pair: pair[0]):
            if prefix not in DENIED:
                continue
            for extra in viewset.get_extra_actions():
                declared = extra.kwargs.get("permission_classes")
                if declared is None:
                    continue  # inherits the viewset's pair, which is the walk above
                method = sorted(extra.mapping)[0] if extra.mapping else "get"
                request = getattr(factory, method)(f"/api/{prefix}/1/{extra.url_path}/")
                request.user = self.auditor
                view = viewset()
                view.action = extra.__name__
                if all(cls().has_permission(request, view) for cls in declared):
                    open_to_auditor.add((prefix, extra.url_path))
        self.assertEqual(open_to_auditor, set(SELF_SERVICE_ACTIONS), (
            "An @action on a denied collection is reachable by an external auditor. "
            "Setting permission_classes on an action REPLACES the viewset's pair rather "
            "than adding to it, so NotExternalAuditor never runs. Drop them and inherit, "
            "or, if the route really is self-service, add it to SELF_SERVICE_ACTIONS in "
            "accounts/tests_auditor_surface.py with the reason."
        ))

    def test_the_jira_backlog_is_refused_board_by_board(self):
        """The concrete case: board ids are sequential and the queryset is
        pinned to the workspace, so trying 1, 2, 3 was the whole attack."""
        from integrations.models import JiraBoard

        board = JiraBoard.objects.create(board_id=1, name="Security backlog", added_by=self.manager)
        r = self.client_.get(f"/api/integrations/jira/boards/{board.pk}/issues/")
        self.assertEqual(r.status_code, 403, getattr(r, "data", r))
