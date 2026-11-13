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

    def test_an_ipv4_address_inside_an_ipv6_one_is_judged_as_the_ipv4_address(self):
        # 6to4 (2002::/16): the IPv4 address is bits 16 to 48.
        for address in ("2002:0a00:0001::1",        # 10.0.0.1
                        "2002:7f00:0001::",         # 127.0.0.1
                        "2002:a9fe:a9fe::1",        # 169.254.169.254
                        "2002:c0a8:0101::1",        # 192.168.1.1
                        # NAT64 (64:ff9b::/96): the last 32 bits.
                        "64:ff9b::a00:1",           # 10.0.0.1
                        "64:ff9b::7f00:1",          # 127.0.0.1
                        "64:ff9b::a9fe:a9fe",       # 169.254.169.254
                        # IPv4-mapped.
                        "::ffff:10.0.0.1"):
            self.assertFalse(outbound.ip_is_public(address), address)
        for address in ("2002:5db8:d822::1",        # 93.184.216.34
                        "64:ff9b::5db8:d822",       # 93.184.216.34
                        "::ffff:93.184.216.34"):
            self.assertTrue(outbound.ip_is_public(address), address)

    def test_teredo_is_never_public(self):
        for address in ("2001:0:4136:e378:8000:63bf:3fff:fdd2", "2001:0:5ef5:79fd:0:0:0:1"):
            self.assertFalse(outbound.ip_is_public(address), address)
        # The rest of 2001::/16 is ordinary address space.
        self.assertTrue(outbound.ip_is_public("2001:4860:4860::8888"))


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

    def test_an_address_written_the_old_way_is_judged_as_the_address_it_means(self):
        proxied = [mock.patch("config.outbound.urllib.request.getproxies",
                              return_value={"https": self.PROXY}),
                   mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=False)]
        with proxied[0], proxied[1]:
            for host in ("2852039166", "2130706433", "0x7f.1", "127.1", "017700000001",
                         "3232235777", "0"):
                with self.subTest(host=host):
                    with self.assertRaises(outbound.OutboundError) as caught:
                        outbound.assert_safe_url(f"https://{host}/", allowed_hosts=None)
                    self.assertEqual(caught.exception.code, "private")
            self.assertIsNone(outbound.assert_safe_url("https://1561097786/", allowed_hosts=None))
            self.assertIsNone(outbound.assert_safe_url("https://example.com/", allowed_hosts=None))
            self.assertIsNone(outbound.assert_safe_url("https://deadbeef.example/", allowed_hosts=None))

    def test_an_authenticated_proxy_is_accepted_and_an_authenticated_target_is_not(self):
        with mock.patch("config.outbound.urllib.request.getproxies",
                        return_value={"https": "http://user:secret@egress.internal:3128"}), \
                mock.patch("config.outbound.urllib.request.proxy_bypass", return_value=False):
            self.assertIsNone(outbound.assert_safe_url(self.URL, allowed_hosts=None))
            with self.assertRaises(outbound.OutboundError) as caught:
                outbound.assert_safe_url("https://user:secret@api.example.com/v1", allowed_hosts=None)
            self.assertEqual(caught.exception.code, "userinfo")

    def test_a_bypassed_host_is_resolved_and_pinned_as_usual(self):
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


