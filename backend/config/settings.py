import os
import secrets
import sys
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from config import keyfile

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(key, default=False):
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_int(key, default):
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{key} must be an integer (got {os.getenv(key)!r})")


def env_int_list(key, default):
    raw = os.getenv(key, default)
    try:
        return [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise ImproperlyConfigured(f"{key} must be comma-separated integers (got {raw!r})")


# --- Core -------------------------------------------------------------------
# Off unless asked for: a bare-metal run with no .env must not start in debug.
DEBUG = env_bool("DJANGO_DEBUG", False)

_INSECURE_KEY = "dev-insecure-change-me"
# Every placeholder published in the repo is refused: SECRET_KEY also signs the JWTs,
# so a published value would let anyone mint tokens for any account.
_PLACEHOLDER_KEYS = {
    _INSECURE_KEY,
    "change-me-to-a-long-random-string",
    "changeme",
    "secret",
}


def _load_secret_key():
    explicit = (os.getenv("DJANGO_SECRET_KEY") or "").strip()
    # Placeholders are ignored here, so a copied .env.example never wins over the key file.
    if explicit and explicit.lower() not in _PLACEHOLDER_KEYS:
        return explicit
    key_file = (os.getenv("DJANGO_SECRET_KEY_FILE") or "").strip()
    if key_file:
        path = Path(key_file)
        try:
            if path.exists():
                stored = path.read_text(encoding="utf-8").strip()
                if len(stored) >= 32:
                    return stored
                if stored:
                    # Never replace a key that has content: sessions, JWTs and the derived field key rest on it.
                    raise ImproperlyConfigured(
                        f"DJANGO_SECRET_KEY_FILE={key_file!r} holds fewer than 32 characters. "
                        "Restore the key it held, or delete the file to have a new one generated "
                        "(which signs everyone out and makes encrypted secrets unreadable)."
                    )
            # Via keyfile.publish, never a direct write: workers booting together must end up with one key.
            held = keyfile.publish(path, secrets.token_urlsafe(64) + "\n").strip()
            if len(held) >= 32:
                return held
            raise ImproperlyConfigured(
                f"DJANGO_SECRET_KEY_FILE={key_file!r} was created by another process "
                "but holds no usable key.")
        except OSError as exc:
            raise ImproperlyConfigured(
                f"DJANGO_SECRET_KEY_FILE={key_file!r} is not readable/writable: {exc}"
            )
    return explicit or _INSECURE_KEY


SECRET_KEY = _load_secret_key()
if not DEBUG and (SECRET_KEY.strip().lower() in _PLACEHOLDER_KEYS or len(SECRET_KEY.strip()) < 32):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong, unique value when DEBUG is off "
        "(or point DJANGO_SECRET_KEY_FILE at a writable path to have one generated). "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
    )

# --- Field encryption (secrets at rest) -------------------------------------
_FIELD_KEY_FILE_DEFAULT = BASE_DIR / ".field-encryption-key"


def _load_field_encryption_keys():
    explicit = (os.getenv("DJANGO_FIELD_ENCRYPTION_KEY") or "").strip()
    if explicit:
        keys = [k.strip() for k in explicit.split(",") if k.strip()]
        if keys:
            return keys, "env"

    key_file = (os.getenv("DJANGO_FIELD_ENCRYPTION_KEY_FILE") or "").strip()
    # A placeholder or short SECRET_KEY never derives the ring, DEBUG or not: a published key encrypts nothing.
    derivable = (
        SECRET_KEY.strip().lower() not in _PLACEHOLDER_KEYS
        and len(SECRET_KEY.strip()) >= 32
    )
    if not key_file and not derivable:
        key_file = str(_FIELD_KEY_FILE_DEFAULT)

    if key_file:
        path = Path(key_file)
        try:
            if path.exists():
                stored = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
                if stored:
                    return stored, "file"
            # Via keyfile.publish, never a direct write: a loser's O_TRUNC write would orphan the others' ciphertext.
            held = keyfile.publish(path, secrets.token_urlsafe(32) + "\n")
            stored = [ln.strip() for ln in held.splitlines() if ln.strip()]
            if not stored:
                raise ImproperlyConfigured(
                    f"DJANGO_FIELD_ENCRYPTION_KEY_FILE={key_file!r} holds no usable key.")
            return stored, "file"
        except OSError as exc:
            raise ImproperlyConfigured(
                f"DJANGO_FIELD_ENCRYPTION_KEY_FILE={key_file!r} is not readable/writable: {exc}"
            )

    # Derived: changing SECRET_KEY makes the encrypted columns unreadable (INSTALL.md: moving the ring off it).
    return ["derived:" + SECRET_KEY.strip()], "secret-key"


