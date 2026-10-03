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
    an authenticator enrolled could be signed in with the password alone, and
    the resulting session authenticates the whole API. This form asks for the
    second factor, refuses archived workspaces, and rate-limits attempts per
    client the way /api/auth/token/ does.
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
        # Every outcome reaches the audit trail, as an API sign-in does; a
        # rate-limit refusal is recorded once per client and window.
        from audit.events import record_admin_sign_in

        key = self._throttle_key()
        username = (self.data.get("username") or "") if self.data else ""
        if (cache.get(key) or 0) >= self.ATTEMPTS:
            if cache.add(f"{key}:audited", 1, self.WINDOW):
                record_admin_sign_in(self.request, username, "throttled")
            raise ValidationError("Too many sign-in attempts. Try again in a minute.")
        try:
            cleaned = super().clean()
        except ValidationError:
            cache.set(key, (cache.get(key) or 0) + 1, self.WINDOW)
            record_admin_sign_in(self.request, username, "invalid credentials or not a staff account")
            raise

        user = self.get_user()
        if user is not None:
            workspace = getattr(user, "workspace", None)
            if workspace is not None and not workspace.is_active and not user.is_superuser:
                record_admin_sign_in(self.request, username, "workspace archived")
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
        record_admin_sign_in(self.request, username)
        return cleaned


# The admin site is part of the product's attack surface, so it gets the
# product's login rules.
admin.site.login_form = MfaAdminAuthenticationForm
admin.site.login_template = None

admin.site.register(Role)


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at")

    # A workspace is archived, never deleted (the API has no delete either):
    # deleting one takes every row it owns with it, its audit trail included.
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(WebAuthnCredential)
class WebAuthnCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "algorithm", "sign_count", "created_at", "last_used_at", "suspect_at")
    readonly_fields = ("credential_id", "public_key", "algorithm", "sign_count", "aaguid",
                       "transports", "created_at", "last_used_at", "suspect_at", "suspect_reason")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Compliance", {"fields": ("role", "job_title")}),)
    list_display = ("username", "email", "first_name", "last_name", "role", "is_staff")

    def user_change_password(self, request, id, form_url=""):
        """A password set here ends the account's sessions, as it does
        everywhere else, and is written to the trail.

        The admin sets a password on this page only: the change form shows the
        hash read-only, and this view saves through its own form without
        calling ``save_model``, so the session-ending hook lives here. Without
        it, resetting the password of a compromised account would leave
        whoever held it signed in. A saved form answers with a redirect; a
        refused one re-renders.
        """
        from django.contrib.admin.utils import unquote

        response = super().user_change_password(request, id, form_url)
        if request.method == "POST" and response.status_code == 302:
            from accounts.session_views import end_all_sessions
            from audit.events import record_auth_event

            user = self.get_object(request, unquote(id))
            if user is not None:
                revoked = end_all_sessions(user)
                record_auth_event(request, user, "password",
                                  f"password set in the admin by {request.user.get_username()}; "
                                  f"{revoked} refresh token(s) revoked and issued access tokens refused")
        return response
