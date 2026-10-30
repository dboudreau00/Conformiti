"""The one SSRF defence for server-side requests: ``assert_safe_url`` returns the validated IP and ``opener`` must dial
exactly that address, so nothing can change between the check and the connection (REVIEWS.md (0.9.5 review), S-2)."""
import http.client
import ipaddress
import socket
import urllib.parse
import urllib.request

# Never public whatever DNS says; checked before resolving, so refused even where the name does not resolve.
INTERNAL_SUFFIXES = (".local", ".internal", ".localdomain", ".home.arpa")
INTERNAL_NAMES = ("localhost", "localhost.localdomain")


class OutboundError(Exception):
    """A URL was refused; ``code`` is one of scheme, userinfo, port, host, dns, private, address, redirect."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect: the other end would pick the next destination after the checks have passed."""

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
    def __init__(self, pinned_ip):
        super().__init__()
        self._pinned_ip = pinned_ip

    def https_open(self, req):
        # Only the handler's SSL context (None is the stdlib default, which verifies the cert against the hostname).
        return self.do_open(
            lambda host, **kw: _PinnedHTTPSConnection(host, pinned_ip=self._pinned_ip, **kw),
            req, context=self._context,
        )


# Python calls these public, but a deployment can reach them privately (100.64.0.0/10: hosting tenant networks).
_ALSO_NOT_PUBLIC = tuple(ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",      # RFC 6598, carrier-grade NAT
    "192.0.0.0/24",       # RFC 6890, IETF protocol assignments
    "198.18.0.0/15",      # RFC 2544, benchmarking
    "64:ff9b::/96",       # RFC 6052, IPv4/IPv6 translation
    # Deprecated site-local: Python reports it as global and deprecates ip.is_site_local, so it needs an explicit rule.
    "fec0::/10",          # RFC 3879, site-local
))


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip):
    """The IPv4 address an IPv6 address wraps (mapped, 6to4 or NAT64), or None."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def ip_is_public(ip_str):
    """False for anything the deployment network can reach privately, the metadata address included."""
    ip = ipaddress.ip_address(ip_str)
    # Judge the IPv4 address inside a mapped, 6to4 or NAT64 address: Python does not see through the wrapper.
    embedded = _embedded_ipv4(ip)
    if embedded is not None:
        ip = embedded
    # Teredo hides the client's IPv4 address behind a tunnel. is_private covers 2001::/23 today; this is the second
    # lock on that door, kept so a change to Python's list cannot reopen it.
    elif ip.version == 6 and ip.teredo is not None:
        return False
    if (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
        return False
    return not any(ip in network for network in _ALSO_NOT_PUBLIC
                   if ip.version == network.version)


def host_matches(host, allowed):
    """The host is an entry or a subdomain of one, never a substring match (hooks.slack.com.attacker.example)."""
    host = (host or "").lower().rstrip(".")
    for entry in allowed or ():
        entry = (entry or "").lower().strip().rstrip(".")
        if entry and (host == entry or host.endswith("." + entry)):
            return True
    return False


def check_shape(url, *, allowed_hosts=None, allowed_ports=(443,),
                deny_internal_names=True, allowed_schemes=("https",), allow_userinfo=False):
    """Judge the URL text alone and return ``(host, port)``. Not a safety check by itself:
    only the resolution in ``assert_safe_url`` can tell where a name points."""
    parsed = urllib.parse.urlparse(url or "")
    # https everywhere except an operator's own-network service; widening it is safe only with the address rules below.
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise OutboundError(
            "scheme", f"The URL must start with {allowed_schemes[0]}:// and name a host.")
    # A target carries no credentials; the operator's authenticated egress proxy may (http://user:password@host:port).
    if (parsed.username or parsed.password) and not allow_userinfo:
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


def legacy_ipv4(host):
    """The IPv4 address denoted by a one-number or short dotted host (``2852039166``, ``0x7f.1``, ``127.1``), or None.
    ``ipaddress`` reads only the canonical form; a proxy, like libc, reads these too."""
    if not host or not all(c in "0123456789abcdefx." for c in host):
        return None
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def proxy_for(url, proxies=None):
    """The proxy this URL would go through, or None; pinning and a proxy are mutually exclusive (see ``opener``)."""
    parsed = urllib.parse.urlparse(url or "")
    scheme, host = parsed.scheme, (parsed.hostname or "")
    if not scheme or not host:
        return None
    available = urllib.request.getproxies() if proxies is None else dict(proxies)
    chosen = available.get(scheme)
    if not chosen:
        return None
    if proxies is None and urllib.request.proxy_bypass(host):
        return None
    return chosen


def assert_safe_url(url, *, allowed_hosts=None, allowed_ports=(443,),
                    deny_internal_names=True, require_public=True,
                    allowed_schemes=("https",)):
    """Validate a URL for a server-side request; return the IP to pin to, or None when a proxy will resolve it.
    ``require_public=False`` must never follow a setting a tenant administrator can change, or it reopens the hole."""
    host, port = check_shape(url, allowed_hosts=allowed_hosts, allowed_ports=allowed_ports,
                             deny_internal_names=deny_internal_names and require_public,
                             allowed_schemes=allowed_schemes)
    proxy = proxy_for(url)
    if proxy:
        # Check the proxy itself: it is the address this process will dial.
        check_shape(proxy, allowed_hosts=None, allowed_ports=None,
                    deny_internal_names=False, allowed_schemes=("http", "https"),
                    allow_userinfo=True)
        # A proxy resolves names, not literal addresses: https://169.254.169.254/ must not pass through it unexamined.
        if require_public:
            try:
                literal = ipaddress.ip_address(host.strip("[]"))
            except ValueError:
                literal = legacy_ipv4(host)
            if literal is not None and not ip_is_public(str(literal)):
                raise OutboundError("private", "The host must resolve to a public address.")
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
        # Every answer must be public: a name with both a public and a private address must not pass on one ordering.
        if require_public and not public:
            raise OutboundError("private", "The host must resolve to a public address.")
        if pinned is None:
            pinned = addr
    if pinned is None:
        raise OutboundError("dns", "Could not resolve the host in the URL.")
    return pinned


def opener(pinned_ip, proxy=None):
    """A redirect-refusing urllib opener that dials ``pinned_ip``. Under a proxy (``proxy`` set, or ``pinned_ip`` None)
    it must not pin: pinning replaces the connection and would step around the operator's proxy."""
    if proxy:
        return urllib.request.build_opener(
            NoRedirect, urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    if pinned_ip is None:
        # A proxy from the environment applies: add nothing that would bypass urllib's default ProxyHandler.
        return urllib.request.build_opener(NoRedirect)
    return urllib.request.build_opener(NoRedirect, PinnedHTTPSHandler(pinned_ip))
