"""
Django settings for Conformiti.

Configuration is environment-driven so the same code runs locally (SQLite +
console email + local file storage) and in production (Postgres + Redis +
SMTP/SES + optional S3). Copy .env.example to .env and adjust. Every key is
documented in .env.example.
"""
import os
import secrets
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(key, default=False):
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes", "on")


def env_int(key, default):
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        raise ImproperlyConfigured(f"{key} must be an integer (got {os.getenv(key)!r})")


# --- Core -------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)

_INSECURE_KEY = "dev-insecure-change-me"
# Every placeholder that ships in the repo must be rejected, not just the
# built-in default: .env.example carries its own placeholder. SECRET_KEY also
# signs the JWTs (SIMPLE_JWT has no separate SIGNING_KEY), so booting on a
# published value would let anyone mint tokens for any account.
_PLACEHOLDER_KEYS = {
    _INSECURE_KEY,
    "change-me-to-a-long-random-string",
    "changeme",
    "secret",
}


def _load_secret_key():
    """Resolve the secret key from, in order:

    1. DJANGO_SECRET_KEY (a real value — placeholders are ignored here so a
       copied .env.example never silently wins over the file below);
    2. DJANGO_SECRET_KEY_FILE — read the key from that file, or generate a
       strong one and write it there on first boot (0600). This is how the
       Docker stack gets a persistent, never-published key with zero config;
    3. the insecure development default (DEBUG only; refused otherwise).
    """
    explicit = (os.getenv("DJANGO_SECRET_KEY") or "").strip()
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
            path.parent.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_urlsafe(64)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(generated + "\n")
            return generated
        except OSError as exc:
            raise ImproperlyConfigured(
                f"DJANGO_SECRET_KEY_FILE={key_file!r} is not readable/writable: {exc}"
            )
    return explicit or _INSECURE_KEY


SECRET_KEY = _load_secret_key()
# Refuse to boot in production with a throwaway/placeholder key.
if not DEBUG and (SECRET_KEY.strip().lower() in _PLACEHOLDER_KEYS or len(SECRET_KEY.strip()) < 32):
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong, unique value when DEBUG is off "
        "(or point DJANGO_SECRET_KEY_FILE at a writable path to have one generated). "
        "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(50))\""
    )

# --- Field encryption (secrets at rest) -------------------------------------
# Two columns hold secrets the application must be able to read back, so they
# cannot be hashed: the TOTP secret and the Jira API token. They are encrypted
# with AES-256-GCM instead (see config/fieldcrypto.py).
#
# Keys are a RING, newest first: the first key encrypts, every key decrypts, so
# a key can be rotated without downtime (manage.py rotate_field_keys).
_FIELD_KEY_FILE_DEFAULT = BASE_DIR / ".field-encryption-key"


def _load_field_encryption_keys():
    """Resolve the key ring, and say where it came from.

    In order:
      1. DJANGO_FIELD_ENCRYPTION_KEY  - comma-separated keys, newest first;
      2. DJANGO_FIELD_ENCRYPTION_KEY_FILE - one key per line, generated at 0600
         on first boot if absent (this is how the Docker stack gets a
         persistent key with no configuration);
      3. derived from SECRET_KEY - only when SECRET_KEY is a real value, so a
         deployment that already keeps one secret does not have to keep two;
      4. a generated key file beside the database.

    Step 3 deliberately refuses a placeholder or short SECRET_KEY *regardless
    of DEBUG*: `dev-insecure-change-me` is published in this repository, and a
    ring derived from it would make "encrypted at rest" a false claim rather
    than a weak one.
    """
    explicit = (os.getenv("DJANGO_FIELD_ENCRYPTION_KEY") or "").strip()
    if explicit:
        keys = [k.strip() for k in explicit.split(",") if k.strip()]
        if keys:
            return keys, "env"

    key_file = (os.getenv("DJANGO_FIELD_ENCRYPTION_KEY_FILE") or "").strip()
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
            path.parent.mkdir(parents=True, exist_ok=True)
            generated = secrets.token_urlsafe(32)
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(generated + "\n")
            return [generated], "file"
        except OSError as exc:
            raise ImproperlyConfigured(
                f"DJANGO_FIELD_ENCRYPTION_KEY_FILE={key_file!r} is not readable/writable: {exc}"
            )

    # Derived from a real SECRET_KEY. Domain-separated so the two never collide.
    return ["derived:" + SECRET_KEY.strip()], "secret-key"


