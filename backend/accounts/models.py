"""User and Role models -- the foundation of role-based access control."""
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from config.fieldcrypto import EncryptedCharField


class Role(models.Model):
    """
    A named role with coarse capability flags.

    Folder-level access is granted separately (documents.FolderPermission);
    these flags govern platform-wide capabilities. ``can_view_all`` lets a
    role bypass folder restrictions for read access (e.g. Compliance Manager),
    while ``is_auditor`` marks a read-only external role.
    """
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True)

    can_manage_users = models.BooleanField(default=False)
    can_manage_frameworks = models.BooleanField(default=False)
    can_manage_documents = models.BooleanField(default=False)
    can_manage_folders = models.BooleanField(default=False)
    can_view_all = models.BooleanField(default=False, help_text="Bypass folder restrictions for read access.")
    is_auditor = models.BooleanField(default=False, help_text="Read-only external auditor.")
    is_system = models.BooleanField(default=False, help_text="Built-in role; protected from deletion.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class OidcIdentity(models.Model):
    """A single sign-on identity (issuer + subject) bound to a local account.

    Created by a verified-email match on first SSO login, by auto-provisioning,
    or by hand with ``manage.py link_oidc_identity``. Superuser and staff
    accounts are only ever linked by hand -- see accounts/oidc.py.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oidc_identities"
    )
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    # Set only by `link_oidc_identity --allow-privileged`. A privileged
    # account (superuser, staff, or a role that manages users) signs in
    # through this identity only while this is true -- so promoting a linked
    # user to administrator later closes their SSO path until an operator
    # re-affirms it.
    privileged_ok = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["issuer", "subject"], name="uniq_oidc_identity"),
        ]
        verbose_name_plural = "OIDC identities"

    def __str__(self):
        return f"{self.issuer} / {self.subject} -> {self.user_id}"


class User(AbstractUser):
    """Application user. Every user has an optional single role."""
    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    job_title = models.CharField(max_length=120, blank=True)

    # --- capability helpers (safe when role is None) -----------------------
    def _cap(self, flag):
        return self.is_superuser or bool(self.role and getattr(self.role, flag))

    @property
    def can_manage_users(self):
        return self._cap("can_manage_users")

    @property
    def can_manage_frameworks(self):
        return self._cap("can_manage_frameworks")

    @property
    def can_manage_documents(self):
        return self._cap("can_manage_documents")

    @property
    def can_manage_folders(self):
        return self._cap("can_manage_folders")

    @property
    def can_view_all(self):
        return self._cap("can_view_all")

    @property
    def is_auditor(self):
        return bool(self.role and self.role.is_auditor)

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def mfa_enabled(self):
        device = getattr(self, "mfa_device", None)
        return bool(device and device.enabled)



class MfaDevice(models.Model):
    """A user's TOTP authenticator enrollment. Created disabled at setup and
    flipped to enabled only after the user proves a valid code, so a half-
    finished setup never blocks login."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_device"
    )
    # Base32 TOTP secret, encrypted at rest (config/fieldcrypto.py). The server
    # needs the original to compute the expected code, so it cannot be hashed.
    # Bound to user_id rather than to this row's own id because pre_save runs
    # before the INSERT; max_length is the envelope width, not the secret's.
    secret = EncryptedCharField(max_length=255, aad_from="user_id")
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"MFA({self.user_id}, {'on' if self.enabled else 'pending'})"

    def verify(self, code):
        """Accept a current TOTP code or an unused backup code (consuming it).
        Updates last_used_at on success."""
        from django.contrib.auth.hashers import check_password
        from django.utils import timezone
        from . import mfa as mfa_lib

        code = (code or "").strip()
        if mfa_lib.verify(self.secret, code):
            self.last_used_at = timezone.now()
            self.save(update_fields=["last_used_at"])
            return True

        normalized = mfa_lib.normalize_backup_code(code)
        for backup in self.backup_codes.filter(used_at__isnull=True):
            if check_password(normalized, backup.code_hash):
                backup.used_at = timezone.now()
                backup.save(update_fields=["used_at"])
                self.last_used_at = timezone.now()
                self.save(update_fields=["last_used_at"])
                return True
        return False

    def set_backup_codes(self, codes):
        """Replace all recovery codes with hashes of the given plaintext codes."""
        from django.contrib.auth.hashers import make_password
        from . import mfa as mfa_lib

        self.backup_codes.all().delete()
        MfaBackupCode.objects.bulk_create([
            MfaBackupCode(device=self, code_hash=make_password(mfa_lib.normalize_backup_code(c)))
            for c in codes
        ])


class MfaBackupCode(models.Model):
    """A single-use recovery code (stored only as a hash).

    Deliberately NOT encrypted like MfaDevice.secret. These are already salted
    PBKDF2 hashes, so there is nothing to protect — and leaving them readable
    is what makes a lost encryption key recoverable instead of terminal: a user
    whose TOTP secret can no longer be decrypted can still sign in with a
    backup code, and an administrator can reset their enrollment.
    """
    device = models.ForeignKey(MfaDevice, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=256)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