FIELD_ENCRYPTION_KEYS, FIELD_ENCRYPTION_KEY_SOURCE = _load_field_encryption_keys()

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    # Before django.contrib.auth: the first app with a command wins, and accounts replaces
    # createsuperuser with one that never offers to bypass the password policy.
    "accounts",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    "compliance",
    "documents",
    "calendar_app",
    "notifications",
    "audit",
    "analytics",
    "governance",
    "integrations",
    "attestations",
    "vendors",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Must precede the audit middleware, which writes a tenant row.
    "accounts.tenancy.WorkspaceMiddleware",
    "audit.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Searched before the apps', so templates/admin/login.html replaces the admin's password-only sign-in.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    },
]

# --- Database ---------------------------------------------------------------
if os.getenv("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB"),
            "USER": os.getenv("POSTGRES_USER", "postgres"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.getenv("SQLITE_PATH") or (BASE_DIR / "db.sqlite3")),
        }
    }

# --- Cache (throttle counters live here) ------------------------------------
_cache_url = os.getenv("CACHE_URL", "").strip()
if _cache_url:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _cache_url,
            "KEY_PREFIX": "conformiti",
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    if not DEBUG:
        import warnings

        warnings.warn(
            "CACHE_URL is not set, so the rate limits (the login throttle included) are "
            "counted in each process's own memory: under gunicorn with several workers each "
            "one counts separately and the real limit is that many times the configured one. "
            "Set CACHE_URL to a Redis database (for example redis://localhost:6379/2 beside "
            "a local Redis) so every worker shares one count.",
            RuntimeWarning, stacklevel=2,
        )

AUTH_USER_MODEL = "accounts.User"
PASSWORD_MIN_LENGTH = env_int("PASSWORD_MIN_LENGTH", 12)
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     # PCI DSS v4.0.1 requirement 8.3.6 asks for at least 12 characters.
     "OPTIONS": {"min_length": PASSWORD_MIN_LENGTH}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- i18n / static ----------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Media / document storage ----------------------------------------------
USE_S3 = env_bool("USE_S3")
if USE_S3:
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    AWS_STORAGE_BUCKET_NAME = os.getenv("AWS_STORAGE_BUCKET_NAME")
    AWS_S3_REGION_NAME = os.getenv("AWS_REGION", "us-east-1")
    AWS_S3_FILE_OVERWRITE = False
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = True
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT") or (BASE_DIR / "media"))

# nginx enforces the same ceiling (client_max_body_size): keep the two in step.
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 32)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

COMPLIANCE_TREE_ROOT = os.getenv(
    "COMPLIANCE_TREE_ROOT", str(BASE_DIR.parent / "compliance-data")
)

# --- Malware scanning for uploaded evidence ---------------------------------
CLAMAV_ENABLED = env_bool("CLAMAV_ENABLED", False)
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = env_int("CLAMAV_PORT", 3310)
CLAMAV_TIMEOUT = env_int("CLAMAV_TIMEOUT", 10)
CLAMAV_CONNECT_TIMEOUT = env_int("CLAMAV_CONNECT_TIMEOUT", 3)
# Must stay at or below clamd's StreamMaxLength (docker/clamd.conf).
CLAMAV_MAX_BYTES = env_int("CLAMAV_MAX_MB", 40) * 1024 * 1024

# --- Evidence packages (the auditor workspace) ------------------------------
ATTESTATION_GRANT_DAYS = env_int("ATTESTATION_GRANT_DAYS", 45)
ATTESTATION_GRANT_MAX_DAYS = env_int("ATTESTATION_GRANT_MAX_DAYS", 180)

