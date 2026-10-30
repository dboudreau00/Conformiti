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
from .reauth import reauthenticated
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
        # Built-in roles are the documented baseline: their capability flags cannot be rewritten through the API.
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
        # No change may leave the workspace without an active administrator; dropping can_manage_users from a custom
        # role would otherwise bypass the user-level guard.
        role = serializer.instance
        if (role.can_manage_users
                and serializer.validated_data.get("can_manage_users", True) is False
                and not self._administrator_remains_without(role)):
            raise PermissionDenied(
                "Removing user management from this role would leave no active "
                "administrator. Give another account a role that manages users first."
            )
        serializer.save()

    @staticmethod
    def _administrator_remains_without(role):
        return (
            User.objects.filter(is_active=True)
            .filter(Q(is_superuser=True) | (Q(role__can_manage_users=True) & ~Q(role=role)))
            .exists()
        )

    def perform_destroy(self, instance):
        if instance.is_system:
            raise PermissionDenied("Built-in roles cannot be deleted.")
        if instance.users.exists():
            raise ValidationError(
                {"detail": "This role is assigned to users. Reassign them first."}
            )
        instance.delete()


class UserViewSet(viewsets.ModelViewSet):
    # Ordered because the list is paginated: unordered, a page boundary can repeat or skip a person.
    queryset = User.objects.select_related("role").order_by("username", "pk")
    permission_classes = [CanManageUsers]
    search_fields = ["username", "email", "first_name", "last_name"]
    filterset_fields = ["role", "is_active"]

    def get_serializer_class(self):
        if self.action in ("create", "update", "partial_update"):
            return UserWriteSerializer
        return UserSerializer

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
                raise PermissionDenied("You cannot change your own role. Ask another administrator.")

        deactivating = data.get("is_active") is False
        new_role = data.get("role", target.role)
        loses_admin = (
            target.role and target.role.can_manage_users
            and (new_role is None or not new_role.can_manage_users)
        )
        if (deactivating or loses_admin) and not target.is_superuser:
            if (target.role and target.role.can_manage_users) and not self._other_active_admins(target):
                raise PermissionDenied(
                    "This is the last active administrator. Assign the role to "
                    "someone else before removing it."
                )
        serializer.save()

    @action(detail=True, methods=["post"])
    def reset_mfa(self, request, pk=None):
        target = self.get_object()
        if target.is_superuser and not request.user.is_superuser:
            raise PermissionDenied("Only a superuser can reset a superuser's MFA.")
        device = getattr(target, "mfa_device", None)
        if device:
            device.delete()
        # Passkeys go too: the recovery path for a person whose only remaining key was flagged as cloned.
        removed = target.passkeys.count()
        target.passkeys.all().delete()
        target.backup_codes.all().delete()
        from accounts.session_views import end_all_sessions
        from audit.events import record_auth_event

        # A compromised or lost second factor: the existing sessions go too.
        end_all_sessions(target)
        record_auth_event(request, target, "mfa",
                          f"MFA reset by {request.user.get_username()}: authenticator "
                          f"{'removed' if device else 'absent'}, {removed} passkey(s) removed, "
                          f"sessions revoked")
        return Response({"detail": f"MFA reset for {target.get_username()}.", "mfa_enabled": False})

    def perform_destroy(self, instance):
        actor = self.request.user
        if instance.pk == actor.pk:
            raise PermissionDenied("You cannot delete your own account.")
        if instance.is_superuser:
            raise PermissionDenied("Superuser accounts cannot be deleted through the API. Deactivate instead.")
        if instance.role and instance.role.can_manage_users and not self._other_active_admins(instance):
            raise PermissionDenied("This is the last active administrator and cannot be deleted.")
        instance.delete()

    @action(detail=False, methods=["get", "patch"], permission_classes=[IsAuthenticated])
    def me(self, request):
        """The caller's own profile. PATCH touches only safe fields: role and active status never change here."""
        if request.method == "PATCH":
            ser = ProfileUpdateSerializer(request.user, data=request.data, partial=True)
            ser.is_valid(raise_exception=True)
            ser.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def change_password(self, request):
        ser = PasswordChangeSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response({"detail": "Password updated."})


class LogoutView(APIView):
    """Blacklist the caller's refresh token; the access token expires on its own. Idempotent: an already-revoked or
    malformed token still answers 200, so the client can always finish clearing its local state."""
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
                pass
        record_logout(request)
        return Response({"detail": "Signed out.", "refresh_revoked": revoked})


