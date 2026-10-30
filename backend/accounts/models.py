from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models

from config.fieldcrypto import EncryptedCharField

from .tenancy import TenantModel, TenantUserManager

# The URL an operator types; the columns are wider because they hold the encrypted envelope, not the URL.
MAX_WEBHOOK_URL_LENGTH = 500
MAX_WEBHOOK_COLUMN = 800


def validate_webhook_url(channel, value, error=ValidationError):
    """Return the webhook URL if safe to store, else raise ``error``. Here, not in the serializer, so the admin cannot
    write a URL the API would refuse; the host's address is checked at send time (``notifications.webhooks``)."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) > MAX_WEBHOOK_URL_LENGTH:
        raise error(f"A webhook URL may be at most {MAX_WEBHOOK_URL_LENGTH} characters.")
    from config import outbound
    from notifications import webhooks

    try:
        outbound.check_shape(value, allowed_hosts=webhooks.allowed_hosts(channel))
    except outbound.OutboundError as exc:
        raise error(str(exc))
    return value


class Workspace(models.Model):
    """The tenant: one organisation. A person belongs to exactly one; a superuser may switch between them."""
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    is_active = models.BooleanField(
        default=True, help_text="Archived workspaces refuse sign-in and drop out of every job.")
    # Per organisation: reminders name its documents, vendors and auditor requests, so they cannot share one mailbox.
    notification_email = models.EmailField(
        blank=True,
        help_text="Where this organisation's reminders and alerts go. "
                  "Blank falls back to the installation's COMPLIANCE_TEAM_EMAIL.")
    # Per organisation like the mailbox: a shared channel would show every tenant the others' notifications. Encrypted
    # at rest because an incoming-webhook URL lets its holder post as the app (REVIEWS.md (0.9.5 review), S-3).
    slack_webhook_url = EncryptedCharField(
        max_length=MAX_WEBHOOK_COLUMN, blank=True, aad_from="id",
        help_text="This organisation's Slack incoming webhook. On an installation with "
                  "several organisations, tenant events are posted here or nowhere.")
    teams_webhook_url = EncryptedCharField(
        max_length=MAX_WEBHOOK_COLUMN, blank=True, aad_from="id",
        help_text="This organisation's Teams incoming webhook.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Insert first, then write the webhooks: each is encrypted with this row's id as associated data, which only
        exists after the INSERT. Two writes, and only when a new workspace arrives with a webhook filled in."""
        pending = {}
        if self._state.adding and self.pk is None:
            for field in ("slack_webhook_url", "teams_webhook_url"):
                value = getattr(self, field, "") or ""
                if value:
                    pending[field] = value
                    setattr(self, field, "")
        super().save(*args, **kwargs)
        if pending:
            for field, value in pending.items():
                setattr(self, field, value)
            super().save(update_fields=list(pending), using=kwargs.get("using"))

    def clean(self):
        """Runs on every admin save, the path that skips the API's validators."""
        super().clean()
        errors = {}
        for channel, field in (("slack", "slack_webhook_url"), ("teams", "teams_webhook_url")):
            try:
                setattr(self, field, validate_webhook_url(channel, getattr(self, field, "")))
            except ValidationError as exc:
                errors[field] = exc
        if errors:
            raise ValidationError(errors)


class Role(TenantModel):
    """A named role of coarse capability flags; folder access is granted separately (documents.FolderPermission)."""
    name = models.CharField(max_length=80)
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
        constraints = [
            models.UniqueConstraint(fields=["workspace", "name"], name="uniq_role_name_per_workspace"),
        ]

    def __str__(self):
        return self.name