# --- Serving uploaded evidence ----------------------------------------------
# Defaults ON with DEBUG off, and then something in front must act on X-Accel-Redirect (the shipped nginx does);
# where nothing does, set MEDIA_INTERNAL=false or every download is an empty file and nothing logs an error.
MEDIA_INTERNAL = env_bool("MEDIA_INTERNAL", not DEBUG)
MEDIA_ACCEL_PREFIX = os.getenv("MEDIA_ACCEL_PREFIX", "/protected-media/")

# --- Control readiness scoring ----------------------------------------------
READINESS_WEIGHTS = {
    "implementation": env_int("SCORE_W_IMPLEMENTATION", 35),
    "owner": env_int("SCORE_W_OWNER", 10),
    "evidence": env_int("SCORE_W_EVIDENCE", 20),
    "freshness": env_int("SCORE_W_FRESHNESS", 20),
    "testing": env_int("SCORE_W_TESTING", 15),
    "risk_penalty": env_int("SCORE_W_RISK_PENALTY", 20),
}
# Ascending lower bounds for the at-risk / nearly / ready bands.
READINESS_BANDS = env_int_list("READINESS_BANDS", "40,70,90")
if len(READINESS_BANDS) != 3 or sorted(READINESS_BANDS) != READINESS_BANDS \
        or len(set(READINESS_BANDS)) != 3 or not all(0 <= b <= 100 for b in READINESS_BANDS):
    raise ImproperlyConfigured(
        "READINESS_BANDS must be three strictly ascending integers in 0..100, "
        f"e.g. '40,70,90' (got {os.getenv('READINESS_BANDS')!r}). A malformed value "
        "would otherwise take the whole control register down on first read."
    )
READINESS_FRESH_DAYS = env_int("READINESS_FRESH_DAYS", 30)
CONTROL_TEST_INTERVAL_DAYS = env_int("CONTROL_TEST_INTERVAL_DAYS", 365)

# --- DRF / auth -------------------------------------------------------------
REST_FRAMEWORK = {
    # SessionAuthentication is DEBUG-only, like the browsable API: in production an admin session
    # (password-only login) would authenticate every /api/ endpoint.
    "DEFAULT_AUTHENTICATION_CLASSES": (
        ["accounts.cookie_auth.CookieJWTAuthentication",
         "rest_framework.authentication.SessionAuthentication"]
        if DEBUG else ["accounts.cookie_auth.CookieJWTAuthentication"]
    ),
    # A view's own permission_classes replace this pair, auditor refusal included; the engagement's
    # routes rely on that, and accounts/tests_auditor_surface.py walks the routers and holds the line.
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
        "accounts.permissions.NotExternalAuditor",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_PARSER_CLASSES": (
        "config.parsers.ObjectJSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ),
    "DEFAULT_METADATA_CLASS": "config.metadata.NoDescriptionMetadata",
    # Always set: DRF's unset default trusts the whole X-Forwarded-For header, so a caller could dodge every throttle.
    # Too low shares one bucket among visitors; too high keys the limits on an entry the client writes.
    "NUM_PROXIES": int(os.getenv("NUM_PROXIES", "1")),
    # Anonymous traffic only: authenticated users are not globally throttled, so the SPA stays responsive.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON", "30/min"),
        "login": os.getenv("THROTTLE_LOGIN", "8/min"),
        "mfa": os.getenv("THROTTLE_MFA", "10/min"),
        "refresh": os.getenv("THROTTLE_REFRESH", "30/min"),
        "package_work": os.getenv("THROTTLE_PACKAGE_WORK", "6/min"),
        "package_verify": os.getenv("THROTTLE_PACKAGE_VERIFY", "60/min"),
        "questionnaire": os.getenv("THROTTLE_QUESTIONNAIRE", "20/min"),
    },
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer", "rest_framework.renderers.BrowsableAPIRenderer"]
        if DEBUG else ["rest_framework.renderers.JSONRenderer"]
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    "LEEWAY": env_int("JWT_LEEWAY_SECONDS", 30),
    # Rotation plus blacklist makes a stolen refresh token single-use; sign-out revokes it server-side.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Keep each user's last_login current so access reviews reflect real activity.
    "UPDATE_LAST_LOGIN": True,
}

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# --- Email -------------------------------------------------------------------
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "console" if DEBUG else "ses")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "compliance@example.com")
COMPLIANCE_TEAM_EMAIL = os.getenv("COMPLIANCE_TEAM_EMAIL", DEFAULT_FROM_EMAIL)

