"""Serializers for users and roles."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.crypto import get_random_string
from rest_framework import serializers

from .models import Role
from .tenancy import CurrentWorkspaceDefault

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    # Names are unique per workspace; the hidden field lets the validator
    # say so (400) instead of the database (500).
    workspace = serializers.HiddenField(default=CurrentWorkspaceDefault())

    CAPABILITIES = ("can_manage_users", "can_manage_frameworks", "can_manage_documents",
                    "can_manage_folders", "can_view_all")

    def validate(self, attrs):
        """An auditor role holds no capabilities.

        The shipped Auditor role is ``is_auditor`` alone and is locked, but a
        custom role was not: any combination stored, and ``PackageGrant`` only
        asks for ``is_auditor``, so a role with ``can_view_all`` beside it
        could be issued an engagement and then read the whole programme. The
        capability short-circuits in documents.access and attestations.access
        now run after the auditor cap, so such a role is contained at read
        time too; this stops another one being made (0.9.5h, M-3).

        Merged with the stored row because PATCH is partial: adding a
        capability to an existing auditor role sends only that one field.
        """
        merged = dict(attrs)
        if self.instance is not None:
            for field in ("is_auditor", *self.CAPABILITIES):
                merged.setdefault(field, getattr(self.instance, field))
        if not (merged.get("is_auditor") and any(merged.get(c) for c in self.CAPABILITIES)):
            return attrs
        # A role that already holds the combination keeps it: renaming or
        # redescribing one must not be refused, and refusing it would amount
        # to making the operator strip flags that this release deliberately
        # does not strip for them. What is refused is introducing the mix --
        # creating one, or flipping either half onto a role that has the
        # other. _cap contains the legacy rows at read time.
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
        # last_login is already non-editable on the model; is_superuser must
        # never be settable through the API (this serializer is read-path only,
        # but declare it anyway as defence in depth).
        read_only_fields = ["last_login", "is_superuser", "mfa_enabled", "workspace"]

    def get_workspace_detail(self, obj):
        ws = obj.workspace
        return {"id": ws.pk, "name": ws.name, "slug": ws.slug} if ws else None

    def get_active_workspace(self, obj):
        """The workspace this REQUEST is working in, which is not the account's
        own when a superuser has switched. The shell shows this one; showing
        the home workspace instead meant a switched superuser saw the wrong
        organisation's name over another organisation's data."""
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
        """`username` is unique across the installation, but the validator DRF
        builds for it is workspace-pinned, so a name taken in another tenant
        used to pass here and fail at the database as a 500 -- telling the
        caller that person has an account somewhere on this installation.
        Checked unscoped, and reported without saying where."""
        from accounts import tenancy

        # Built inside the block, not outside it. A tenant queryset carries
        # `workspace_id = ActiveWorkspace()`, which resolves when the query
        # runs: built out here it was pinned to the caller's workspace, and
        # running it unscoped compared the column to NULL and matched nothing.
        # The check passed, the name reached the database's global unique
        # constraint, and the 500 that came back was the disclosure this was
        # written to remove.
        with tenancy.unscoped():
            qs = User.objects.filter(username__iexact=value)
            if self.instance is not None:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("That username is not available.")
        return value

    def validate_email(self, value):
        """One address, one account, within the organisation.

        Nothing enforced this, and an identity provider linking by verified
        email gives up with ``ambiguous_email`` when two accounts answer to
        one address, which locks that person out of single sign-on. Scoped to
        the workspace on purpose: a consultant may hold an account in two
        organisations on the same installation, under the same address."""
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
            # An administrator setting somebody's password is the recovery
            # path for an account that may already be in the wrong hands.
            # The person's own password change and the MFA reset both revoke
            # every issued refresh token; this path used to leave them all
            # valid, so a hijacked session outlived the reset that was meant
            # to end it.
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
    """Fields a user may edit about themselves. Role and status are excluded so
    a user can never escalate their own access through the account page.

    ``email`` is excluded for a subtler reason. With ``OIDC_LINK_BY_EMAIL`` on,
    which is the default, an identity provider binds its subject to whichever
    local account holds the address it asserts. A self-service edit therefore
    decided who a colleague's first single sign-on would land on: claim an
    address whose owner had not signed in through the provider yet, and their
    first sign-in lands in the claimant's account. Any signed-in caller could
    do it, the issued external auditor included. Changing an address is an
    operator's act, at ``/users/{id}/``, where it is recorded (0.9.5f)."""

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
        # A password change that leaves the old sessions alive is not a
        # password change: every refresh token issued before now is revoked,
        # so a stolen one cannot renew itself indefinitely.
        end_all_sessions(user)
        return user


# --------------------------------------------------------------------------
# MFA-aware login
# --------------------------------------------------------------------------
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer  # noqa: E402
from rest_framework.exceptions import APIException, AuthenticationFailed  # noqa: E402


class MfaChallenge(APIException):
    """The password was right and a second factor is now due.

    Carries a plain dict rather than DRF's error details: the payload holds
    WebAuthn options (integers, nested lists) that must reach the browser
    untouched, and ``_get_error_details`` would stringify every leaf.
    """
    status_code = 400

    def __init__(self, payload):
        self.detail = payload


class MFATokenObtainPairSerializer(TokenObtainPairSerializer):
    """Standard username/password login, plus a second factor when the account
    has one: a TOTP code (``otp``) or a passkey assertion (``passkey``).

    The password is checked first, by the grandparent, which authenticates and
    stops there. Minting happens at the end, after the factor has been
    accepted, because ``TokenObtainPairSerializer.validate`` does both at once:
    calling it first left a refresh token in OutstandingToken, and moved
    last_login, for a session the second factor had not authorised yet. The
    browser never saw that token; a database dump, a replica and the admin do,
    and a signed JWT needs no key ring to use, unlike the TOTP secret stored
    beside it (0.9.5h, M-1).
    """

    def _authenticate_only(self, attrs):
        """The password check, without the tokens.

        ``TokenObtainSerializer.validate`` is the grandparent: it authenticates,
        sets ``self.user`` and returns an empty dict. Addressed through the MRO
        rather than imported, so a SimpleJWT that changes the hierarchy fails
        here loudly rather than silently minting again.
        """
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
            # An authenticator code, or one of the account's backup codes --
            # which a passkey-only person also holds.
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
