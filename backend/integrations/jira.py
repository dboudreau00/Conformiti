import base64
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request

from config import outbound


MAX_RESPONSE_BYTES = 5 * 1024 * 1024


class JiraError(Exception):
    """Any Jira failure; ``str()`` is safe to show the user."""


# The URL checks live in config/outbound.py (never a second, weaker copy); only the wording is Jira's
# (REVIEWS.md (0.9.5 review), S-2).
_MESSAGES = {
    "scheme": "Jira base URL must start with https:// (e.g. https://your-team.atlassian.net).",
    "userinfo": "Jira base URL must not carry a username or password.",
    "host": "Jira base URL must be a public host.",
    "dns": "Could not resolve the Jira host. Check the base URL.",
    "private": "Jira base URL must resolve to a public host.",
    "address": "Jira host resolved to an invalid address.",
    "redirect": "Jira endpoint attempted a redirect; refusing it for security.",
}


def _translate(exc):
    return JiraError(_MESSAGES.get(exc.code, str(exc)))


# Kept as module names because the integration tests import them.
_ip_is_public = outbound.ip_is_public


def _assert_safe_base_url(base_url):
    """Return the validated IP to pin to. The port is unrestricted: a Jira Server install may use a non-standard one."""
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
    # Dials the validated IP and refuses redirects, so the request cannot be bounced to an internal address.
    sender = outbound.opener(pinned_ip)
    try:
        with sender.open(req, timeout=15) as resp:
            body = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise JiraError("Jira returned a response larger than this app will read.")
        return json.loads(body)
    except outbound.OutboundError as exc:
        raise _translate(exc)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise JiraError("Jira rejected the credentials (check the email and API token).")
        if exc.code == 404:
            raise JiraError("Jira returned 404. Check the base URL and board ID.")
        raise JiraError(f"Jira returned HTTP {exc.code}.")
    except urllib.error.URLError as exc:
        raise JiraError(f"Could not reach Jira: {getattr(exc, 'reason', exc)}")
    except (OSError, http.client.HTTPException) as exc:
        # Neither a timeout while reading the body, IncompleteRead nor a garbled status line is a URLError.
        raise JiraError(f"Could not reach Jira: {exc}")
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        raise JiraError("Jira returned a response that wasn't JSON. Check the base URL.")


def verify(config):
    """Confirm the credentials work and return the message to show the user."""
    me = _request(config, "/rest/api/3/myself")
    name = me.get("displayName") or me.get("emailAddress") or "unknown account"
    return f"Connected to Jira as {name}."


def board_issues(config, board_id, max_results=50):
    data = _request(
        config,
        f"/rest/agile/1.0/board/{int(board_id)}/issue",
        {
            "maxResults": max_results,
            "fields": "summary,status,assignee,priority,issuetype,updated",
        },
    )
    # The browser never sees base_url (manager-only configuration), so each row carries its own link.
    base = config.base_url.rstrip("/")
    rows = []
    for issue in data.get("issues", []):
        f = issue.get("fields", {}) or {}
        key = issue.get("key", "")
        rows.append({
            "key": key,
            "url": f"{base}/browse/{urllib.parse.quote(key)}" if key else "",
            "summary": f.get("summary", ""),
            "type": (f.get("issuetype") or {}).get("name", ""),
            "status": (f.get("status") or {}).get("name", ""),
            "assignee": (f.get("assignee") or {}).get("displayName") or None,
            "priority": (f.get("priority") or {}).get("name", ""),
            "updated": f.get("updated", ""),
        })
    return {"total": data.get("total", len(rows)), "issues": rows}