# --- Slack / Microsoft Teams ------------------------------------------------------
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "").strip()
TEAMS_WEBHOOK_URL = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
# Off keeps tenant events in each workspace's own channels; shared, every tenant sees the others' package names.
WEBHOOKS_SHARED_ACROSS_WORKSPACES = env_bool("WEBHOOKS_SHARED_ACROSS_WORKSPACES", False)
NOTIFY_EVENTS = [e.strip() for e in os.getenv("NOTIFY_EVENTS", "").split(",") if e.strip()]
WEBHOOK_TIMEOUT = env_int("WEBHOOK_TIMEOUT", 5)
# SSRF allow-list, matched label by label (the host itself or a subdomain of an entry): a webhook URL is a
# request the server makes wherever it points, so never widen an entry to a bare domain.
WEBHOOK_ALLOWED_HOSTS_SLACK = [
    h.strip() for h in os.getenv("WEBHOOK_ALLOWED_HOSTS_SLACK", "hooks.slack.com").split(",")
    if h.strip()]
# Teams issues webhook URLs on the retiring Office 365 connector hosts and, for Workflows, on logic.azure.com.
WEBHOOK_ALLOWED_HOSTS_TEAMS = [
    h.strip() for h in os.getenv(
        "WEBHOOK_ALLOWED_HOSTS_TEAMS",
        "webhook.office.com,outlook.office.com,outlook.office365.com,logic.azure.com",
    ).split(",") if h.strip()]
WEBHOOK_SYNC = env_bool("WEBHOOK_SYNC", False)

# SES
AWS_SES_REGION = os.getenv("AWS_SES_REGION", os.getenv("AWS_REGION", "us-east-1"))
AWS_SES_CONFIGURATION_SET = os.getenv("AWS_SES_CONFIGURATION_SET", "")

# Standard mailbox account (EMAIL_PROVIDER=mailbox).
MAILBOX_PROTOCOL = os.getenv("MAILBOX_PROTOCOL", "imap").lower()   # "imap" or "pop3"
MAILBOX_HOST = os.getenv("MAILBOX_HOST", "")
MAILBOX_PORT = env_int("MAILBOX_PORT", 993 if MAILBOX_PROTOCOL == "imap" else 995)
MAILBOX_USERNAME = os.getenv("MAILBOX_USERNAME", "")
MAILBOX_PASSWORD = os.getenv("MAILBOX_PASSWORD", "")
MAILBOX_USE_SSL = env_bool("MAILBOX_USE_SSL", True)
MAILBOX_SAVE_SENT = env_bool("MAILBOX_SAVE_SENT", True)
MAILBOX_SENT_FOLDER = os.getenv("MAILBOX_SENT_FOLDER", "Sent")
MAILBOX_TIMEOUT = env_int("MAILBOX_TIMEOUT", 30)
MAILBOX_SMTP_HOST = os.getenv("MAILBOX_SMTP_HOST", "")
MAILBOX_SMTP_PORT = env_int("MAILBOX_SMTP_PORT", 587)
MAILBOX_SMTP_USERNAME = os.getenv("MAILBOX_SMTP_USERNAME", "")
MAILBOX_SMTP_PASSWORD = os.getenv("MAILBOX_SMTP_PASSWORD", "")
MAILBOX_SMTP_USE_TLS = env_bool("MAILBOX_SMTP_USE_TLS", True)
MAILBOX_SMTP_USE_SSL = env_bool("MAILBOX_SMTP_USE_SSL", False)

# SMTP (only used when EMAIL_PROVIDER=smtp)
if EMAIL_PROVIDER == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
    EMAIL_PORT = env_int("EMAIL_PORT", 587)
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
    EMAIL_TIMEOUT = env_int("EMAIL_TIMEOUT", 30)
elif EMAIL_PROVIDER == "console":
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

REVIEW_ALERT_LEAD_DAYS = env_int_list("REVIEW_ALERT_LEAD_DAYS", "30,14,7,1")

# --- Celery -----------------------------------------------------------------
from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
REVIEW_SCAN_HOUR = env_int("REVIEW_SCAN_HOUR", 6)
if not 0 <= REVIEW_SCAN_HOUR <= 23:
    raise ImproperlyConfigured(f"REVIEW_SCAN_HOUR must be an hour from 0 to 23 (got {REVIEW_SCAN_HOUR}).")