class OidcIdentity(models.Model):
    """A single sign-on identity (issuer + subject) bound to a local account. Superuser and staff accounts are only
    ever linked by hand (see accounts/oidc.py)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oidc_identities"
    )
    issuer = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    # Set only by `link_oidc_identity --allow-privileged`. A privileged account signs in through this identity only
    # while true, so promoting a linked user to administrator closes their SSO path until an operator re-affirms it.
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
    """A SAML assertion id already accepted, kept until it would have expired: replays are refused from here. A table,
    not a per-process cache, so every worker sees the same history."""
    assertion_id = models.CharField(max_length=255, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.assertion_id


class User(AbstractUser, TenantModel):
    """Application user: one optional role, one workspace. A superuser without a workspace is a platform account."""
    workspace = models.ForeignKey(
        "accounts.Workspace", null=True, blank=True, on_delete=models.CASCADE,
        related_name="users", editable=False,
    )
    objects = TenantUserManager()

    role = models.ForeignKey(
        Role, null=True, blank=True, on_delete=models.SET_NULL, related_name="users"
    )
    job_title = models.CharField(max_length=120, blank=True)

    class Digest(models.TextChoices):
        OFF = "off", "Off"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly (Monday)"

    digest = models.CharField(max_length=8, choices=Digest.choices, default=Digest.OFF)
    digest_sent_at = models.DateTimeField(null=True, blank=True)

    # Access tokens issued before this moment are refused (accounts/cookie_auth.py), so a password reset,
    # forced sign-out or MFA reset ends the session at once instead of leaving a live access token valid for an hour.
    sessions_valid_from = models.DateTimeField(null=True, blank=True, editable=False)

    def _cap(self, flag):
        """Does this account hold a capability? An external auditor holds none, whatever their role stores: a custom
        role with both would otherwise reach every folder and package through the capability short-circuits (M-3)."""
        if self.is_superuser:
            return True
        if self.is_auditor:
            return False
        return bool(self.role and getattr(self.role, flag))

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
        """True when signing in takes a second factor: an authenticator app or any passkey, even a suspect one, which
        cannot satisfy the factor but must not lift it, or cloning a key would leave the account password-only."""
        return self.totp_enabled or self.passkeys.exists()

    @property
    def usable_passkeys(self):
        return self.passkeys.filter(suspect_at__isnull=True)

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
                # Claim with a conditional UPDATE, not read-modify-write: two simultaneous sign-ins would both see the
                # code unused. The UPDATE that matches the still-null row wins.
                claimed = MfaBackupCode.objects.filter(
                    pk=backup.pk, used_at__isnull=True,
                ).update(used_at=timezone.now())
                return bool(claimed)
        return False

    @property
    def backup_codes_remaining(self):
        return self.backup_codes.filter(used_at__isnull=True).count()


class WebAuthnCredential(models.Model):
    """A passkey or security key enrolled as a second factor: public key as a DER SubjectPublicKeyInfo, credential id
    base64url. ``suspect_at`` is set when ``sign_count`` fails to increase (a cloned key); sign-in is then refused."""
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
    """A challenge awaiting its answer. A table, not the cache or session, so every worker can check it; deleted when
    used or expired. ``token_hash`` is the SHA-256 of the opaque ``state`` the client echoes."""
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
    """A user's TOTP enrollment: created disabled and enabled only once a valid code is proved, so a half-finished
    setup never blocks login."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_device"
    )
    # Encrypted, not hashed: the server needs the secret to compute codes. Bound to user_id because pre_save runs
    # before the INSERT; max_length is the envelope width, not the secret's.
    secret = EncryptedCharField(max_length=255, aad_from="user_id")
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    # The last TOTP time step this device accepted. Without it a code stays valid for up to 90 seconds (window plus
    # drift), long enough to replay one taken from a phishing form or a proxied login page.
    last_counter = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f"MFA({self.user_id}, {'on' if self.enabled else 'pending'})"

    def verify(self, code):
        """Accept a current, unspent TOTP code (a backup code is the account's: see ``User.verify_backup_code``). The
        matched step must be later than the last used, claimed by one conditional UPDATE: replays and races fail."""
        from django.utils import timezone
        from . import mfa as mfa_lib

        code = (code or "").strip()
        # A secret the key ring cannot decrypt reads as "". Refused here as
        # well as in matched_counter: an empty key's codes are public.
        if not self.secret:
            return False
        step = mfa_lib.matched_counter(self.secret, code)
        if step is None:
            return False
        claimed = MfaDevice.objects.filter(pk=self.pk, last_counter__lt=step).update(
            last_counter=step, last_used_at=timezone.now())
        if not claimed:
            return False
        self.last_counter = step
        return True


class MfaBackupCode(models.Model):
    """A single-use recovery code, stored as a salted hash and owned by the account, not the authenticator app. Not
    field-encrypted like ``MfaDevice.secret``: a lost encryption key must still leave backup codes usable."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="backup_codes")
    code_hash = models.CharField(max_length=256)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
