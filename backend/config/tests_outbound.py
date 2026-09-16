"""The one place that decides whether the server may make a request.

Two callers depend on this: the Jira client, which has been through it since
0.9.2, and the chat webhooks, which had their own weaker copy until 0.9.5b
(REVIEW_095.md, S-2). Tested here on its own so a change to it cannot be
judged only by whether those two suites still pass.
"""
import urllib.request
from unittest import mock

from django.test import TestCase

from config import outbound

SLACK = ["hooks.slack.com"]


def resolving_to(*addresses):
    return mock.patch("config.outbound.socket.getaddrinfo",
                      return_value=[(2, 1, 6, "", (a, 443)) for a in addresses])


class HostMatchTests(TestCase):
    def test_a_host_matches_itself_and_its_subdomains(self):
        for host in ("hooks.slack.com", "eu.hooks.slack.com", "HOOKS.SLACK.COM", "hooks.slack.com."):
            self.assertTrue(outbound.host_matches(host, SLACK), host)

    def test_and_nothing_that_merely_contains_it(self):
        for host in ("hooks.slack.com.attacker.example", "notslack.com", "slack.com",
                     "xhooks.slack.com", "attacker.example", ""):
            self.assertFalse(outbound.host_matches(host, SLACK), host)


class PublicAddressTests(TestCase):
    def test_the_addresses_a_deployment_can_reach_privately_are_not_public(self):
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.1", "172.16.0.1",
                        "169.254.169.254", "0.0.0.0", "::1", "fd00::1", "100.64.0.1"):
            self.assertFalse(outbound.ip_is_public(address), address)

    def test_and_ordinary_internet_addresses_are(self):
        for address in ("93.184.216.34", "1.1.1.1", "2606:4700::1111"):
            self.assertTrue(outbound.ip_is_public(address), address)


class ShapeTests(TestCase):
    def refused(self, url, code, **kwargs):
        with self.assertRaises(outbound.OutboundError) as caught:
            outbound.check_shape(url, allowed_hosts=SLACK, **kwargs)
        self.assertEqual(caught.exception.code, code, url)

    def test_the_ways_a_url_can_name_someone_elses_host(self):
        self.refused("http://hooks.slack.com/x", "scheme")
        self.refused("ftp://hooks.slack.com/x", "scheme")
        self.refused("https:///x", "scheme")
        self.refused("", "scheme")
        self.refused("https://hooks.slack.com@attacker.example/", "userinfo")
        self.refused("https://user:pw@hooks.slack.com/", "userinfo")
        self.refused("https://hooks.slack.com:8443/x", "port")
        self.refused("https://attacker.example/?hooks.slack.com", "host")
        self.refused("https://hooks.slack.com.attacker.example/x", "host")
        self.refused("https://localhost/x", "host")
        self.refused("https://redis.internal/x", "host")

    def test_the_host_is_read_after_the_at_sign_not_before_it(self):
        """``https://hooks.slack.com@attacker.example/`` addresses
        attacker.example. Credentials in a URL are refused outright rather
        than parsed around, so this never reaches the allow-list at all, but
        the allow-list would reject it too."""
        with self.assertRaises(outbound.OutboundError):
            outbound.check_shape("https://hooks.slack.com@attacker.example/", allowed_hosts=SLACK)
        host, _ = outbound.check_shape("https://attacker.example/",
                                       allowed_hosts=["attacker.example"])
        self.assertEqual(host, "attacker.example")

    def test_a_genuine_url_passes(self):
        host, port = outbound.check_shape("https://hooks.slack.com/services/T/B/x",
                                          allowed_hosts=SLACK)
        self.assertEqual((host, port), ("hooks.slack.com", 443))

    def test_with_no_allow_list_any_public_host_passes(self):
        host, _ = outbound.check_shape("https://team.atlassian.net/rest",
                                       allowed_hosts=None, allowed_ports=None)
        self.assertEqual(host, "team.atlassian.net")


