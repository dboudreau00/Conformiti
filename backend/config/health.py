"""Liveness / readiness endpoint.

``GET /api/health/`` is unauthenticated and unthrottled so container
healthchecks, load balancers and the installers can poll it. It reports the
version, whether the database answers, and whether the demo accounts still
exist (the login screen uses that to decide whether to show the demo hint, and
operators can alert on it in production).
"""
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .version import __version__

DEMO_USERNAMES = ("admin", "mia", "owen", "aria", "val")


def demo_accounts_present():
    """True when any seeded demo account is still active with its demo email."""
    User = get_user_model()
    return User.objects.filter(
        username__in=DEMO_USERNAMES, email__endswith="@example.com", is_active=True
    ).exists()


def scanner_state():
    """The malware scanner as the health endpoint reports it: off, or on and
    reachable/unreachable. Cached for a minute in documents.monitor, so a
    load balancer polling this never hammers clamd."""
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
    """The package-signing key as published: enabled, key id, fingerprint.
    The key is created on first call when a file location is configured."""
    from attestations import signing

    try:
        info = signing.current_key_info(create=True)
    except Exception:  # pragma: no cover - health must answer regardless
        return {"enabled": True, "key_id": None, "fingerprint": None, "error": "unavailable"}
    # Never echo the configuration error itself: it names the path of the
    # private key, and this endpoint answers unauthenticated callers.
    return {"enabled": info["enabled"], "algorithm": info["algorithm"], "key_id": info["key_id"],
            "fingerprint": info["fingerprint"],
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
        body = {
            "status": "ok" if db_ok else "degraded",
            "version": __version__,
            "database": "ok" if db_ok else "unavailable",
            "demo_accounts": demo_accounts_present() if db_ok else None,
            "scanning": scanner_state() if db_ok else None,
            "signing": signing_state(),
        }
        return Response(body, status=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE)
