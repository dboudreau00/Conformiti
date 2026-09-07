from django import forms
from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.admin import UserAdmin
from django.core.cache import cache
from django.core.exceptions import ValidationError

from .models import Role, User, WebAuthnCredential, Workspace


class MfaAdminAuthenticationForm(AdminAuthenticationForm):
    """The admin sign-in, held to the same bar as the application's.

    Django's own form checks a password and nothing else, so an account with
    an authenticator enrolled could still be signed in with the password
    alone -- and the resulting session used to authenticate the whole API.
    This asks for the second factor, honours the archived-workspace refusal,
    and rate-limits attempts per client the way /api/auth/token/ does.
    """

    otp = forms.CharField(
        label="Authentication code", required=False, strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
        help_text="From your authenticator app, or one of your backup codes.",
    )

    ATTEMPTS = 8
    WINDOW = 60  # seconds

    def _throttle_key(self):
        from audit.middleware import _client_ip

        return f"admin-login:{_client_ip(self.request) if self.request else 'unknown'}"

    def clean(self):
        key = self._throttle_key()
        if (cache.get(key) or 0) >= self.ATTEMPTS:
            raise ValidationError("Too many sign-in attempts. Try again in a minute.")
        try:
            cleaned = super().clean()
        except ValidationError:
            cache.set(key, (cache.get(key) or 0) + 1, self.WINDOW)
            raise

        user = self.get_user()
        if user is not None:
            workspace = getattr(user, "workspace", None)
            if workspace is not None and not workspace.is_active and not user.is_superuser:
                raise ValidationError("This workspace is archived.")
            if user.mfa_enabled:
                code = (self.cleaned_data.get("otp") or "").strip()
                device = getattr(user, "mfa_device", None)
                ok = bool(code) and (
                    (device is not None and device.enabled and device.verify(code))
                    or user.verify_backup_code(code)
                )
                if not ok:
                    cache.set(key, (cache.get(key) or 0) + 1, self.WINDOW)
                    from audit.events import record_auth_event

                    record_auth_event(self.request, user, "mfa",
                                      "admin sign-in refused: second factor missing or wrong")
                    raise ValidationError(
                        "Enter the code from your authenticator app, or a backup code."
                    )
        return cleaned


# The admin site is part of the product's attack surface, so it gets the
# product's login rules.
admin.site.login_form = MfaAdminAuthenticationForm
admin.site.login_template = None

admin.site.register(Role)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")


@admin.register(WebAuthnCredential)
class WebAuthnCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "algorithm", "sign_count", "created_at", "last_used_at", "suspect_at")
    readonly_fields = ("credential_id", "public_key", "algorithm", "sign_count", "aaguid",
                       "transports", "created_at", "last_used_at", "suspect_at", "suspect_reason")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Compliance", {"fields": ("role", "job_title")}),)
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")
