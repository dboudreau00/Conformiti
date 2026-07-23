"""
Django settings for Conformiti.

Configuration is environment-driven so the same code runs locally (SQLite +
console email + local file storage) and in production (Postgres + Amazon SES +
S3). Copy .env.example to .env and adjust.
"""
import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / ".env")


def env_bool(key, default=False):
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes", "on")


# --- Core -------------------------------------------------------------------
DEBUG = env_bool("DJANGO_DEBUG", True)

_INSECURE_KEY = "dev-insecure-change-me"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", _INSECURE_KEY)
# Refuse to boot in production with the throwaway development key.
if not DEBUG and SECRET_KEY == _INSECURE_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY must be set to a strong, unique value when DEBUG is off."
    )

ALLOWED_HOSTS = [h for h in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",") if o
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
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
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
if env_bool("USE_S3"):
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
    MEDIA_ROOT = BASE_DIR / "media"

# Physical compliance folder tree location (used by generate_folder_tree).
COMPLIANCE_TREE_ROOT = os.getenv(
    "COMPLIANCE_TREE_ROOT", str(BASE_DIR.parent / "compliance-data")
)

# --- DRF / auth -------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
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
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.getenv("JWT_ACCESS_MINUTES", "60"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.getenv("JWT_REFRESH_DAYS", "7"))),
    # Keep each user's last_login current so access reviews reflect real activity.
    "UPDATE_LAST_LOGIN": True,
}

CORS_ALLOWED_ORIGINS = [
    o for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o
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
MAILBOX_PORT = int(os.getenv("MAILBOX_PORT", "993" if MAILBOX_PROTOCOL == "imap" else "995"))
MAILBOX_USERNAME = os.getenv("MAILBOX_USERNAME", "")
MAILBOX_PASSWORD = os.getenv("MAILBOX_PASSWORD", "")
MAILBOX_USE_SSL = env_bool("MAILBOX_USE_SSL", True)
MAILBOX_SAVE_SENT = env_bool("MAILBOX_SAVE_SENT", True)
MAILBOX_SENT_FOLDER = os.getenv("MAILBOX_SENT_FOLDER", "Sent")
MAILBOX_TIMEOUT = int(os.getenv("MAILBOX_TIMEOUT", "30"))
# SMTP endpoint for the same account (defaults fill in from the mailbox values).
MAILBOX_SMTP_HOST = os.getenv("MAILBOX_SMTP_HOST", "")
MAILBOX_SMTP_PORT = int(os.getenv("MAILBOX_SMTP_PORT", "587"))
MAILBOX_SMTP_USERNAME = os.getenv("MAILBOX_SMTP_USERNAME", "")
MAILBOX_SMTP_PASSWORD = os.getenv("MAILBOX_SMTP_PASSWORD", "")
MAILBOX_SMTP_USE_TLS = env_bool("MAILBOX_SMTP_USE_TLS", True)   # STARTTLS on 587
MAILBOX_SMTP_USE_SSL = env_bool("MAILBOX_SMTP_USE_SSL", False)  # implicit SSL on 465

# SMTP (only used when EMAIL_PROVIDER=smtp)
if EMAIL_PROVIDER == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = os.getenv("EMAIL_HOST", "localhost")
    EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
elif EMAIL_PROVIDER == "console":
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Review-reminder lead times (days before next_review_date) that trigger alerts.
REVIEW_ALERT_LEAD_DAYS = [
    int(x) for x in os.getenv("REVIEW_ALERT_LEAD_DAYS", "30,14,7,1").split(",")
]

# --- Celery -----------------------------------------------------------------
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULE = {
    "scan-document-reviews-daily": {
        "task": "notifications.tasks.scan_document_reviews",
        "schedule": 60 * 60 * 24,  # once a day
    },
}


# --- Security hardening ------------------------------------------------------
# Sensible always-on headers, plus TLS/cookie hardening that engages
# automatically in production (DEBUG off). All of it is env-tunable so a local
# HTTP deployment can opt out where TLS isn't terminated yet.
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True

if not DEBUG:
    # We sit behind nginx/another proxy that terminates TLS.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", True)
    # HSTS: opt-in via env so it isn't switched on before TLS is truly ready.
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