class FallbackAcrossValidatedAddressesTests(TestCase):
    """A name whose first answer cannot be reached (an IPv6 address on a host with no IPv6 route) still connects on a
    later answer the same lookup validated; the name is never resolved a second time."""
    URL = "https://hooks.slack.com/services/T/B/x"
    V6, V4 = "2606:4700::1111", "93.184.216.34"

    def connection(self, pinned):
        return outbound._PinnedHTTPSConnection("hooks.slack.com", 443, timeout=7, pinned_ip=pinned)

    def dial(self, pinned, outcomes):
        """Dial with create_connection answering from ``outcomes`` (an exception is raised, anything else returned)."""
        asked = []

        def create_connection(address, timeout=None, source_address=None):
            asked.append((address, timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        with mock.patch("config.outbound.socket.create_connection", side_effect=create_connection), \
                mock.patch("config.outbound.socket.getaddrinfo") as lookup:
            try:
                sock = self.connection(pinned)._dial()
                error = None
            except OSError as exc:
                sock, error = None, exc
        self.assertFalse(lookup.called, "the name was resolved again")
        return sock, error, asked

    def test_assert_safe_url_still_returns_the_first_address_and_now_carries_all(self):
        with resolving_to(self.V6, self.V4):
            pinned = outbound.assert_safe_url(self.URL, allowed_hosts=SLACK)
        self.assertEqual(pinned, self.V6)
        self.assertEqual(str(pinned), self.V6)
        self.assertIsInstance(pinned, str)
        self.assertEqual(pinned.addresses, (self.V6, self.V4))

    def test_a_repeated_answer_is_tried_once(self):
        with resolving_to(self.V4, self.V4, self.V6):
            pinned = outbound.assert_safe_url(self.URL, allowed_hosts=SLACK)
        self.assertEqual(pinned.addresses, (self.V4, self.V6))

    def test_the_first_address_unreachable_and_the_second_answering_connects_to_the_second(self):
        sentinel = object()
        sock, error, asked = self.dial(
            outbound.PinnedAddress([self.V6, self.V4]),
            [OSError(101, "Network is unreachable"), sentinel])
        self.assertIs(sock, sentinel)
        self.assertIsNone(error)
        self.assertEqual(asked, [((self.V6, 443), 7), ((self.V4, 443), 7)])

    def test_every_address_unreachable_raises_the_last_error(self):
        sock, error, asked = self.dial(
            [self.V6, self.V4],
            [OSError(101, "Network is unreachable"), TimeoutError("timed out")])
        self.assertIsNone(sock)
        self.assertIsInstance(error, TimeoutError)
        self.assertEqual([a for a, _ in asked], [(self.V6, 443), (self.V4, 443)])

    def test_a_single_address_is_dialled_once_and_its_error_is_raised(self):
        sentinel = object()
        sock, error, asked = self.dial(self.V4, [sentinel])
        self.assertIs(sock, sentinel)
        self.assertEqual(asked, [((self.V4, 443), 7)])
        sock, error, asked = self.dial(self.V4, [OSError(111, "Connection refused")])
        self.assertIsNone(sock)
        self.assertEqual(error.errno, 111)
        self.assertEqual(len(asked), 1)

    def test_the_order_of_the_validated_answers_is_kept(self):
        addresses = ["198.51.100.7", self.V6, "203.0.113.9", self.V4]
        failures = [OSError(113, "No route to host")] * 3
        sock, error, asked = self.dial(outbound.PinnedAddress(addresses), failures + [object()])
        self.assertEqual([a[0] for a, _ in asked], addresses)

    def test_no_pinned_address_dials_the_name_as_before(self):
        sock, error, asked = self.dial(None, [object()])
        self.assertEqual(asked, [(("hooks.slack.com", 443), 7)])

    def test_the_opener_hands_the_connection_every_validated_address(self):
        for pinned, expected in ((outbound.PinnedAddress([self.V6, self.V4]), (self.V6, self.V4)),
                                 ([self.V6, self.V4], (self.V6, self.V4)),
                                 (self.V4, (self.V4,))):
            with self.subTest(pinned=pinned):
                handler = next(h for h in outbound.opener(pinned).handlers
                               if isinstance(h, outbound.PinnedHTTPSHandler))
                made = []
                with mock.patch.object(handler, "do_open",
                                       side_effect=lambda factory, req, **kw: made.append(factory("hooks.slack.com"))):
                    handler.https_open(urllib.request.Request(self.URL))
                self.assertEqual(made[0]._pinned_addresses, expected)

    def test_tls_still_verifies_the_original_name_on_whichever_address_answered(self):
        raw = mock.Mock()
        context = mock.Mock()
        connection = outbound._PinnedHTTPSConnection(
            "hooks.slack.com", 443, timeout=7, context=context, pinned_ip=[self.V6, self.V4])
        with mock.patch("config.outbound.socket.create_connection",
                        side_effect=[OSError(101, "Network is unreachable"), raw]):
            connection.connect()
        context.wrap_socket.assert_called_once_with(raw, server_hostname="hooks.slack.com")
