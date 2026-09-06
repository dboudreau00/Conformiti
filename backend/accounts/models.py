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


class SsoAssertion(models.Model):
    """A SAML assertion id that has been accepted, kept until it would have
    expired anyway. Replays are refused from here -- a shared table, not a
    per-process cache, so every worker sees the same history."""
    assertion_id = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.assertion_id


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
    def totp_enabled(self):
        device = getattr(self, "mfa_device", None)
        return bool(device and device.enabled)

    @property
    def mfa_enabled(self):
        """Does signing in take a second factor? True with an enrolled
        authenticator app or ANY passkey -- including one marked suspect: a
        suspect passkey cannot satisfy the factor, but it must not make the
        requirement disappear either, or cloning a key would be the way to
        drop an account to password-only."""
        return self.totp_enabled or self.passkeys.exists()

    @property
    def usable_passkeys(self):
        return self.passkeys.filter(suspect_at__isnull=True)

    # --- backup codes: the recovery factor, owned by the account rather than
    # by the authenticator app since 0.6.1, so a passkey-only person has them
    # too. Stored as salted hashes; single use.
    def set_backup_codes(self, codes):
        from django.contrib.auth.hashers import make_password
        from . import mfa as mfa_lib

        self.backup_codes.all().delete()
        MfaBackupCode.objects.bulk_create([
            MfaBackupCode(user=self, code_hash=make_password(mfa_lib.normalize_backup_code(c)))
            for c in codes
        ])

    def issue_backup_codes(self):
        from . import mfa as mfa_lib

        codes = mfa_lib.generate_backup_codes()
        self.set_backup_codes(codes)
        return codes

    def verify_backup_code(self, code):
        """Consume an unused backup code. False for anything else."""
        from django.contrib.auth.hashers import check_password
        from django.utils import timezone
        from . import mfa as mfa_lib

        normalized = mfa_lib.normalize_backup_code(code)
        if not normalized:
            return False
        for backup in self.backup_codes.filter(used_at__isnull=True):
            if check_password(normalized, backup.code_hash):
                backup.used_at = timezone.now()
                backup.save(update_fields=["used_at"])
                return True
        return False

    @property
    def backup_codes_remaining(self):
        return self.backup_codes.filter(used_at__isnull=True).count()


class WebAuthnCredential(models.Model):
    """One passkey or security key enrolled as a second factor.

    The public key is stored as a DER SubjectPublicKeyInfo; the credential id
    is the authenticator's own, base64url. ``sign_count`` is the last counter
    value the authenticator reported; ``suspect_at`` is set the moment a
    later assertion fails to increase it (a cloned key), after which the
    credential refuses every sign-in until the person removes it with their
    password and enrols afresh.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="passkeys"
    )
    name = models.CharField(max_length=80)
    credential_id = models.CharField(max_length=1400, unique=True)
    public_key = models.BinaryField()
    algorithm = models.SmallIntegerField(help_text="COSE algorithm identifier.")
    sign_count = models.PositiveBigIntegerField(default=0)
    aaguid = models.CharField(max_length=36, blank=True)
    transports = models.JSONField(default=list, blank=True)
    backup_eligible = models.BooleanField(default=False)
    backup_state = models.BooleanField(default=False)
    user_verified = models.BooleanField(
        default=False, help_text="The authenticator verified the person (PIN/biometric) at enrolment.")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    suspect_at = models.DateTimeField(null=True, blank=True)
    suspect_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"Passkey({self.user_id}, {self.name!r})"

    @property
    def is_usable(self):
        return self.suspect_at is None


class WebAuthnChallenge(models.Model):
    """A challenge handed to a browser, waiting for its answer.

    Kept in the database rather than the cache (per-process by default) or
    the session (a login carries none in header mode): every worker must be
    able to check the answer, and the row is deleted the moment it is used or
    has expired. ``token_hash`` is the SHA-256 of the opaque ``state`` the
    client echoes, so a row is only reachable by the browser that asked.
    """
    class Purpose(models.TextChoices):
        REGISTER = "register", "Enrol a passkey"
        LOGIN = "login", "Sign in"

    token_hash = models.CharField(max_length=64, unique=True)
    challenge = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="webauthn_challenges"
    )
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.purpose} challenge for {self.user_id}"


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
        """Accept a current TOTP code (a backup code is the account's, not
        the device's: see ``User.verify_backup_code``). Updates last_used_at
        on success."""
        from django.utils import timezone
        from . import mfa as mfa_lib

        code = (code or "").strip()
        if mfa_lib.verify(self.secret, code):
            self.last_used_at = timezone.now()
            self.save(update_fields=["last_used_at"])
            return True
        return False


class MfaBackupCode(models.Model):
    """A single-use recovery code (stored only as a hash).

    Owned by the account, not by the authenticator app: it is the way back
    in when the app is lost OR when the only passkey is lost or flagged.

    Deliberately NOT encrypted like MfaDevice.secret. These are already salted
    PBKDF2 hashes, so there is nothing to protect — and leaving them readable
    is what makes a lost encryption key recoverable instead of terminal: a user
    whose TOTP secret can no longer be decrypted can still sign in with a
    backup code, and an administrator can reset their enrollment.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=256)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
