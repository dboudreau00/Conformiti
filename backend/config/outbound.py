"""
One safe way to make a server-side HTTPS request.

Anything the application fetches or posts to at an address someone else chose
is a server-side request forgery risk: the server sits inside the deployment
network, where it can reach the database, Redis, the scanner and, on a cloud
host, the instance metadata service. A URL that looks harmless from outside
can point at any of them.

This module is the single implementation of the defence. It was the Jira
client's private code until 0.9.5b, when the per-workspace chat webhooks added
a second caller that had gone without it (see REVIEW_095.md, S-2).

What a caller gets
------------------
``assert_safe_url`` checks a URL and returns the IP address it validated.
``opener`` builds a urllib opener that refuses redirects and connects to that
exact address. Used together, there is no window between the check and the
connection for the answer to change:

* **https only**, because a credential travels on these requests.
* **No credentials in the URL.** ``https://good.example@evil.example/`` is a
  well-known way to make a host check read the wrong half of the string.
* **The host must be on the caller's allow-list**, matched label by label.
  A substring test accepts ``hooks.slack.com.attacker.example``.
* **Every address the host resolves to must be public.** Refusing only
  private IP *literals* misses ``internal.attacker.example``, an ordinary
  name whose A record is 127.0.0.1.
* **The connection is pinned to the validated address**, with TLS still
  verifying the original hostname. Without this, urllib resolves the name a
  second time when it connects, so DNS that answers differently on the second
  ask defeats the check.
* **Redirects are refused.** Following one hands the destination back to the
  other end, after every check above has passed.

Errors carry a ``code`` so a caller can phrase its own message for its own
user without parsing English.
"""
import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request

# Names that are never public, whatever DNS says today. Checked before
# resolving so an internal host is refused even where it does not resolve.
INTERNAL_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")
INTERNAL_NAMES = ("localhost", "localhost.localdomain")


