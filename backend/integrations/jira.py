"""
Minimal Jira Cloud / Server client built on the Python standard library
(urllib) — no new dependencies. Used by the optional Jira integration to pull
issues from specific boards so security work tracked in Jira is visible next
to the controls it supports.

Authentication is HTTP Basic with an Atlassian API token
(email + token — create one at id.atlassian.com → Security → API tokens).
"""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from config import outbound


class JiraError(Exception):
    """Raised for any configuration, network, or Jira-side failure; the
    message is safe to show to the user."""


# The safety checks below used to live here in full. They moved to
# config/outbound.py in 0.9.5b so the chat webhooks could not ship a second,
# weaker copy of them (REVIEW_095.md, S-2). Jira keeps its own wording.
_MESSAGES = {
    "scheme": "Jira base URL must start with https:// (e.g. https://your-team.atlassian.net).",
    "userinfo": "Jira base URL must not carry a username or password.",
    "host": "Jira base URL must be a public host.",
    "dns": "Could not resolve the Jira host \u2014 check the base URL.",
    "private": "Jira base URL must resolve to a public host.",
    "address": "Jira host resolved to an invalid address.",
    "redirect": "Jira endpoint attempted a redirect; refusing it for security.",
}


def _translate(exc):
    return JiraError(_MESSAGES.get(exc.code, str(exc)))


# Kept as module names because the integration tests import them.
_ip_is_public = outbound.ip_is_public


def _assert_safe_base_url(base_url):
    """Only allow https to a host that resolves exclusively to public IPs, and
    return the validated IP to pin the connection to. A Jira Server install
    may sit on a non-standard port, so the port is not restricted here."""
    try:
        return outbound.assert_safe_url(base_url, allowed_hosts=None, allowed_ports=None)
    except outbound.OutboundError as exc:
        raise _translate(exc)


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
    sender = outbound.opener(pinned_ip)
    try:
        with sender.open(req, timeout=15) as resp:
            return json.load(resp)
    except outbound.OutboundError as exc:
        raise _translate(exc)
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
