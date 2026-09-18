"""Self-service passkey management: list, enrol, rename, remove."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.events import record_auth_event

from . import passkeys
from .models import WebAuthnCredential
from .reauth import reauthenticated  # re-exported: this is where it used to live
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
        # Asked for here rather than at /register/, so nobody is sent to their
        # authenticator only to be turned away after touching it.
        if not reauthenticated(request):
            return Response({"detail": "Confirm your password to add a passkey.",
                             "code": "reauth_required"}, status=403)
        try:
            return Response(passkeys.begin_registration(request.user, request))
        except passkeys.PasskeyRefused as exc:
            return Response({"detail": exc.message, "code": exc.code}, status=400)


class PasskeyRegisterView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        first_factor = not request.user.mfa_enabled
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
        # The account's first second factor comes with its recovery codes,
        # shown once -- exactly as enabling the authenticator app does.
        codes = None
        if first_factor and request.user.backup_codes_remaining == 0:
            codes = request.user.issue_backup_codes()
        return Response({**passkeys.serialize(row), "factors": passkeys.factors(request.user),
                         "backup_codes": codes}, status=201)


class PasskeyDetailView(APIView):
    """PATCH renames; DELETE removes and takes proof the account is yours in the
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
        # Not check_password: an account provisioned through an identity
        # provider has no usable password, so the owner of a passkey their
        # authenticator has reported cloned had no way to take it off. A
        # backup code, or a code from the authenticator app, proves the same
        # thing.
        if not reauthenticated(request):
            return Response({"detail": "Confirm your password, or a code from a factor you still have.",
                             "code": "reauth_required"}, status=403)
        name = row.name
        row.delete()
        if not request.user.mfa_enabled:
            # No second factor left: the codes have nothing to back up.
            request.user.backup_codes.all().delete()
        record_auth_event(request, request.user, "mfa", f"passkey removed: {name}")
        return Response({"removed": pk, "factors": passkeys.factors(request.user)})
