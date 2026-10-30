"""GET /api/health/: unauthenticated and unthrottled so healthchecks and load balancers can poll it."""
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .version import __version__

DEMO_USERNAMES = ("admin", "mia", "owen", "aria", "val")


def demo_accounts_present():
    User = get_user_model()
    return User.objects.filter(
        username__in=DEMO_USERNAMES, email__endswith="@example.com", is_active=True
    ).exists()


def first_admin_needed():
    """True while no active account exists in any workspace, whatever the request or caller has active."""
    from accounts import tenancy

    with tenancy.unscoped():
        return not get_user_model().objects.filter(is_active=True).exists()


def administrator_present():
    """True when an active superuser, or an account whose role manages users, exists in any workspace.
    An auditor role manages nobody whatever it stores, as ``User._cap`` has it."""
    from django.db.models import Q

    from accounts import tenancy

    with tenancy.unscoped():
        return get_user_model().objects.filter(is_active=True).filter(
            Q(is_superuser=True) | Q(role__can_manage_users=True, role__is_auditor=False)
        ).exists()


def scanner_state():
    from documents import monitor

    try:
        state = monitor.probe()
    except Exception:  # pragma: no cover - health must answer regardless
        return {"enabled": True, "reachable": False, "checked_at": None, "latency_ms": None,
                "down_since": None}
    return {
        "enabled": state["enabled"],
        "reachable": state["reachable"],
        "checked_at": state["checked_at"].isoformat() if state.get("checked_at") else None,
        "latency_ms": state.get("latency_ms"),
        "down_since": state["down_since"].isoformat() if state.get("down_since") else None,
    }


def signing_state():
    """The signing key as published. With one active workspace it is that workspace's key; with several it names none
    (``per_workspace``). Never the installation's root key, which signs nothing."""
    from accounts import tenancy
    from accounts.models import Workspace
    from attestations import signing

    try:
        active = list(Workspace.objects.filter(is_active=True).order_by("pk")[:2])
        if len(active) == 1:
            with tenancy.scoped(active[0]):
                info = signing.current_key_info(create=True)
        else:
            info = signing.current_key_info(create=True)
    except Exception:  # pragma: no cover - health must answer regardless
        return {"enabled": True, "key_id": None, "fingerprint": None, "error": "unavailable"}
    several = len(active) > 1
    # Never echo the configuration error: it names the private key's path and this endpoint is unauthenticated.
    return {"enabled": info["enabled"], "algorithm": info["algorithm"],
            "key_id": None if several else info["key_id"],
            "fingerprint": None if several else info["fingerprint"],
            "per_workspace": several,
            "error": "misconfigured" if info.get("error") else None}


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def get(self, request):
        db_ok = True
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        except DatabaseError:
            db_ok = False
        # demo_accounts and first_admin_needed are unauthenticated on purpose: the sign-in screen shows them to the
        # person who can act, and each turns false once it no longer applies (REVIEWS.md (0.9.5 review), S-9).
        body = {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "database": "ok" if db_ok else "unavailable",
            "demo_accounts": demo_accounts_present() if db_ok else None,
            "first_admin_needed": first_admin_needed() if db_ok else None,
            "scanning": scanner_state() if db_ok else None,
            "signing": signing_state(),
        }
        return Response(body, status=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE)
