"""Slack and Teams incoming webhooks. Every POST goes through ``config.outbound``: a bare ``https://`` check would let
a stored URL point the server at its own network (REVIEWS.md (0.9.5 review), S-2)."""
import json
import logging
import threading
import time
import urllib.error
import urllib.request

from django.conf import settings
from django.db import connection, transaction

from config import outbound

logger = logging.getLogger(__name__)

EVENTS = {
    "package.sealed": "A package was sealed",
    "package.issued": "A package was issued to an auditor",
    "package.withdrawn": "A package was withdrawn",
    "pbc.raised": "The auditor raised a request",
    "pbc.returned": "The auditor returned an answer",
    "questionnaire.returned": "A vendor returned their questionnaire",
    "scanner.down": "The malware scanner stopped answering",
    "scanner.up": "The malware scanner is back",
    "document.quarantined": "A stored file was quarantined",
    "digest.daily": "The daily summary",
    "test": "A test message",
}

SEVERITY_EMOJI = {"info": "", "medium": "", "high": ":warning: ", "critical": ":rotating_light: "}


def allowed_hosts(channel):
    key = "WEBHOOK_ALLOWED_HOSTS_SLACK" if channel == "slack" else "WEBHOOK_ALLOWED_HOSTS_TEAMS"
    return [h for h in (getattr(settings, key, None) or []) if h]


def check_url(channel, url):
    """Return the IP to post to, or raise ``outbound.OutboundError``. Checked again before every POST: a stored URL
    can bypass entry validation (the admin, a fixture, a restored backup)."""
    return outbound.assert_safe_url(url, allowed_hosts=allowed_hosts(channel))


def _open(request, timeout, pinned_ip):
    """The one place a webhook POST leaves the process; tests replace it so no run reaches the network."""
    return outbound.opener(pinned_ip).open(request, timeout=timeout)


def installation_channels():
    out = []
    for name, key in (("slack", "SLACK_WEBHOOK_URL"), ("teams", "TEAMS_WEBHOOK_URL")):
        url = (getattr(settings, key, "") or "").strip()
        if url:
            out.append((name, url))
    return out


def workspace_channels(workspace):
    if workspace is None:
        return []
    out = []
    for name, attr in (("slack", "slack_webhook_url"), ("teams", "teams_webhook_url")):
        url = (getattr(workspace, attr, "") or "").strip()
        if url:
            out.append((name, url))
    return out


def channels():
    """``[(name, url)]`` an event raised now goes to. With several workspaces a tenant's event goes only to its own
    channels: the installation's would disclose it to every other tenant unless WEBHOOKS_SHARED_ACROSS_WORKSPACES."""
    from accounts import tenancy

    workspace = tenancy.current()
    own = workspace_channels(workspace)
    if own:
        return own
    if workspace is not None and not getattr(settings, "WEBHOOKS_SHARED_ACROSS_WORKSPACES", False):
        from accounts.models import Workspace
        if Workspace.objects.filter(is_active=True).count() > 1:
            return []
    return installation_channels()


def allowed(event):
    chosen = getattr(settings, "NOTIFY_EVENTS", None)
    if not chosen:
        return event in EVENTS
    return event in EVENTS and (event in chosen or "all" in chosen)


def link(path):
    base = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else ""