FIELD_ENCRYPTION_KEYS, FIELD_ENCRYPTION_KEY_SOURCE = _load_field_encryption_keys()

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # third-party
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "django_filters",
    # local apps
    "accounts",
    "compliance",
    "documents",
    "calendar_app",
    "notifications",
    "audit",
    "analytics",
    "governance",
    "integrations",
    "attestations",
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
    "audit.middleware.AuditLogMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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
    # SQLITE_PATH lets a second process (the end-to-end suite, a throwaway
    # sandbox) run against its own file instead of a developer's working
    # database.
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(os.getenv("SQLITE_PATH") or (BASE_DIR / "db.sqlite3")),
        }
    }

# --- Cache (throttle counters live here) ------------------------------------
# The per-IP login/MFA throttles count in the cache. The default local-memory
# cache is per *process*, so under gunicorn with N workers the effective limit
# is N times the configured rate and nothing is shared between containers.
# Point CACHE_URL at Redis (the compose file does) for a real shared limit.
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

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     # PCI DSS v4.0.1 requirement 8.3.6 asks for at least 12 characters.
     "OPTIONS": {"min_length": env_int("PASSWORD_MIN_LENGTH", 12)}},
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
# Local filesystem by default; switch to S3 by setting USE_S3=true.
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

# Upload ceiling enforced by the API (nginx enforces the same number at the
# edge via client_max_body_size, so keep the two in step).
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", 32)
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # non-file request bodies
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

# Physical compliance folder tree location (used by generate_folder_tree).
COMPLIANCE_TREE_ROOT = os.getenv(
    "COMPLIANCE_TREE_ROOT", str(BASE_DIR.parent / "compliance-data")
)

# --- Malware scanning for uploaded evidence ---------------------------------
# Off by default: it needs a ClamAV daemon. `docker compose --profile scanning
# up` starts one, and install.sh --scan turns it on. When it IS on it fails
# CLOSED -- an upload is refused if the scanner cannot be reached -- because
# "is evidence scanned?" must not depend on whether the daemon happened to
# answer. A scan occupies a gunicorn worker for its duration, which is why the
# API runs threaded workers.
CLAMAV_ENABLED = env_bool("CLAMAV_ENABLED", False)
CLAMAV_HOST = os.getenv("CLAMAV_HOST", "clamav")
CLAMAV_PORT = env_int("CLAMAV_PORT", 3310)
CLAMAV_TIMEOUT = env_int("CLAMAV_TIMEOUT", 10)
CLAMAV_CONNECT_TIMEOUT = env_int("CLAMAV_CONNECT_TIMEOUT", 3)
# Must stay at or below clamd's StreamMaxLength (docker/clamd.conf).
CLAMAV_MAX_BYTES = env_int("CLAMAV_MAX_MB", 40) * 1024 * 1024

# --- Evidence packages (the auditor workspace) ------------------------------
# How long a package may be issued to an external auditor for. The grant is
# checked on every request, so shortening this affects live grants too.
ATTESTATION_GRANT_DAYS = env_int("ATTESTATION_GRANT_DAYS", 45)
ATTESTATION_GRANT_MAX_DAYS = env_int("ATTESTATION_GRANT_MAX_DAYS", 180)

# --- Serving uploaded evidence ----------------------------------------------
# Evidence is read through the API (GET /api/documents/<id>/download/), which
# checks folder permissions and writes an audit row, rather than straight off
# the media volume. With MEDIA_INTERNAL the view answers with an
# X-Accel-Redirect and nginx sends the bytes from a location marked `internal`,
# so the storage path is neither guessable nor directly fetchable. Turn it off
# only where no accelerator sits in front of Django (the dev server does this
# automatically, because it defaults to the inverse of DEBUG).
MEDIA_INTERNAL = env_bool("MEDIA_INTERNAL", not DEBUG)
MEDIA_ACCEL_PREFIX = os.getenv("MEDIA_ACCEL_PREFIX", "/protected-media/")

# --- Control readiness scoring ----------------------------------------------
# A control's readiness is a weighted 0-100 score over the signals an auditor
# actually asks about, rather than a binary implemented/not. Weights and bands
# are configurable because "ready" means different things to different
# programmes; compliance/scoring.py reads these through settings at call time
# so a test can override them.
READINESS_WEIGHTS = {
    "implementation": env_int("SCORE_W_IMPLEMENTATION", 35),
    "owner": env_int("SCORE_W_OWNER", 10),
    "evidence": env_int("SCORE_W_EVIDENCE", 20),
    "freshness": env_int("SCORE_W_FRESHNESS", 20),
    "testing": env_int("SCORE_W_TESTING", 15),
    "risk_penalty": env_int("SCORE_W_RISK_PENALTY", 20),
}
# Ascending lower bounds for the at-risk / nearly / ready bands.
READINESS_BANDS = [int(x) for x in os.getenv("READINESS_BANDS", "40,70,90").split(",") if x.strip()]
if len(READINESS_BANDS) != 3 or sorted(READINESS_BANDS) != READINESS_BANDS         or len(set(READINESS_BANDS)) != 3 or not all(0 <= b <= 100 for b in READINESS_BANDS):
    raise ImproperlyConfigured(
        "READINESS_BANDS must be three strictly ascending integers in 0..100, "
        f"e.g. '40,70,90' (got {os.getenv('READINESS_BANDS')!r}). A malformed value "
        "would otherwise take the whole control register down on first read."
    )
