from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NotificationReceipt, WebhookDelivery
from .notifications import build


class ChannelsView(APIView):
    """Which chat channels the deployment posts to (never configured from here); administrators also get the delivery
    log and a test post."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import webhooks

        from accounts import tenancy
        from accounts.models import Workspace

        names = [name for name, _ in webhooks.channels()]
        workspace = tenancy.current()
        own = [name for name, _ in webhooks.workspace_channels(workspace)]
        installation = [name for name, _ in webhooks.installation_channels()]
        body = {
            "slack": "slack" in names, "teams": "teams" in names,
            "source": "workspace" if own else ("installation" if names else "none"),
            "workspace_channels": own,
            "installation_channels": installation,
            "multi_workspace": Workspace.objects.filter(is_active=True).count() > 1,
            "shared_across_workspaces": bool(getattr(settings, "WEBHOOKS_SHARED_ACROSS_WORKSPACES", False)),
            "events": [{"event": e, "label": label, "enabled": webhooks.allowed(e)}
                       for e, label in webhooks.EVENTS.items() if e != "test"],
            "digest": request.user.digest,
            "digest_choices": [{"id": c, "label": label} for c, label in request.user.Digest.choices],
        }
        # WebhookDelivery is installation-wide (not a tenant model), so only a superuser may see it: a workspace
        # administrator would see other organisations' rows.
        if request.user.is_superuser:
            body["deliveries"] = [{
                "event": d.event, "channel": d.channel, "ok": d.ok, "response_code": d.response_code,
                "error": d.error, "at": d.created_at,
            } for d in WebhookDelivery.objects.all()[:10]]
        return Response(body)

    def post(self, request):
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
    """Mark every live notification read; the keys are recomputed server-side, never taken from the client."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        now = timezone.now()
        for item in build(request.user):
            NotificationReceipt.objects.update_or_create(
                user=request.user, key=item["key"], defaults={"seen_at": now},
            )
        return Response({"unread": 0})


class NotificationDismissView(APIView):
    """Dismiss one notification. The key must be in the caller's current feed, or a client could grow the receipt
    table without bound with made-up keys."""
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
