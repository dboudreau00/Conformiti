"""Jira integration: configuration gating, token secrecy and the SSRF guard."""
from integrations.jira import JiraError, _assert_safe_base_url, _ip_is_public
from testutils import APITestBase


class JiraConfigTests(APITestBase):
    def test_config_is_admin_only_and_token_never_returned(self):
        m = self.client_for(self.manager)
        self.assertEqual(m.get("/api/integrations/jira/config/").status_code, 403)
        self.assertEqual(m.patch("/api/integrations/jira/config/", {"enabled": True}, format="json").status_code, 403)
        a = self.client_for(self.admin)
        r = a.patch("/api/integrations/jira/config/", {
            "base_url": "https://team.atlassian.net", "email": "a@b.co", "api_token": "tok", "enabled": True,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("api_token", r.data)
        self.assertTrue(r.data["has_token"])
        # a blank token on a later save keeps the stored one
        r = a.patch("/api/integrations/jira/config/", {"api_token": ""}, format="json")
        self.assertTrue(r.data["has_token"])

    def test_boards_readable_by_all_but_managed_by_admins(self):
        a = self.client_for(self.admin)
        r = a.post("/api/integrations/jira/boards/", {"board_id": 12, "name": "Security backlog"}, format="json")
        self.assertEqual(r.status_code, 201)
        v = self.client_for(self.viewer)
        self.assertEqual(v.get("/api/integrations/jira/boards/").data["count"], 1)
        self.assertEqual(v.post("/api/integrations/jira/boards/", {"board_id": 13, "name": "x"}, format="json").status_code, 403)
        # issues proxy fails cleanly when the integration is off / unconfigured
        r = v.get(f"/api/integrations/jira/boards/{r.data['id']}/issues/")
        self.assertEqual(r.status_code, 502)
        self.assertIn("detail", r.data)


class SsrfGuardTests(APITestBase):
    def test_private_and_non_https_targets_are_refused(self):
        for bad in ("http://team.atlassian.net", "https://localhost", "https://127.0.0.1",
                    "https://jira.corp.local", "https://10.0.0.5", "https://[::1]", "https://169.254.169.254"):
            with self.assertRaises(JiraError, msg=bad):
                _assert_safe_base_url(bad)

    def test_ip_classification(self):
        for private in ("10.1.2.3", "192.168.0.1", "172.16.5.5", "127.0.0.1", "169.254.169.254", "::1", "fe80::1", "0.0.0.0"):
            self.assertFalse(_ip_is_public(private), private)
        for public in ("8.8.8.8", "2606:4700::1111"):
            self.assertTrue(_ip_is_public(public), public)