# Evidence newer than this many days is fully fresh; past its review date by
# more than this, it scores zero.
READINESS_FRESH_DAYS = env_int("READINESS_FRESH_DAYS", 30)
# Fallback retest interval when a control does not set its own.
CONTROL_TEST_INTERVAL_DAYS = env_int("CONTROL_TEST_INTERVAL_DAYS", 365)

# --- DRF / auth -------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # Reads the access cookie when AUTH_TRANSPORT=cookie, and otherwise
        # behaves exactly like JWTAuthentication. A Bearer header always wins.
        "accounts.cookie_auth.CookieJWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # Throttling: limit anonymous traffic globally; the login endpoint adds a
    # tighter scoped limit (see config/urls.py) to blunt password brute-forcing.
    # Authenticated users are not globally throttled so the SPA stays responsive.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": os.getenv("THROTTLE_ANON", "30/min"),
        "login": os.getenv("THROTTLE_LOGIN", "8/min"),
        "mfa": os.getenv("THROTTLE_MFA", "10/min"),
        # Its own scope: in cookie mode every user's first request of the
        # morning goes through refresh, and the 8/min login limit would
        # start rejecting them behind a shared NAT.
        "refresh": os.getenv("THROTTLE_REFRESH", "30/min"),
        # Sealing and exporting hash every pinned file.
        "package_work": os.getenv("THROTTLE_PACKAGE_WORK", "6/min"),
    },
    # Browsable API only while developing; JSON-only in production.
    "DEFAULT_RENDERER_CLASSES": (
        ["rest_framework.renderers.JSONRenderer", "rest_framework.renderers.BrowsableAPIRenderer"]
        if DEBUG else ["rest_framework.renderers.JSONRenderer"]
    ),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env_int("JWT_ACCESS_MINUTES", 60)),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env_int("JWT_REFRESH_DAYS", 7)),
    # Every refresh issues a new refresh token and blacklists the old one, so a
    # stolen refresh token is single-use, and sign-out revokes it server-side
    # (POST /api/auth/logout/). Expired blacklist rows are pruned by the
    # weekly flushexpiredtokens beat job below.
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    # Keep each user's last_login current so access reviews reflect real activity.
    "UPDATE_LAST_LOGIN": True,
}

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()
]

# --- Email -------------------------------------------------------------------
# EMAIL_PROVIDER selects how review reminders are delivered:
#   "ses"     -> Amazon SES via boto3
#   "mailbox" -> a standard IMAP/POP3 + SMTP mailbox account (see notifications/mailbox.py)
#   "smtp"    -> any SMTP server (Django SMTP backend)
#   "console" -> prints to stdout (default in DEBUG)
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "console" if DEBUG else "ses")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "compliance@example.com")
COMPLIANCE_TEAM_EMAIL = os.getenv("COMPLIANCE_TEAM_EMAIL", DEFAULT_FROM_EMAIL)

# SES
AWS_SES_REGION = os.getenv("AWS_SES_REGION", os.getenv("AWS_REGION", "us-east-1"))
AWS_SES_CONFIGURATION_SET = os.getenv("AWS_SES_CONFIGURATION_SET", "")

# Standard mailbox account (EMAIL_PROVIDER=mailbox).
# The mailbox side (IMAP or POP3) is used to verify credentials and, for IMAP,
# to file a copy of each reminder in the Sent folder. Outgoing mail is sent over
# SMTP -- IMAP/POP3 cannot send. The SMTP host/user default to the mailbox
# host/user so a single-provider account (e.g. Gmail) needs minimal config.
MAILBOX_PROTOCOL = os.getenv("MAILBOX_PROTOCOL", "imap").lower()   # "imap" or "pop3"
MAILBOX_HOST = os.getenv("MAILBOX_HOST", "")
MAILBOX_PORT = env_int("MAILBOX_PORT", 993 if MAILBOX_PROTOCOL == "imap" else 995)
MAILBOX_USERNAME = os.getenv("MAILBOX_USERNAME", "")
MAILBOX_PASSWORD = os.getenv("MAILBOX_PASSWORD", "")
MAILBOX_USE_SSL = env_bool("MAILBOX_USE_SSL", True)
MAILBOX_SAVE_SENT = env_bool("MAILBOX_SAVE_SENT", True)
MAILBOX_SENT_FOLDER = os.getenv("MAILBOX_SENT_FOLDER", "Sent")
MAILBOX_TIMEOUT = env_int("MAILBOX_TIMEOUT", 30)
# SMTP endpoint for the same account (defaults fill in from the mailbox values).
MAILBOX_SMTP_HOST = os.getenv("MAILBOX_SMTP_HOST", "")
MAILBOX_SMTP_PORT = env_int("MAILBOX_SMTP_PORT", 587)
MAILBOX_SMTP_USERNAME = os.getenv("MAILBOX_SMTP_USERNAME", "")
MAILBOX_SMTP_PASSWORD = os.getenv("MAILBOX_SMTP_PASSWORD", "")
MAILBOX_SMTP_USE_TLS = env_bool("MAILBOX_SMTP_USE_TLS", True)   # STARTTLS on 587
MAILBOX_SMTP_USE_SSL = env_bool("MAILBOX_SMTP_USE_SSL", False)  # implicit SSL on 465

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

