"""
Minimal Jira Cloud / Server client built on the Python standard library
(urllib) — no new dependencies. Used by the optional Jira integration to pull
issues from specific boards so security work tracked in Jira is visible next
to the controls it supports.

Authentication is HTTP Basic with an Atlassian API token
(email + token — create one at id.atlassian.com → Security → API tokens).
"""
import base64
import http.client
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class JiraError(Exception):
    """Raised for any configuration, network, or Jira-side failure; the
    message is safe to show to the user."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse HTTP redirects. Following them would let a malicious or
    compromised Jira endpoint bounce the server-side request to an internal
    address (SSRF), bypassing the host checks below."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise JiraError("Jira endpoint attempted a redirect; refusing it for security.")


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Dials a pre-validated IP address while keeping TLS SNI and certificate
    verification bound to the original hostname. This closes the DNS-rebind
    (TOCTOU) SSRF gap: without pinning, urllib re-resolves the hostname at
    connect time, so an attacker-controlled DNS record could point the safety-
    checked hostname at an internal IP for the actual connection."""

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


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
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


def _ip_is_public(ip_str):
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _assert_safe_base_url(base_url):
    """Only allow https to a host that resolves exclusively to public IPs, and
    return the validated IP to pin the connection to. Resolving here (not just
    checking IP literals) closes the gap where an internal hostname like
    ``jira.corp.local`` points at a private address; returning the pinned IP
    lets the caller connect to exactly the address we validated."""
    parsed = urllib.parse.urlparse(base_url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise JiraError("Jira base URL must start with https:// (e.g. https://your-team.atlassian.net).")
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".internal"):
        raise JiraError("Jira base URL must be a public host.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise JiraError("Could not resolve the Jira host — check the base URL.")
    pinned = None
    for info in infos:
        addr = info[4][0]
        try:
            if not _ip_is_public(addr):
                raise JiraError("Jira base URL must resolve to a public host.")
        except ValueError:
            raise JiraError("Jira host resolved to an invalid address.")
        if pinned is None:
            pinned = addr
    if pinned is None:
        raise JiraError("Could not resolve the Jira host — check the base URL.")
    return pinned


def _request(config, path, params=None):
    if not config.enabled:
        raise JiraError("The Jira integration is turned off. Enable it in the configuration first.")
    if not (config.base_url and config.email and config.api_token):
        raise JiraError("Jira is not fully configured: base URL, email and API token are all required.")
    pinned_ip = _assert_safe_base_url(config.base_url)

    url = config.base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    token = base64.b64encode(f"{config.email}:{config.api_token}".encode()).decode()
    req = urllib.request.Request(url, headers={
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    })
    # Connect to the exact IP we validated, refusing redirects, so the request
    # can't be bounced to an internal address after the safety check.
    opener = urllib.request.build_opener(_NoRedirect, _PinnedHTTPSHandler(pinned_ip))
    try:
        with opener.open(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise JiraError("Jira rejected the credentials (check the email and API token).")
        if exc.code == 404:
            raise JiraError("Jira returned 404 — check the base URL and board ID.")
        raise JiraError(f"Jira returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise JiraError(f"Could not reach Jira: {getattr(exc, 'reason', exc)}")
    except json.JSONDecodeError:
        raise JiraError("Jira returned a response that wasn't JSON — check the base URL.")


def verify(config):
    """Confirm the credentials work; returns the authenticated account's name."""
    me = _request(config, "/rest/api/3/myself")
    name = me.get("displayName") or me.get("emailAddress") or "unknown account"
    return f"Connected to Jira as {name}."


def board_issues(config, board_id, max_results=50):
    """Fetch issues on a board (Jira Agile API) as slim rows for the UI."""
    data = _request(
        config,
        f"/rest/agile/1.0/board/{int(board_id)}/issue",
        {
            "maxResults": max_results,
            "fields": "summary,status,assignee,priority,issuetype,updated",
        },
    )
    rows = []
    for issue in data.get("issues", []):
        f = issue.get("fields", {}) or {}
        rows.append({
            "key": issue.get("key", ""),
            "summary": f.get("summary", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName") or None,
            "priority": (f.get("priority") or {}).get("name", ""),
            "updated": f.get("updated", ""),
        })
    return {"total": data.get("total", len(rows)), "issues": rows}