class ResolutionTests(TestCase):
    URL = "https://hooks.slack.com/services/T/B/x"

    def test_the_validated_address_is_the_one_returned_to_connect_to(self):
        with resolving_to("93.184.216.34"):
            self.assertEqual(outbound.assert_safe_url(self.URL, allowed_hosts=SLACK),
                             "93.184.216.34")

    def test_an_allowed_host_pointing_inside_the_network_is_refused(self):
        """The check a name-only allow-list cannot make."""
        for address in ("127.0.0.1", "169.254.169.254", "10.1.2.3"):
            with resolving_to(address):
                with self.assertRaises(outbound.OutboundError) as caught:
                    outbound.assert_safe_url(self.URL, allowed_hosts=SLACK)
                self.assertEqual(caught.exception.code, "private", address)

    def test_one_private_answer_among_public_ones_refuses_the_lot(self):
        with resolving_to("93.184.216.34", "127.0.0.1"):
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url(self.URL, allowed_hosts=SLACK)

    def test_a_private_address_is_allowed_only_when_the_caller_asks(self):
        """For the operator who deliberately runs the far end on their own
        network. The connection is still pinned to the address checked here,
        and the opener still refuses redirects."""
        url = "https://models.internal/v1/chat"
        with resolving_to("10.1.2.3"):
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url(url, allowed_hosts=None)
            self.assertEqual(
                outbound.assert_safe_url(url, allowed_hosts=None, require_public=False),
                "10.1.2.3")

    def test_a_host_that_does_not_resolve_says_so(self):
        import socket as socket_module

        with mock.patch("config.outbound.socket.getaddrinfo",
                        side_effect=socket_module.gaierror("nope")):
            with self.assertRaises(outbound.OutboundError) as caught:
                outbound.assert_safe_url(self.URL, allowed_hosts=SLACK)
        self.assertEqual(caught.exception.code, "dns")


class ProxyTests(TestCase):
    """An operator who routes egress through one proxy has made that proxy
    the boundary. Pinning and proxying cannot both happen: the pinning
    handler replaces the connection, so together they send the request to the
    target's address on the proxy's port, which both breaks the call and
    steps around the control the operator chose."""

    URL = "https://api.example.com/v1"
    PROXY = "http://egress.internal:3128"

    def test_a_proxy_is_recognised_for_the_scheme_that_names_it(self):
        self.assertEqual(outbound.proxy_for(self.URL, {"https": self.PROXY}), self.PROXY)
        self.assertIsNone(outbound.proxy_for(self.URL, {"http": self.PROXY}))
        self.assertIsNone(outbound.proxy_for(self.URL, {}))

    def test_under_a_proxy_nothing_is_resolved_or_pinned(self):
        with mock.patch("config.outbound.urllib.request.getproxies",
                        return_value={"https": self.PROXY}), \
                mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=False), \
                mock.patch("config.outbound.socket.getaddrinfo") as resolved:
            self.assertIsNone(outbound.assert_safe_url(self.URL, allowed_hosts=None))
        resolved.assert_not_called()

    def test_the_url_is_still_checked_and_so_is_the_proxy(self):
        with mock.patch("config.outbound.urllib.request.getproxies",
                        return_value={"https": "not-a-url"}), \
                mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=False):
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url(self.URL, allowed_hosts=None)
        with mock.patch("config.outbound.urllib.request.getproxies",
                        return_value={"https": self.PROXY}), \
                mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=False):
            with self.assertRaises(outbound.OutboundError):
                outbound.assert_safe_url("http://api.example.com/v1", allowed_hosts=None)

    def test_a_bypassed_host_is_resolved_and_pinned_as_usual(self):
        """`no_proxy` names what the operator excluded, a model server on the
        LAN being the obvious case."""
        with mock.patch("config.outbound.urllib.request.getproxies",
                        return_value={"https": self.PROXY}), \
                mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=True), \
                resolving_to("93.184.216.34"):
            self.assertEqual(outbound.assert_safe_url(self.URL, allowed_hosts=None),
                             "93.184.216.34")

    def test_the_opener_never_carries_pinning_and_a_proxy_at_once(self):
        proxied = outbound.opener(None, proxy=self.PROXY)
        self.assertFalse(any(isinstance(h, outbound.PinnedHTTPSHandler)
                             for h in proxied.handlers))
        self.assertTrue(any(isinstance(h, urllib.request.ProxyHandler)
                            for h in proxied.handlers))
        # And no pinned address, no proxy argument: urllib's own proxy
        # handling stays in charge rather than being bypassed.
        from_env = outbound.opener(None)
        self.assertFalse(any(isinstance(h, outbound.PinnedHTTPSHandler)
                             for h in from_env.handlers))


class RedirectTests(TestCase):
    def test_a_redirect_raises_rather_than_being_followed(self):
        handler = outbound.NoRedirect()
        with self.assertRaises(outbound.OutboundError) as caught:
            handler.redirect_request(None, None, 302, "Found", {},
                                     "http://169.254.169.254/latest/meta-data/")
        self.assertEqual(caught.exception.code, "redirect")

    def test_the_opener_carries_both_defences(self):
        opener = outbound.opener("93.184.216.34")
        kinds = [type(h) for h in opener.handlers]
        self.assertIn(outbound.NoRedirect, kinds)
        self.assertTrue(any(isinstance(h, outbound.PinnedHTTPSHandler) for h in opener.handlers))