class OutboundError(Exception):
    """A URL was refused. ``code`` says why, so callers can translate.

    Codes: scheme, userinfo, port, host, dns, private, address, redirect.
    """

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect.

    The host and address checks happen before the request is sent. A redirect
    is the other end choosing the next destination after those checks are
    done, which is exactly the hole they exist to close.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OutboundError("redirect", "The endpoint attempted a redirect; refusing it.")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dial a pre-validated IP while TLS still verifies the original name."""

    def __init__(self, host, *args, pinned_ip=None, **kwargs):
        super().__init__(host, *args, **kwargs)
        self._pinned_ip = pinned_ip

    def connect(self):
        sock = socket.create_connection(
            (self._pinned_ip or self.host, self.port), self.timeout, self.source_address
        )
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        server_hostname = self._tunnel_host or self.host
        self.sock = self._context.wrap_socket(sock, server_hostname=server_hostname)


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """urllib HTTPS handler that connects via a pinned IP (see above)."""

    def __init__(self, pinned_ip):
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        # Pass only the handler's SSL context (context=None -> stdlib's secure
        # default, which verifies the cert against the hostname). Mirrors
        # HTTPSHandler.https_open on modern Python.
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(host, pinned_ip=self._pinned_ip, **kw),
            req, context=self._context,
        )


# Ranges the standard library does not call private but a deployment can
# still reach privately. Carrier-grade NAT is the one that matters: several
# hosting providers address tenant networks out of 100.64.0.0/10, so a name
# resolving there is inside somebody's network even though Python says the
# address is a public one.
_ALSO_NOT_PUBLIC = tuple(ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",      # RFC 6598, carrier-grade NAT
    "192.0.0.0/24",       # RFC 6890, IETF protocol assignments
    "198.18.0.0/15",      # RFC 2544, benchmarking
    "64:ff9b::/96",       # RFC 6052, IPv4/IPv6 translation
))


def ip_is_public(ip_str):
    """False for anything the deployment network can reach privately.

    ``is_private`` covers RFC 1918 and, by way of link-local, the
    169.254.169.254 metadata address. It does not cover every range that is
    unreachable from the open internet, so the list above is checked too.
    """
    ip = ipaddress.ip_address(ip_str)
    # ::ffff:100.64.0.1 is 100.64.0.1 wearing an IPv6 address. Python says it
    # is neither private nor in any v4 network, because the version check
    # below would compare a v6 address with a v4 range, so every rule in this
    # function missed it and the range it belongs to is the one hosting
    # providers put tenant networks in (0.9.5f).
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return False
    return not any(ip in network for network in _ALSO_NOT_PUBLIC
                   if ip.version == network.version)


def host_matches(host, allowed):
    """Label-wise match: the host is ``allowed`` itself or a subdomain of it.

    ``"hooks.slack.com" in url`` is the version of this test that lets
    ``hooks.slack.com.attacker.example`` and ``https://x/?hooks.slack.com``
    through, which is how S-2 was found.
    """
    host = (host or "").lower().rstrip(".")
    for entry in allowed or ():
        entry = (entry or "").lower().strip().rstrip(".")
        if entry and (host == entry or host.endswith("." + entry)):
            return True
    return False


def check_shape(url, *, allowed_hosts=None, allowed_ports=(443,),
                deny_internal_names=True, allowed_schemes=("https",)):
    """Everything that can be judged from the URL text alone, returning
    ``(host, port)``.

    Split out from ``assert_safe_url`` so a form can reject a wrong URL the
    moment it is typed without depending on DNS. It is not a safety check on
    its own: only the resolution in ``assert_safe_url`` can tell where a name
    actually points, so that is what runs before a request is sent.
    """
    parsed = urllib.parse.urlparse(url or "")
    # ``allowed_schemes`` is https everywhere except one case: a service the
    # operator runs on their own network, where TLS to a loopback address is
    # not the norm. Widening it is only safe together with the address rules
    # below, never on its own.
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise OutboundError(
            "scheme", f"The URL must start with {allowed_schemes[0]}:// and name a host.")
    if parsed.username or parsed.password:
        raise OutboundError(
            "userinfo", "The URL must not carry a username or password before the host.")
    host = parsed.hostname.lower().rstrip(".")
    try:
        port = parsed.port or 443
    except ValueError:  # a port that is not a number at all
        raise OutboundError("port", "The URL has an invalid port.")
    if allowed_ports is not None and port not in allowed_ports:
        raise OutboundError("port", f"The URL must use port {allowed_ports[0]}.")
    if deny_internal_names and (host in INTERNAL_NAMES or host.endswith(INTERNAL_SUFFIXES)):
        raise OutboundError("host", "The URL must name a public host.")
    if allowed_hosts is not None and not host_matches(host, allowed_hosts):
        raise OutboundError(
            "host", "Expected one of: " + ", ".join(allowed_hosts) + ".")
    return host, port


def proxy_for(url, proxies=None):
    """The proxy this URL would go through, or None.

    An operator who routes egress through one proxy has made that proxy the
    boundary: it is the thing that decides what may be reached, and it is
    where their logging is. Honouring it is not optional, and neither is
    knowing when it applies, because a pinned connection and a proxy are
    mutually exclusive (see ``opener``).
    """
    parsed = urllib.parse.urlparse(url or "")
    scheme, host = parsed.scheme, (parsed.hostname or "")
    if not scheme or not host:
        return None
    available = urllib.request.getproxies() if proxies is None else dict(proxies)
    chosen = available.get(scheme)
    if not chosen:
        return None
    # `no_proxy` names the hosts the operator excluded; a self-hosted model
    # server on the LAN is the obvious one.
    if proxies is None and urllib.request.proxy_bypass(host):
        return None
    return chosen


def assert_safe_url(url, *, allowed_hosts=None, allowed_ports=(443,),
                    deny_internal_names=True, require_public=True,
                    allowed_schemes=("https",)):
    """Validate a URL for a server-side request and return the IP to pin to,
    or None when the request will go through a proxy.

    ``allowed_hosts`` of None means any public host, which is right for a
    URL the operator typed about their own systems (Jira). Pass a list for a
    URL that should only ever address one service (a chat webhook).
    ``allowed_ports`` of None means any port.

    ``require_public=False`` allows an address inside the deployment network.
    It exists for the one honest case: an operator who deliberately runs the
    service being called on their own network, a self-hosted model server
    being the example. It must never be reachable from a setting a tenant
    administrator can change, or it is simply the hole this module closes.
    The connection is still pinned and redirects are still refused.

    **Through a proxy, nothing here is resolved or pinned.** The proxy does
    the resolving, so a check made on this side would describe a connection
    that is not the one being made. The URL's shape is still checked, the
    proxy's own address still is, and redirects are still refused; beyond
    that the operator's proxy is the control, which is what choosing one
    means.
    """
    host, port = check_shape(url, allowed_hosts=allowed_hosts, allowed_ports=allowed_ports,
                             deny_internal_names=deny_internal_names and require_public,
                             allowed_schemes=allowed_schemes)
    proxy = proxy_for(url)
    if proxy:
        # Check the proxy itself: it is the address this process will dial.
        check_shape(proxy, allowed_hosts=None, allowed_ports=None,
                    deny_internal_names=False, allowed_schemes=("http", "https"))
        return None
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise OutboundError("dns", "Could not resolve the host in the URL.")
    pinned = None
    for info in infos:
        addr = info[4][0]
        try:
            public = ip_is_public(addr)
        except ValueError:
            raise OutboundError("address", "The host resolved to an invalid address.")
        # Every answer must be public, not merely the first: a name that
        # resolves to both a public and a private address would otherwise
        # pass on one ordering and fail on another.
        if require_public and not public:
            raise OutboundError("private", "The host must resolve to a public address.")
        if pinned is None:
            pinned = addr
    if pinned is None:
        raise OutboundError("dns", "Could not resolve the host in the URL.")
    return pinned


def opener(pinned_ip, proxy=None):
    """A urllib opener that refuses redirects.

    With ``pinned_ip``, it dials exactly the address ``assert_safe_url``
    checked. With ``proxy`` (or ``pinned_ip`` of None, meaning a proxy applies
    to this URL), it goes through the proxy instead and does **not** pin:
    under a proxy the far end is reached by the proxy, and a handler that
    dialled the target's address itself would step around the operator's
    egress control rather than use it. That is not a theoretical tidy-up. The
    pinning handler replaces the connection wholesale, so combining the two
    silently sends the request to the target's address on the proxy's port.
    """
    if proxy:
        return urllib.request.build_opener(
            NoRedirect, urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if pinned_ip is None:
        # A proxy from the environment applies; let urllib's default
        # ProxyHandler find it, and add nothing that would bypass it.
        return urllib.request.build_opener(NoRedirect)
    return urllib.request.build_opener(NoRedirect, PinnedHTTPSHandler(pinned_ip))
