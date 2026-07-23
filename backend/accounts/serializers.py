"""Serializers for users and roles."""
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.crypto import get_random_string
from rest_framework import serializers

from .models import Role

User = get_user_model()


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            "id", "name", "description", "can_manage_users", "can_manage_frameworks",
            "can_manage_documents", "can_manage_folders", "can_view_all",
            "is_auditor", "is_system",
        ]
        read_only_fields = ["is_system"]


class UserSerializer(serializers.ModelSerializer):
    role_detail = RoleSerializer(source="role", read_only=True)
    full_name = serializers.CharField(source="get_full_name", read_only=True)
    capabilities = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "full_name",
            "job_title", "role", "role_detail", "is_active", "capabilities",
            "last_login", "is_superuser", "mfa_enabled",
        ]
        # last_login is already non-editable on the model; is_superuser must
        # never be settable through the API (this serializer is read-path only,
        # but declare it anyway as defence in depth).
        read_only_fields = ["last_login", "is_superuser", "mfa_enabled"]

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
        return instance


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Fields a user may edit about themselves. Role and status are excluded so
    a user can never escalate their own access through the account page."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "job_title"]


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
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


# --------------------------------------------------------------------------
# MFA-aware login
# --------------------------------------------------------------------------
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer  # noqa: E402
from rest_framework.exceptions import AuthenticationFailed  # noqa: E402


class MFATokenObtainPairSerializer(TokenObtainPairSerializer):
    """Standard username/password login, plus a second factor when the account
    has TOTP enabled. Password is verified first (by super()); if MFA is on we
    require a valid `otp` before the tokens are returned — they're only handed
    back on the final `return`, so nothing leaks on the challenge step."""

    def validate(self, attrs):
        data = super().validate(attrs)  # authenticates; sets self.user; builds tokens
        device = getattr(self.user, "mfa_device", None)
        if device and device.enabled:
            otp = (self.initial_data.get("otp") or "").strip()
            if not otp:
                # 400 with a flag the login screen branches on to prompt for a code.
                raise serializers.ValidationError({"mfa_required": True})
            if not device.verify(otp):
                raise AuthenticationFailed("Invalid authentication code.", "mfa_invalid")
        return data
