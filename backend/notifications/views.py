"""In-app notification feed: list (with read/dismissed state), mark-read, dismiss."""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationReceipt, WebhookDelivery
from .notifications import build


class ChannelsView(APIView):
    """Which chat channels this deployment posts to (configured by an
    operator, never from here), and -- for administrators -- the last few
    delivery attempts and a test post."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import webhooks

        names = [name for name, _ in webhooks.channels()]
        body = {
            "slack": "slack" in names, "teams": "teams" in names,
            "events": [{"event": e, "label": label, "enabled": webhooks.allowed(e)}
                       for e, label in webhooks.EVENTS.items() if e != "test"],
            "digest": request.user.digest,
            "digest_choices": [{"id": c, "label": label} for c, label in request.user.Digest.choices],
        }
        # The delivery log is installation-wide -- WebhookDelivery is not a
        # tenant model, and the webhook itself is configured by an operator --
        # so a workspace administrator must not see other organisations' rows.
        if request.user.is_superuser:
            body["deliveries"] = [{
                "event": d.event, "channel": d.channel, "ok": d.ok, "response_code": d.response_code,
                "error": d.error, "at": d.created_at,
            } for d in WebhookDelivery.objects.all()[:10]]
        return Response(body)

    def post(self, request):
        """Send a test message to every configured channel, synchronously, so
        the administrator sees the outcome at once."""
        from . import webhooks

        if not (request.user.is_superuser or request.user.can_manage_users):
            return Response({"detail": "Only an administrator can send a test message."}, status=403)
        attempted = webhooks.post_event(
            "test", "Conformiti test message",
            f"Sent by {request.user.get_full_name() or request.user.get_username()} from Settings › Notifications.",
            path="/settings", sync=True)
        if not attempted:
            return Response({"detail": "No Slack or Teams webhook is configured on this server."}, status=400)
        results = [{"channel": d.channel, "ok": d.ok, "response_code": d.response_code, "error": d.error}
                   for d in WebhookDelivery.objects.filter(event="test")[:len(attempted)]]
        return Response({"attempted": attempted, "results": results})


class NotificationListView(APIView):
    """The signed-in user's personalized feed. Dismissed items are hidden;
    each remaining item is annotated read/unread, and `unread` drives the bell
    badge."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = build(request.user)
        keys = [i["key"] for i in items]
        receipts = {
            r.key: r for r in
            NotificationReceipt.objects.filter(user=request.user, key__in=keys)
        }
        results, unread = [], 0
        for item in items:
            receipt = receipts.get(item["key"])
            if receipt and receipt.dismissed_at:
                continue
            read = bool(receipt and receipt.seen_at)
            if not read:
                unread += 1
            results.append({**item, "read": read})
        return Response({"results": results, "unread": unread})


class NotificationMarkReadView(APIView):
    """Mark every currently-live notification as read (recomputed server-side,
    so the client can't mark keys that aren't actually present)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        now = timezone.now()
        for item in build(request.user):
            NotificationReceipt.objects.update_or_create(
                user=request.user, key=item["key"], defaults={"seen_at": now},
            )
        return Response({"unread": 0})


class NotificationDismissView(APIView):
    """Dismiss a single notification by key so it stops appearing. The key
    must belong to the caller's *current* feed — otherwise a client could
    grow the receipt table without bound with made-up keys."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        key = str(request.data.get("key") or "").strip()
        if not key:
            return Response({"detail": "A notification key is required."}, status=400)
        live = {i["key"] for i in build(request.user)}
        if key not in live:
            return Response({"detail": "That notification is not in your feed."}, status=404)
        NotificationReceipt.objects.update_or_create(
            user=request.user, key=key, defaults={"dismissed_at": timezone.now()},
        )
        return Response({"dismissed": key})