class _MfaThrottle(SimpleRateThrottle):
    """Per-identity limit on the MFA endpoints. Not ScopedRateThrottle, which reads ``throttle_scope`` from a view and
    would silently not apply to these APIViews."""
    scope = "mfa"

    def get_cache_key(self, request, view):
        if request.user and request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}


def _reauth_required(detail):
    return Response({"detail": detail, "code": "reauth_required"}, status=403)


class MfaStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from . import passkeys

        device = getattr(request.user, "mfa_device", None)
        factors = passkeys.factors(request.user)
        return Response({
            "enabled": bool(device and device.enabled),
            "pending": bool(device and not device.enabled),
            "backup_codes_remaining": request.user.backup_codes_remaining,
            "passkeys": request.user.passkeys.count(),
            "passkeys_suspect": factors["passkey_suspect"],
            # Whether signing in takes a second factor at all.
            "second_factor": request.user.mfa_enabled,
        })


class MfaSetupView(APIView):
    """Begin enrollment: (re)issue a pending secret and its otpauth URI; the device stays disabled until verified."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        device = getattr(request.user, "mfa_device", None)
        if device and device.enabled:
            return Response({"detail": "MFA is already enabled. Disable it first to re-enroll."}, status=400)
        # Asked here as well as at /verify/, so nobody scans a QR code only to be turned away. Without it a hijacked
        # session could enrol the attacker's authenticator and lock the owner out. A passkey enrolment asks the same.
        if not reauthenticated(request):
            return _reauth_required("Confirm your password to set up an authenticator.")
        secret = mfa_lib.generate_secret()
        if device:
            device.secret = secret
            device.confirmed_at = None
            device.save(update_fields=["secret", "confirmed_at"])
        else:
            device = MfaDevice.objects.create(user=request.user, secret=secret)
        account = request.user.email or request.user.get_username()
        return Response({
            "secret": secret,
            "otpauth_uri": mfa_lib.otpauth_uri(secret, account),
        })


class MfaVerifyView(APIView):
    """Confirm a code to switch MFA on; returns the backup codes, shown exactly once."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        device = getattr(request.user, "mfa_device", None)
        if not device:
            return Response({"detail": "Start setup first."}, status=400)
        if device.enabled:
            return Response({"detail": "MFA is already enabled."}, status=400)
        if not reauthenticated(request):
            return _reauth_required("Confirm your password to turn on the authenticator.")
        code = (request.data.get("code") or "").strip()
        # device.verify, not mfa_lib.verify: it spends the time step, so the code that switched the factor on cannot
        # be replayed to sign in.
        if not device.verify(code):
            return Response({"detail": "That code isn't valid. Check your authenticator and try again."}, status=400)
        from django.utils import timezone
        device.enabled = True
        device.confirmed_at = timezone.now()
        device.save(update_fields=["enabled", "confirmed_at"])
        # Codes belong to the account: unused ones from a passkey enrolment are kept, not silently replaced.
        codes = None
        if request.user.backup_codes_remaining == 0:
            codes = request.user.issue_backup_codes()
        from audit.events import record_auth_event

        record_auth_event(request, request.user, "mfa",
                          "authenticator app enrolled" + ("; backup codes issued" if codes else ""))
        return Response({"enabled": True, "backup_codes": codes,
                         "backup_codes_remaining": request.user.backup_codes_remaining})


class MfaDisableView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        if not reauthenticated(request):
            return _reauth_required("Confirm your password, or a code from a factor you still have.")
        device = getattr(request.user, "mfa_device", None)
        if device:
            device.delete()
        # With no second factor left, backup codes have nothing to back up.
        codes_gone = not request.user.passkeys.exists()
        if codes_gone:
            request.user.backup_codes.all().delete()
        from audit.events import record_auth_event

        record_auth_event(request, request.user, "mfa",
                          ("authenticator app removed" if device else "authenticator app off (none enrolled)")
                          + ("; backup codes deleted" if codes_gone else ""))
        return Response({"enabled": False})


class MfaBackupCodesView(APIView):
    """Regenerate backup codes, invalidating the old set, for anyone with a second factor (app or passkey)."""
    permission_classes = [IsAuthenticated]
    throttle_classes = [_MfaThrottle]

    def post(self, request):
        if not request.user.mfa_enabled:
            return Response({"detail": "Enrol an authenticator app or a passkey first."}, status=400)
        if not reauthenticated(request):
            return _reauth_required("Confirm your password, or a code from a factor you still have.")
        codes = request.user.issue_backup_codes()
        from audit.events import record_auth_event

        record_auth_event(request, request.user, "mfa",
                          "backup codes regenerated (the previous set no longer works)")
        return Response({"backup_codes": codes})