CELERY_BEAT_SCHEDULE = {
    "scan-document-reviews-daily": {
        "task": "notifications.tasks.scan_document_reviews",
        "schedule": crontab(hour=REVIEW_SCAN_HOUR, minute=0),
    },
    "record-readiness-snapshot-daily": {
        "task": "analytics.tasks.record_readiness_snapshot",
        "schedule": crontab(hour=REVIEW_SCAN_HOUR, minute=5),
    },
    "flush-expired-jwt-blacklist-weekly": {
        "task": "accounts.tasks.flush_expired_tokens",
        "schedule": crontab(day_of_week="sunday", hour=3, minute=30),
    },
    "watch-malware-scanner-hourly": {
        "task": "notifications.tasks.watch_scanner",
        "schedule": crontab(minute=17),
    },
    # The emailed digests, after the review scan has refreshed the trays.
    "send-notification-digests-daily": {
        "task": "notifications.tasks.send_digests",
        "schedule": crontab(hour=REVIEW_SCAN_HOUR, minute=20),
    },
}


# --- Security hardening ------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

BEHIND_TLS = env_bool("BEHIND_TLS", not DEBUG)
if BEHIND_TLS:
    # Only where the operator says a TLS terminator is in front: otherwise any client could send
    # `X-Forwarded-Proto: https` and make request.is_secure() true (OIDC/SAML URLs, passkey origins).
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Health checks arrive over plain HTTP on the internal hop: redirected, the backend never turns healthy.
# The endpoint carries no credentials and sets no cookie.
SECURE_REDIRECT_EXEMPT = [r"^api/health/$"]
if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", BEHIND_TLS)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", BEHIND_TLS)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", BEHIND_TLS)
    # HSTS: opt-in via env so it is not switched on before TLS is ready.
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)

if BEHIND_TLS and not DEBUG and os.getenv("NUM_PROXIES") is None:
    # Warn only while unset: advising 2 to a deliberate 1 would key the limits on a client-written address.
    import warnings

    warnings.warn(
        "BEHIND_TLS is on and NUM_PROXIES is not set, so every rate limit is keyed on the "
        "address one proxy back along X-Forwarded-For. Set NUM_PROXIES to the number of "
        "proxies between the client and Django: 1 when this host's own nginx terminates "
        "TLS and passes requests straight to Django, 2 when a separate TLS terminator sits "
        "in front of the shipped nginx.",
        RuntimeWarning, stacklevel=2,
    )

# --- Authentication transport -----------------------------------------------
AUTH_TRANSPORT = os.getenv("AUTH_TRANSPORT", "cookie").strip().lower()
if AUTH_TRANSPORT not in ("header", "cookie"):
    raise ImproperlyConfigured(
        f"AUTH_TRANSPORT must be 'header' or 'cookie' (got {AUTH_TRANSPORT!r}). "
        "A typo here would fall back to header auth and undo the hardening it "
        "was set for."
    )
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE", BEHIND_TLS)
AUTH_COOKIE_ACCESS = os.getenv("AUTH_COOKIE_ACCESS", "").strip()
AUTH_COOKIE_REFRESH = os.getenv("AUTH_COOKIE_REFRESH", "").strip()
# Scoped to the one endpoint that consumes it: /api/auth/ also serves the TOTP secret and the backup codes.
AUTH_COOKIE_REFRESH_PATH = "/api/auth/token/"
# The __Host- prefix needs a Secure cookie, which is only defined with DEBUG off.
CSRF_COOKIE_NAME = "__Host-csrftoken" if globals().get("CSRF_COOKIE_SECURE") else "csrftoken"