def mrkdwn_text(value):
    """Escape the three characters Slack reserves: otherwise a name typed into the public questionnaire (``<!channel>``,
    ``<url|label>``) would mention the whole channel or plant a link."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def slack_payload(title, text, facts=None, url="", severity="info"):
    body = f"{SEVERITY_EMOJI.get(severity, '')}*{mrkdwn_text(title)}*\n{mrkdwn_text(text)}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}}]
    if facts:
        blocks.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*{mrkdwn_text(k)}*\n{mrkdwn_text(v)}"[:200]} for k, v in list(facts)[:10]]})
    if url:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|Open in Conformiti>"}]})
    # The fallback text is mrkdwn too, so it is escaped as well.
    return {"text": f"{mrkdwn_text(title)}: {mrkdwn_text(text)}"[:3000], "blocks": blocks}


def teams_payload(title, text, facts=None, url="", severity="info"):
    body = [
        {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
        {"type": "TextBlock", "text": text, "wrap": True},
    ]
    if facts:
        body.append({"type": "FactSet", "facts": [{"title": str(k), "value": str(v)} for k, v in list(facts)[:10]]})
    card = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
            "version": "1.4", "body": body}
    if url:
        card["actions"] = [{"type": "Action.OpenUrl", "title": "Open in Conformiti", "url": url}]
    return {"type": "message", "attachments": [
        {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}]}


BUILDERS = {"slack": slack_payload, "teams": teams_payload}


def _record(event, channel, ok, code=None, error=""):
    from .models import WebhookDelivery

    try:
        WebhookDelivery.objects.create(event=event[:40], channel=channel[:10], ok=ok,
                                       response_code=code, error=str(error)[:200])
    except Exception:  # pragma: no cover - bookkeeping must never raise
        logger.exception("Failed to record a webhook delivery")


RETRY_DELAY_SECONDS = 2.0
#: Worth a second try; any other 4xx answers the same way again.
_RETRYABLE_HTTP = {408, 429}


def _attempt(request, timeout, pinned):
    """One POST. Returns ``(ok, code, error, retryable)``."""
    try:
        with _open(request, timeout, pinned) as response:
            code = getattr(response, "status", 200)
            return 200 <= code < 300, code, "", False
    except outbound.OutboundError as exc:  # a redirect, after every check passed
        return False, None, f"refused: {exc}", False
    except urllib.error.HTTPError as exc:
        return False, exc.code, f"HTTP {exc.code}", exc.code >= 500 or exc.code in _RETRYABLE_HTTP
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # A connection failure or timeout may pass, so it is retryable; a ValueError (a bad request) is not.
        return False, None, str(exc), not isinstance(exc, ValueError)


def _post(channel, url, payload, event, retry=False):
    """Post one payload and record the outcome once. ``retry`` allows one more attempt after a short pause when the
    first failure may be transient; only the delivery thread sets it, as a synchronous caller wants its answer now."""
    timeout = float(getattr(settings, "WEBHOOK_TIMEOUT", 5))
    if not url.lower().startswith("https://"):
        _record(event, channel, False, None, "refused: webhook URL is not https")
        return False
    # Keep the validated address: the connection is pinned to it, so DNS cannot re-point it before the socket.
    try:
        pinned = check_url(channel, url)
    except outbound.OutboundError as exc:
        _record(event, channel, False, None, f"refused: {exc}")
        return False
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "Conformiti"})
    ok, code, error, retryable = _attempt(request, timeout, pinned)
    if not ok and retry and retryable:
        time.sleep(RETRY_DELAY_SECONDS)
        ok, code, error, _ = _attempt(request, timeout, pinned)
        if not ok:
            error = f"{error} (after one retry)"
    _record(event, channel, ok, code, error)
    return ok


def _deliver(jobs):
    try:
        for channel, url, payload, event in jobs:
            _post(channel, url, payload, event, retry=True)
    finally:
        connection.close()


def post_event(event, title, text, *, facts=None, path="", severity="info", sync=None):
    """Post one event to every configured channel; returns the channels attempted ([] when none is configured or the
    event is not allowed). Asynchronous unless ``sync`` or WEBHOOK_SYNC: it starts when the surrounding transaction
    commits (a rolled-back event is never announced) and gets one retry; synchronously it is one attempt, at once."""
    if not allowed(event):
        return []
    targets = channels()
    if not targets:
        return []
    from accounts import tenancy
    from accounts.models import Workspace

    workspace = tenancy.current()
    if workspace is not None and Workspace.objects.count() > 1:
        title = f"[{workspace.name}] {title}"
    url = link(path) if path else ""
    jobs = [(name, hook, BUILDERS[name](title, text, facts, url, severity), event) for name, hook in targets]
    run_sync = sync if sync is not None else bool(getattr(settings, "WEBHOOK_SYNC", False))
    if run_sync:
        for channel, hook, payload, ev in jobs:
            _post(channel, hook, payload, ev)
    else:
        def start():
            threading.Thread(target=_deliver, args=(jobs,), daemon=True, name="conformiti-webhook").start()

        # robust=True: a failure to start the thread is logged, never raised into the request.
        transaction.on_commit(start, robust=True)
    return [name for name, _ in targets]
