"""Liveness / readiness endpoint.

``GET /api/health/`` is unauthenticated and unthrottled so container
healthchecks, load balancers and the installers can poll it. It reports the
version, whether the database answers, whether the demo accounts still exist
(the login screen uses that to decide whether to show the demo hint, and
operators can alert on it in production), and whether the installation has no
active account at all yet (the login screen then explains how the first
administrator is created, since nobody can sign in to do it).
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


def first_admin_needed():
    """True while no active account exists anywhere on the installation.

    The sign-in page uses it to explain how the first administrator is
    created (on the server, with createsuperuser), because nobody can sign in
    to create one. Counted across every workspace, whatever the request or
    caller has active: one person able to sign in anywhere means the page has
    nothing to explain.
    """
    from accounts import tenancy

    with tenancy.unscoped():
        return not get_user_model().objects.filter(is_active=True).exists()


def administrator_present():
    """True when an active superuser, or an active account whose role manages
    users, exists in any workspace. The container's boot banner reads it to
    say plainly when nobody can administer the installation. An auditor role
    manages nobody whatever it stores, as User._cap has it."""
    from django.db.models import Q

    from accounts import tenancy

    with tenancy.unscoped():
        return get_user_model().objects.filter(is_active=True).filter(
            Q(is_superuser=True) | Q(role__can_manage_users=True, role__is_auditor=False)
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
        # `demo_accounts` is deliberately still unauthenticated. It is what
        # puts "this installation still has its seeded demo accounts, remove
        # them before real use" on the sign-in screen, where the person who
        # can act on it will actually see it. Hiding it would quietly remove
        # that warning from the one page it belongs on, and the seeded
        # accounts would stay. 0.9.5b stops seeding them by default instead,
        # so an installation has nothing to disclose unless its operator
        # asked for the demo dataset (REVIEW_095.md, S-9).
        # `first_admin_needed` is unauthenticated for the same reason: it is
        # true only while nobody at all can sign in, and it is what tells the
        # person at the sign-in page how the first administrator is made. It
        # turns false with the first active account, so a deployment anyone
        # uses discloses nothing through it.
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
