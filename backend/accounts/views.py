"""User and role API views, self-service MFA, and sign-out."""
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from .models import MfaDevice, Role
from . import mfa as mfa_lib
from .permissions import CanManageUsers
from .serializers import (
    PasswordChangeSerializer,
    ProfileUpdateSerializer,
    RoleSerializer,
    UserSerializer,
    UserWriteSerializer,
)

User = get_user_model()


class RoleViewSet(viewsets.ModelViewSet):
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = [CanManageUsers]

    def perform_update(self, serializer):
        # Built-in roles are the documented baseline the demo, docs and access
        # reviews refer to; their capability flags can't be silently rewritten
        # through the API (create a custom role instead).
        if serializer.instance.is_system:
            changed = {
                k for k, v in serializer.validated_data.items()
                if k.startswith(("can_", "is_")) and getattr(serializer.instance, k) != v
            }
            if changed:
                raise PermissionDenied(
                    "Capability flags on built-in roles are fixed. Create a custom role "
                    "with the flags you need and assign it instead."
                )
        serializer.save()

    def perform_destroy(self, instance):
        if instance.is_system:
            raise PermissionDenied("Built-in roles cannot be deleted.")
        if instance.users.exists():
            raise ValidationError(
                {"detail": "This role is assigned to users — reassign them first."}
            )
        instance.delete()


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.select_related("role").all()
    permission_classes = [CanManageUsers]
    search_fields = ["username", "email", "first_name", "last_name"]
    filterset_fields = ["role", "is_active"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteSerializer
        return UserSerializer

    # ---- lockout / privilege guards ----------------------------------------
    # These make the admin panel safe to hand to alpha testers: you cannot
    # remove your own access, touch a superuser without being one, or strip
    # the last remaining administrator.

    def _other_active_admins(self, excluding):
        return (
            User.objects.filter(is_active=True)
            .exclude(pk=excluding.pk)
            .filter(Q(is_superuser=True) | Q(role__can_manage_users=True))
            .exists()
        )

    def perform_update(self, serializer):
        target = serializer.instance
        actor = self.request.user
        data = serializer.validated_data

        if target.is_superuser and not actor.is_superuser:
            raise PermissionDenied("Only a superuser can modify a superuser account.")

        if target.pk == actor.pk:
            if "is_active" in data and data["is_active"] is False:
                raise PermissionDenied("You cannot deactivate your own account.")
            if "role" in data and data["role"] != target.role:
                raise PermissionDenied("You cannot change your own role — ask another administrator.")

        # Never allow the org to end up with zero active administrators.
        deactivating = data.get("is_active") is False
        new_role = data.get("role", target.role)
        loses_admin = (
            target.role and target.role.can_manage_users
            and (new_role is None or not new_role.can_manage_users)
        )
        if (deactivating or loses_admin) and not target.is_superuser:
            if (target.role and target.role.can_manage_users) and not self._other_active_admins(target):
                raise PermissionDenied(
                    "This is the last active administrator — assign the role to "
                    "someone else before removing it."
                )
        serializer.save()

    @action(detail=True, methods=["post"])
    def reset_mfa(self, request, pk=None):
        """Admin lockout recovery: remove a user's MFA enrollment so they can
        re-enroll (e.g. lost device with no backup codes left)."""
        target = self.get_object()
        if target.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("Only a superuser can reset a superuser's MFA.")
        device = getattr(target, "mfa_device", None)
        if device:
            device.delete()
        # Passkeys go too: this is the recovery path for a person whose only
        # remaining key was flagged as cloned.
        removed = target.passkeys.count()
        target.passkeys.all().delete()
        from audit.events import record_auth_event
        record_auth_event(request, target, "mfa",
                          f"MFA reset by {request.user.get_username()}: authenticator "
                          f"{'removed' if device else 'absent'}, {removed} passkey(s) removed")
        return Response({"detail": f"MFA reset for {target.get_username()}.", "mfa_enabled": False})

    def perform_destroy(self, instance):
        actor = self.request.user
        if instance.pk == actor.pk:
            raise PermissionDenied("You cannot delete your own account.")
        if instance.is_superuser:
            raise PermissionDenied("Superuser accounts cannot be deleted through the API — deactivate instead.")
        if instance.role and instance.role.can_manage_users and not self._other_active_admins(instance):
            raise PermissionDenied("This is the last active administrator and cannot be deleted.")
        instance.delete()

    @action(detail=False, methods=["get", "patch"], permission_classes=[IsAuthenticated])
    def me(self, request):
        """Return, or update, the currently authenticated user's own profile.

        PATCH only touches safe self-editable fields (name, email, job title);
        role and active status can never be changed here.
        """
        if request.method == "PATCH":
            ser = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
            ser.is_valid(raise_exception=True)
            ser.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def change_password(self, request):
        """Change the authenticated user's own password (verifies the current one)."""
        ser = PasswordChangeSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"detail": "Password updated."})


