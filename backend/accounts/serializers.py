from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.crypto import get_random_string
from rest_framework import serializers

from .models import Role
from .tenancy import CurrentWorkspaceDefault

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    # The hidden field lets the per-workspace unique-name validator answer 400 instead of the database's 500.
    workspace = serializers.HiddenField(default=CurrentWorkspaceDefault())

    CAPABILITIES = ("can_manage_users", "can_manage_frameworks", "can_manage_documents",
                    "can_manage_folders", "can_view_all")

    def validate(self, attrs):
        """An auditor role holds no capabilities: ``PackageGrant`` asks only for ``is_auditor``, so a role that also
        had ``can_view_all`` could be issued an engagement and read the whole programme (M-3)."""
        merged = dict(attrs)
        if self.instance is not None:
            for field in ("is_auditor", *self.CAPABILITIES):
                merged.setdefault(field, getattr(self.instance, field))
        if not (merged.get("is_auditor") and any(merged.get(c) for c in self.CAPABILITIES)):
            return attrs
        # A role that already holds the mix keeps it, so renaming one does not force stripping flags; only introducing
        # the mix is refused. _cap contains existing rows at read time.
        already = self.instance is not None and self.instance.is_auditor and any(
            getattr(self.instance, c) for c in self.CAPABILITIES)
        if already:
            return attrs
        held = ", ".join(c for c in self.CAPABILITIES if merged.get(c))
        raise serializers.ValidationError({
            "is_auditor": "An auditor role holds no capabilities of its own: the "
                          f"engagement is what an auditor is granted. Remove {held}, "
                          "or make this an ordinary role."})

    class Meta:
        model = Role
        fields = [
            "id", "name", "description", "can_manage_users", "can_manage_frameworks",
            "can_manage_documents", "can_manage_folders", "can_view_all",
            "is_auditor", "is_system", "workspace",
        ]
        read_only_fields = ["is_system"]


class UserSerializer(serializers.ModelSerializer):
    role_detail = RoleSerializer(source="role", read_only=True)
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    capabilities = serializers.SerializerMethodField()
    workspace_detail = serializers.SerializerMethodField()
    active_workspace = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "full_name",
            "job_title", "role", "role_detail", "is_active", "capabilities",
            "last_login", "is_superuser", "mfa_enabled", "digest",
            "workspace", "workspace_detail", "active_workspace",
        ]
        # Defence in depth: is_superuser must never be settable through the API, even from a read-path serializer.
        read_only_fields = ["last_login", "is_superuser", "mfa_enabled", "workspace"]

    def get_workspace_detail(self, obj):
        ws = obj.workspace
        return {"id": ws.pk, "name": ws.name, "slug": ws.slug} if ws else None

    def get_active_workspace(self, obj):
        """The workspace this request works in, which differs from the account's own when a superuser has switched."""
        from accounts import tenancy

        ws = tenancy.current()
        if ws is None:
            return None
        return {"id": ws.pk, "name": ws.name, "slug": ws.slug,
                "switched": ws.pk != obj.workspace_id}

    def get_capabilities(self, obj):
        return {
            "manage_users": obj.can_manage_users,
            "manage_frameworks": obj.can_manage_frameworks,
            "manage_documents": obj.can_manage_documents,
            "manage_folders": obj.can_manage_folders,
            "view_all": obj.can_view_all,
            "auditor": obj.is_auditor,
        }


