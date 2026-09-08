"""Self-service passkey management: list, enrol, rename, remove."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.events import record_auth_event

from . import passkeys
from .models import WebAuthnCredential
from .views import _MfaThrottle


def reauthenticated(request):
    """Has the caller just proved the account is theirs?

    Removing a passkey takes the account password; adding one used to take
    nothing, so a hijacked session could quietly enrol the attacker's own key
    and keep the account for good. Enrolment now asks for the same proof --
    the password, or a code from a factor already enrolled, which is what an
    account signed in through an identity provider has instead.

    An account with neither (no usable password, no second factor) has
    nothing to prove with and nothing yet to protect: that is the first
    enrolment, and it is allowed.
    """
    user = request.user
    password = request.data.get("password") or ""
    otp = str(request.data.get("otp") or "").strip()
    has_password = user.has_usable_password()
    if has_password and password and user.check_password(password):
        return True
    if otp and user.mfa_enabled:
        device = getattr(user, "mfa_device", None)
        if device is not None and device.enabled and device.verify(otp):
            return True
        if user.verify_backup_code(otp):
            return True
    return not (has_password or user.mfa_enabled)


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
        if not request.user.mfa_enabled:
            # No second factor left: the codes have nothing to back up.
            request.user.backup_codes.all().delete()
        record_auth_event(request, request.user, "mfa", f"passkey removed: {name}")
        return Response({"removed": pk, "factors": passkeys.factors(request.user)})