# Review-reminder lead times (days before next_review_date) that trigger alerts.
REVIEW_ALERT_LEAD_DAYS = [
    int(x) for x in os.getenv("REVIEW_ALERT_LEAD_DAYS", "30,14,7,1").split(",") if x.strip()
]

# --- Celery -----------------------------------------------------------------
from celery.schedules import crontab  # noqa: E402

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = 15 * 60
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# The review scan runs once a day at a fixed local hour (REVIEW_SCAN_HOUR, 24h)
# rather than "24h after the worker started", so operators know when mail goes
# out and a worker restart never skips or double-runs a day.
CELERY_BEAT_SCHEDULE = {
    "scan-document-reviews-daily": {
        "task": "notifications.tasks.scan_document_reviews",
        "schedule": crontab(hour=env_int("REVIEW_SCAN_HOUR", 6), minute=0),
    },
    "record-readiness-snapshot-daily": {
        "task": "analytics.tasks.record_readiness_snapshot",
        "schedule": crontab(hour=env_int("REVIEW_SCAN_HOUR", 6), minute=5),
    },
    "flush-expired-jwt-blacklist-weekly": {
        "task": "accounts.tasks.flush_expired_tokens",
        "schedule": crontab(day_of_week="sunday", hour=3, minute=30),
    },
}


# --- Security hardening ------------------------------------------------------
# Sensible always-on headers, plus TLS/cookie hardening that engages
# automatically in production (DEBUG off). BEHIND_TLS is the single switch for
# an HTTP-only deployment (e.g. the compose stack on a LAN before TLS is
# terminated): it defaults to "on" whenever DEBUG is off, and each individual
# setting can still be overridden.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

BEHIND_TLS = env_bool("BEHIND_TLS", not DEBUG)
if not DEBUG:
    # We sit behind nginx/another proxy that terminates TLS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", BEHIND_TLS)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", BEHIND_TLS)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", BEHIND_TLS)
    # HSTS: opt-in via env so it isn't switched on before TLS is truly ready.
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)

# --- Authentication transport -----------------------------------------------
# "header"  the SPA keeps the tokens in localStorage and sends Authorization
#           (the 0.2.x behaviour, and still the default -- flipping it silently
#           would sign every existing deployment out);
# "cookie"  the same tokens travel as HttpOnly cookies, so script cannot read
#           them, and unsafe methods must carry Django's CSRF token.
# Both modes accept a Bearer header, so API clients are unaffected either way.
AUTH_TRANSPORT = os.getenv("AUTH_TRANSPORT", "header").strip().lower()
if AUTH_TRANSPORT not in ("header", "cookie"):
    raise ImproperlyConfigured(
        f"AUTH_TRANSPORT must be 'header' or 'cookie' (got {AUTH_TRANSPORT!r}). "
        "A typo here would silently fall back to header auth and quietly undo "
        "the hardening it was set for."
    )
AUTH_COOKIE_ACCESS = os.getenv("AUTH_COOKIE_ACCESS", "conformiti_access")
AUTH_COOKIE_REFRESH = os.getenv("AUTH_COOKIE_REFRESH", "conformiti_refresh")
# Scoped to the endpoint that consumes it, not to /api/auth/ -- that prefix
# covers nine routes, including the ones that return the TOTP secret and the
# backup codes.
AUTH_COOKIE_REFRESH_PATH = "/api/auth/token/"
AUTH_COOKIE_SECURE = env_bool("AUTH_COOKIE_SECURE", BEHIND_TLS)

# --- Logging ------------------------------------------------------------------
# Plain, single-line console logging that docker/systemd/journald can ingest.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO" if not DEBUG else "DEBUG").upper()
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
        # SQL echo is far too chatty even in DEBUG.
        "django.db.backends": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}