# --- Single sign-on (OpenID Connect) -------------------------------------------
# Environment only, on purpose: a provider configurable from the UI could be pointed at an administrator's own IdP.
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip().rstrip("/")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "").strip()
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_SCOPES = os.getenv("OIDC_SCOPES", "openid email profile").strip() or "openid email profile"
OIDC_LABEL = os.getenv("OIDC_LABEL", "Single sign-on").strip() or "Single sign-on"
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "").strip()
OIDC_ALLOWED_DOMAINS = [
    d.strip().lower().lstrip("@") for d in os.getenv("OIDC_ALLOWED_DOMAINS", "").split(",") if d.strip()
]
OIDC_AUTO_PROVISION = env_bool("OIDC_AUTO_PROVISION", False)
SSO_WORKSPACE = os.getenv("SSO_WORKSPACE", "default").strip() or "default"
OIDC_DEFAULT_ROLE = os.getenv("OIDC_DEFAULT_ROLE", "Viewer").strip() or "Viewer"
OIDC_LINK_BY_EMAIL = env_bool("OIDC_LINK_BY_EMAIL", True)
OIDC_REQUIRE_VERIFIED_EMAIL = env_bool("OIDC_REQUIRE_VERIFIED_EMAIL", True)
if OIDC_ISSUER and not OIDC_ISSUER.startswith("https://") and not DEBUG:
    raise ImproperlyConfigured("OIDC_ISSUER must be an https:// URL.")

# --- Single sign-on (SAML 2.0) ---------------------------------------------------
# Environment only; the IdP's signing certificate is the trust anchor, so there is no metadata auto-fetch.
SAML_IDP_ENTITY_ID = os.getenv("SAML_IDP_ENTITY_ID", "").strip()
SAML_IDP_SSO_URL = os.getenv("SAML_IDP_SSO_URL", "").strip()
SAML_IDP_CERT = os.getenv("SAML_IDP_CERT", "").strip()
SAML_IDP_CERT_FILE = os.getenv("SAML_IDP_CERT_FILE", "").strip()
if not SAML_IDP_CERT and SAML_IDP_CERT_FILE:
    try:
        SAML_IDP_CERT = Path(SAML_IDP_CERT_FILE).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ImproperlyConfigured(f"SAML_IDP_CERT_FILE could not be read: {exc}")
SAML_SP_ENTITY_ID = os.getenv("SAML_SP_ENTITY_ID", "").strip()
SAML_ACS_URL = os.getenv("SAML_ACS_URL", "").strip()
SAML_LABEL = os.getenv("SAML_LABEL", "Sign in with SAML").strip() or "Sign in with SAML"
SAML_EMAIL_ATTRIBUTE = os.getenv("SAML_EMAIL_ATTRIBUTE", "").strip()
SAML_ALLOWED_DOMAINS = [
    d.strip().lower().lstrip("@")
    for d in os.getenv("SAML_ALLOWED_DOMAINS", os.getenv("OIDC_ALLOWED_DOMAINS", "")).split(",") if d.strip()
]
SAML_AUTO_PROVISION = env_bool("SAML_AUTO_PROVISION", OIDC_AUTO_PROVISION)
SAML_DEFAULT_ROLE = os.getenv("SAML_DEFAULT_ROLE", OIDC_DEFAULT_ROLE).strip() or OIDC_DEFAULT_ROLE
SAML_LINK_BY_EMAIL = env_bool("SAML_LINK_BY_EMAIL", OIDC_LINK_BY_EMAIL)
if SAML_IDP_SSO_URL and not SAML_IDP_SSO_URL.startswith("https://") and not DEBUG:
    raise ImproperlyConfigured("SAML_IDP_SSO_URL must be an https:// URL.")

# Unpinned, the ACS and redirect addresses are built from the request, and with ALLOWED_HOSTS=* any host would
# satisfy the Destination and Recipient comparison: pin SAML_ACS_URL and OIDC_REDIRECT_URI.
if not DEBUG and (OIDC_ISSUER or SAML_IDP_SSO_URL) and "*" in ALLOWED_HOSTS:
    if not (SAML_ACS_URL and OIDC_REDIRECT_URI):
        raise ImproperlyConfigured(
            "Single sign-on with DJANGO_ALLOWED_HOSTS=* needs SAML_ACS_URL and "
            "OIDC_REDIRECT_URI set explicitly, so an assertion cannot be redirected "
            "to a host of the sender's choosing. Name your hosts, or pin both URLs.")

# --- Step-up on single sign-on -------------------------------------------------------
SSO_STEP_UP = os.getenv("SSO_STEP_UP", "if_enrolled").strip().lower()
if SSO_STEP_UP not in ("off", "if_enrolled", "required"):
    raise ImproperlyConfigured("SSO_STEP_UP must be off, if_enrolled or required.")
