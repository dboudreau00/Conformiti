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
        }
        return Response(body, status=status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE)