class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    def validate_username(self, value):
        """`username` is unique installation-wide but DRF's validator is workspace-pinned, so a name taken in another
        tenant would fail at the database as a 500 that reveals the account. Checked unscoped, reported blandly."""
        from accounts import tenancy

        # Build the queryset inside the block: built outside, it is pinned to the caller's workspace, and running it
        # unscoped compares the column to NULL and matches nothing, so the name would reach the unique constraint.
        with tenancy.unscoped():
            qs = User.objects.filter(username__iexact=value)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("That username is not available.")
        return value

    def validate_email(self, value):
        """One address, one account per organisation: OIDC linking by verified email gives up (``ambiguous_email``) on
        two matches. Workspace-scoped on purpose: a consultant may hold accounts in two organisations, one address."""
        value = (value or "").strip()
        if not value:
            return value
        qs = User.objects.filter(email__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "Another account in this workspace already uses that address.")
        return value

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "job_title", "role", "is_active", "password",
        ]

    def _validate_password(self, password, user):
        try:
            validate_password(password, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            self._validate_password(password, user)
            user.set_password(password)
        else:
            user.set_password(get_random_string(20))
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for k, v in validated_data.items():
            setattr(instance, k, v)
        if password:
            self._validate_password(password, instance)
            instance.set_password(password)
        instance.save()
        if password:
            # An administrator setting a password is a recovery path for an account that may be in the wrong hands, so
            # it ends the account's sessions, as the person's own change and the MFA reset do.
            from accounts.session_views import end_all_sessions
            from audit.events import record_auth_event

            revoked = end_all_sessions(instance)
            request = self.context.get("request")
            if request is not None:
                by = request.user.get_username() if request.user.is_authenticated else "?"
                record_auth_event(
                    request, instance, "password",
                    f"password set by {by}; {revoked} refresh token(s) revoked")
        return instance


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """What a user may edit about themselves. No role or status (self-escalation), and no ``email``: with
    ``OIDC_LINK_BY_EMAIL`` on, claiming a colleague's address would capture their first SSO sign-in."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "job_title", "digest"]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        user = self.context["request"].user
        try:
            validate_password(value, user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def save(self, **kwargs):
        from accounts.session_views import end_all_sessions

        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        end_all_sessions(user)
        return user


from rest_framework_simplejwt.serializers import TokenObtainPairSerializer  # noqa: E402
from rest_framework.exceptions import APIException, AuthenticationFailed  # noqa: E402


class MfaChallenge(APIException):
    """The password was right and a second factor is now due. ``detail`` is a plain dict, not DRF error details, which
    would stringify every leaf of the WebAuthn options the browser needs untouched."""
    status_code = 400

    def __init__(self, payload):
        self.detail = payload


class MFATokenObtainPairSerializer(TokenObtainPairSerializer):
    """Username/password login plus a second factor when the account has one (``otp`` or ``passkey``). Tokens are
    minted last: the parent's validate persists a refresh token and moves last_login before the factor passes (M-1)."""

    def _authenticate_only(self, attrs):
        """The password check without the tokens: ``TokenObtainSerializer.validate`` (grandparent), addressed through
        the MRO so a SimpleJWT hierarchy change fails loudly instead of silently minting tokens again."""
        return super(TokenObtainPairSerializer, self).validate(attrs)

    def _issue(self):
        """What the parent would have returned, now that a factor has passed."""
        from django.contrib.auth.models import update_last_login
        from rest_framework_simplejwt.settings import api_settings

        refresh = self.get_token(self.user)
        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, self.user)
        return {"refresh": str(refresh), "access": str(refresh.access_token)}

    def validate(self, attrs):
        from . import passkeys

        self._authenticate_only(attrs)  # sets self.user; mints nothing
        user = self.user
        if user.workspace_id and not user.is_superuser and not user.workspace.is_active:
            raise AuthenticationFailed("This workspace is archived.", "workspace_archived")
        device = getattr(user, "mfa_device", None)
        totp_on = bool(device and device.enabled)
        if not (totp_on or user.passkeys.exists()):
            return self._issue()

        request = self.context.get("request")
        otp = (self.initial_data.get("otp") or "").strip()
        assertion = self.initial_data.get("passkey")
        if otp:
            # An authenticator code, or a backup code (a passkey-only person holds those too).
            if not ((totp_on and device.verify(otp)) or user.verify_backup_code(otp)):
                raise AuthenticationFailed("Invalid authentication code.", "mfa_invalid")
            return self._issue()
        if assertion is not None:
            try:
                passkeys.finish_login(user, request, assertion)
            except passkeys.PasskeyRefused as exc:
                from audit.events import record_auth_event
                record_auth_event(request, user, "mfa", f"passkey refused ({exc.code})")
                raise AuthenticationFailed(exc.message, "mfa_invalid")
            return self._issue()
        # 400 with a flag the login screen branches on to prompt for a factor.
        payload = {"mfa_required": True, "factors": passkeys.factors(user)}
        if payload["factors"]["passkey"]:
            payload["passkey"] = passkeys.begin_login(user, request)
        raise MfaChallenge(payload)
