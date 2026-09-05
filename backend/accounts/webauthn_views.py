"""Self-service passkey management: list, enrol, rename, remove."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.events import record_auth_event

from . import passkeys
from .models import WebAuthnCredential
from .views import _MfaThrottle


class PasskeyListView(APIView):
    """GET: the caller's passkeys. POST: nothing -- enrolment is two steps
    (``/register/options/`` then ``/register/``)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = request.user.passkeys.all()
        return Response({
            "results": [passkeys.serialize(r) for r in rows],
            "factors": passkeys.factors(request.user),
            "rp_id": passkeys.rp_id(request),
            "max": passkeys.MAX_PASSKEYS,
        })


class PasskeyRegisterOptionsView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        try:
            return Response(passkeys.begin_registration(request.user, request))
        except passkeys.PasskeyRefused as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)


class PasskeyRegisterView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        try:
            row = passkeys.finish_registration(
                request.user, request, request.data.get("state"),
                str(request.data.get("name") or ""), request.data.get("credential"),
            )
        except passkeys.PasskeyRefused as exc:
            record_auth_event(request, request.user, "mfa",
                              f"passkey enrolment refused ({exc.code})")
            return Response({"detail": exc.message, "code": exc.code}, status=400)
        record_auth_event(request, request.user, "mfa", f"passkey enrolled: {row.name}")
        return Response({**passkeys.serialize(row), "factors": passkeys.factors(request.user)},
                        status=201)


class PasskeyDetailView(APIView):
    """PATCH renames; DELETE removes and takes the account password in the
    body, like turning off the authenticator app does, so a hijacked session
    cannot quietly strip a factor -- or clear the suspect mark on a key it
    cloned."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def _get(self, request, pk):
        return WebAuthnCredential.objects.filter(user=request.user, pk=pk).first()

    def patch(self, request, pk):
        row = self._get(request, pk)
        if row is None:
            return Response({"detail": "No such passkey."}, status=404)
        name = str(request.data.get("name") or "").strip()[:80]
        if not name:
            return Response({"detail": "Give the passkey a name."}, status=400)
        row.name = name
        row.save(update_fields=["name"])
        return Response(passkeys.serialize(row))

    def delete(self, request, pk):
        row = self._get(request, pk)
        if row is None:
            return Response({"detail": "No such passkey."}, status=404)
        if not request.user.check_password(request.data.get("password") or ""):
            return Response({"detail": "Password is incorrect."}, status=400)
        name = row.name
        row.delete()
        record_auth_event(request, request.user, "mfa", f"passkey removed: {name}")
        return Response({"removed": pk, "factors": passkeys.factors(request.user)})