# `user` (presence only) and `pin` (often the first factor) from RFC 8176 are left out on purpose:
# either would satisfy the step-up requirement with no second factor presented.
SSO_MFA_ASSERTIONS = [
    a.strip() for a in os.getenv(
        "SSO_MFA_ASSERTIONS",
        "mfa,otp,hwk,swk,sms,tel,fido,pop,"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:TimeSyncToken,"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorContract,"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:MobileTwoFactorUnregistered,"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:SmartcardPKI,"
        "urn:oasis:names:tc:SAML:2.0:ac:classes:X509,"
        "http://schemas.microsoft.com/claims/multipleauthn,"
        "http://schemas.microsoft.com/ws/2012/12/authmethod/otp,"
        "http://schemas.microsoft.com/ws/2012/12/authmethod/fido",
    ).split(",") if a.strip()
]

# --- Passkeys (WebAuthn) -------------------------------------------------------------
# A passkey is bound to its relying-party id for life: pin the id and origins before the hostname changes.
WEBAUTHN_RP_ID = os.getenv("WEBAUTHN_RP_ID", "").strip().lower()
WEBAUTHN_RP_NAME = os.getenv("WEBAUTHN_RP_NAME", "Conformiti").strip() or "Conformiti"
WEBAUTHN_ORIGINS = [
    o.strip().rstrip("/").lower() for o in os.getenv("WEBAUTHN_ORIGINS", "").split(",") if o.strip()
]
WEBAUTHN_USER_VERIFICATION = os.getenv("WEBAUTHN_USER_VERIFICATION", "preferred").strip().lower()
if WEBAUTHN_USER_VERIFICATION not in ("required", "preferred", "discouraged"):
    raise ImproperlyConfigured("WEBAUTHN_USER_VERIFICATION must be required, preferred or discouraged.")

# --- Public address ---------------------------------------------------------------------
# Required with DEBUG off: a link that carries a bearer token (the questionnaire) must not take its host from
# the request (vendors/questionnaire.py, public_base). Under DEBUG an unset value falls back to the request.
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
ORGANISATION_NAME = os.getenv("ORGANISATION_NAME", "").strip()

TEST_RUNNER = "config.testrunner.Runner"

# --- Package signing ----------------------------------------------------------------
# Detached Ed25519 signatures; the key lives in a FILE (or SIGNING_KEY), never in the database.
SIGNING_ENABLED = env_bool("SIGNING_ENABLED", True)
SIGNING_KEY = os.getenv("SIGNING_KEY", "")
SIGNING_KEY_FILE = os.getenv("SIGNING_KEY_FILE", str(BASE_DIR / ".package-signing-key")).strip()

# --- Logging ------------------------------------------------------------------
_LOG_LEVEL_SET = (os.getenv("LOG_LEVEL") or "").strip().upper()
LOG_LEVEL = _LOG_LEVEL_SET or ("DEBUG" if DEBUG else "INFO")
# runserver's autoreloader logs one DEBUG line per watched file, over a thousand per start: hold it at INFO.
_AUTORELOAD_LEVEL = "INFO" if LOG_LEVEL in ("DEBUG", "NOTSET") else LOG_LEVEL
# django.template logs every unresolved variable at DEBUG with a traceback (each 404, each email template):
# held at INFO under the DEBUG default, while an explicit LOG_LEVEL applies as written.
_FRAMEWORK_LEVEL = LOG_LEVEL if _LOG_LEVEL_SET else _AUTORELOAD_LEVEL
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.utils.autoreload": {"handlers": ["console"], "level": _AUTORELOAD_LEVEL,
                                    "propagate": False},
        "django.template": {"handlers": ["console"], "level": _FRAMEWORK_LEVEL,
                            "propagate": False},
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # signxml logs whole SAML assertions at DEBUG; they do not belong in a log.
        "signxml": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
if getattr(sys, "argv", [])[1:2] == ["test"] and not _LOG_LEVEL_SET:
    LOGGING["loggers"]["django.request"] = {"handlers": ["console"], "level": "ERROR",
                                           "propagate": False}
    LOGGING["loggers"]["notifications.email_service"] = {
        "handlers": ["console"], "level": "WARNING", "propagate": False}