# ==========================================================================
# Sign-out: revoke the refresh token server-side
# ==========================================================================
class LogoutView(APIView):
    """Blacklist the caller's refresh token so it cannot mint further access
    tokens. The (short-lived) access token expires on its own. Idempotent: an
    already-revoked or malformed token still returns 200 so the client can
    always finish clearing its local state."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from audit.events import record_logout

        refresh = request.data.get("refresh")
        revoked = False
        if refresh:
            try:
                RefreshToken(refresh).blacklist()
                revoked = True
            except TokenError:
                revoked = False
        record_logout(request)
        return Response({"detail": "Signed out.", "refresh_revoked": revoked})


# ==========================================================================
# Multi-factor authentication (TOTP) — self-service enable/disable + admin reset
# ==========================================================================
class _MfaThrottle(SimpleRateThrottle):
    """Per-identity limit on the MFA setup/verify/disable endpoints.

    Subclasses SimpleRateThrottle so its ``scope`` binds directly to the
    THROTTLE_MFA rate. (ScopedRateThrottle reads its scope from a view
    ``throttle_scope`` attribute these APIViews don't set, which would silently
    disable the limit.)"""
    scope = "mfa"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


class MfaStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import passkeys

        device = getattr(request.user, "mfa_device", None)
        factors = passkeys.factors(request.user)
        return Response({
            "enabled": bool(device and device.enabled),
            "pending": bool(device and not device.enabled),
            "backup_codes_remaining": (
                device.backup_codes.filter(used_at__isnull=True).count() if device and device.enabled else 0
            ),
            "passkeys": request.user.passkeys.count(),
            "passkeys_suspect": factors["passkey_suspect"],
            # Whether signing in takes a second factor at all.
            "second_factor": request.user.mfa_enabled,
        })


class MfaSetupView(APIView):
    """Begin enrollment: (re)issue a pending secret and its otpauth URI. The
    device stays disabled until the user confirms a code at /mfa/verify/."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        device = getattr(request.user, "mfa_device", None)
        if device and device.enabled:
            return Response({"detail": "MFA is already enabled. Disable it first to re-enroll."}, status=400)
        secret = mfa_lib.generate_secret()
        if device:
            device.secret = secret
            device.confirmed_at = None
            device.save(update_fields=["secret", "confirmed_at"])
            device.backup_codes.all().delete()
        else:
            device = MfaDevice.objects.create(user=request.user, secret=secret)
        account = request.user.email or request.user.get_username()
        return Response({
            "secret": secret,
            "otpauth_uri": mfa_lib.otpauth_uri(secret, account),
        })


class MfaVerifyView(APIView):
    """Confirm a code to switch MFA on, and return one-time backup codes
    (shown exactly once)."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        device = getattr(request.user, "mfa_device", None)
        if not device:
            return Response({"detail": "Start setup first."}, status=400)
        if device.enabled:
            return Response({"detail": "MFA is already enabled."}, status=400)
        code = (request.data.get("code") or "").strip()
        if not mfa_lib.verify(device.secret, code):
            return Response({"detail": "That code isn't valid — check your authenticator and try again."}, status=400)
        from django.utils import timezone
        device.enabled = True
        device.confirmed_at = timezone.now()
        device.save(update_fields=["enabled", "confirmed_at"])
        codes = mfa_lib.generate_backup_codes()
        device.set_backup_codes(codes)
        return Response({"enabled": True, "backup_codes": codes})


class MfaDisableView(APIView):
    """Turn MFA off. Requires the account password (re-auth) to prevent a
    hijacked session from silently removing the second factor."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        if not request.user.check_password(request.data.get("password") or ""):
            return Response({"detail": "Password is incorrect."}, status=400)
        device = getattr(request.user, "mfa_device", None)
        if device:
            device.delete()
        return Response({"enabled": False})


class MfaBackupCodesView(APIView):
    """Regenerate backup codes (invalidates the old set). Password-gated."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        device = getattr(request.user, "mfa_device", None)
        if not (device and device.enabled):
            return Response({"detail": "Enable MFA first."}, status=400)
        if not request.user.check_password(request.data.get("password") or ""):
            return Response({"detail": "Password is incorrect."}, status=400)
        codes = mfa_lib.generate_backup_codes()
        device.set_backup_codes(codes)
        return Response({"backup_codes": codes})
