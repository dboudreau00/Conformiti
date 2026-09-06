"""
Slack and Microsoft Teams, by incoming webhook.

The tray only helps people who open the app. For the moments that matter --
a package sealed or issued, the auditor returning an answer, a vendor's
questionnaire coming back, the scanner going quiet, a file quarantined --
the same fact is posted to a channel, when one is configured.

Deliberately small: two operator-configured https URLs (``SLACK_WEBHOOK_URL``,
``TEAMS_WEBHOOK_URL``), an allow-list of events (``NOTIFY_EVENTS``), one
POST per event per channel with a short timeout, built on ``urllib`` so no
dependency is added. Posts leave the request path on a thread, never block a
seal on a chat outage, and every attempt is recorded in ``WebhookDelivery``
so "did Slack get it?" has an answer. Nothing is ever *read* from these URLs.
"""
import json
import logging
import threading
import urllib.error
import urllib.request

from django.conf import settings
from django.db import connection

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


def channels():
    """``[(name, url)]`` for every configured channel."""
    out = []
    for name, key in (("slack", "SLACK_WEBHOOK_URL"), ("teams", "TEAMS_WEBHOOK_URL")):
        url = (getattr(settings, key, "") or "").strip()
        if url:
            out.append((name, url))
    return out


def allowed(event):
    chosen = getattr(settings, "NOTIFY_EVENTS", None)
    if not chosen:
        return event in EVENTS
    return event in EVENTS and (event in chosen or "all" in chosen)


def link(path):
    base = (getattr(settings, "PUBLIC_URL", "") or "").rstrip("/")
    return f"{base}{path}" if base else ""


# --------------------------------------------------------------------------- #
# Payloads
# --------------------------------------------------------------------------- #
def slack_payload(title, text, facts=None, url="", severity="info"):
    body = f"{SEVERITY_EMOJI.get(severity, '')}*{title}*\n{text}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": body[:2900]}}]
    if facts:
        blocks.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*{k}*\n{v}"[:200]} for k, v in list(facts)[:10]]})
    if url:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"<{url}|Open in Conformiti>"}]})
    return {"text": f"{title}: {text}"[:3000], "blocks": blocks}


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


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #
def _record(event, channel, ok, code=None, error=""):
    from .models import WebhookDelivery

    try:
        WebhookDelivery.objects.create(event=event[:40], channel=channel[:10], ok=ok,
                                       response_code=code, error=str(error)[:200])
    except Exception:  # pragma: no cover - bookkeeping must never raise
        logger.exception("Failed to record a webhook delivery")


def _post(channel, url, payload, event):
    timeout = float(getattr(settings, "WEBHOOK_TIMEOUT", 5))
    if not url.lower().startswith("https://"):
        _record(event, channel, False, None, "refused: webhook URL is not https")
        return False
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "Conformiti"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced above
            code = getattr(response, "status", 200)
            _record(event, channel, 200 <= code < 300, code)
            return 200 <= code < 300
    except urllib.error.HTTPError as exc:
        _record(event, channel, False, exc.code, f"HTTP {exc.code}")
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _record(event, channel, False, None, str(exc))
    return False


def _deliver(jobs):
    try:
        for channel, url, payload, event in jobs:
            _post(channel, url, payload, event)
    finally:
        connection.close()


def post_event(event, title, text, *, facts=None, path="", severity="info", sync=None):
    """Post one event to every configured channel. Returns the channels
    attempted (an empty list when nothing is configured or the event is not
    in the allow-list). Asynchronous unless ``sync`` (or WEBHOOK_SYNC)."""
    if not allowed(event):
        return []
    targets = channels()
    if not targets:
        return []
    url = link(path) if path else ""
    jobs = [(name, hook, BUILDERS[name](title, text, facts, url, severity), event) for name, hook in targets]
    run_sync = sync if sync is not None else bool(getattr(settings, "WEBHOOK_SYNC", False))
    if run_sync:
        for channel, hook, payload, ev in jobs:
            _post(channel, hook, payload, ev)
    else:
        threading.Thread(target=_deliver, args=(jobs,), daemon=True, name="conformiti-webhook").start()
    return [name for name, _ in targets]
