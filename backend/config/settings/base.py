"""
Base Django settings for Milepost backend.

Shared across development and production.  Environment-specific overrides
live in dev.py (implicitly, via DJANGO_SETTINGS_MODULE) or prod.py.

No database models are used — the application is fully stateless per-request
(SPEC §27).  No authentication is required (SPEC §27).
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# backend/ directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env from backend/.env (never committed — see .env.example)
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    # Insecure fallback used ONLY in local dev; prod.py enforces a real key.
    "django-insecure-dev-only-change-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"

ALLOWED_HOSTS_ENV = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_ENV.split(",") if h.strip()]

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    # Django built-ins (admin/auth omitted — not required by SPEC §27)
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # Local
    "trip_planner",
]

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",   # must be first
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# URLs / WSGI / ASGI
# ---------------------------------------------------------------------------

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Templates (minimal — API-only backend; no rendered HTML pages)
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Database — intentionally empty (stateless per-request, SPEC §27)
# ---------------------------------------------------------------------------

DATABASES = {}

# ---------------------------------------------------------------------------
# CORS — allow React dev server and the deployed frontend origin
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS_ENV = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
CORS_ALLOWED_ORIGINS = [
    o.strip() for o in CORS_ALLOWED_ORIGINS_ENV.split(",") if o.strip()
]

CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]
CORS_ALLOW_HEADERS = ["content-type", "accept"]

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    # No authentication or permissions required (SPEC §27)
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    # Return structured error objects, never raw 500s (SPEC §13)
    "EXCEPTION_HANDLER": "trip_planner.views.custom_exception_handler",
}

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files (API only — nothing to serve in practice)
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Nominatim throttle (SPEC §13 — ~1 req/sec)
# ---------------------------------------------------------------------------

NOMINATIM_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT", "milepost-trip-planner/1.0"
)
NOMINATIM_THROTTLE_SECONDS = float(
    os.environ.get("NOMINATIM_THROTTLE_SECONDS", "1.1")
)

# ---------------------------------------------------------------------------
# External service timeouts (SPEC §13 — 5 s timeout, 1 retry)
# ---------------------------------------------------------------------------

EXTERNAL_TIMEOUT_SECONDS = int(os.environ.get("EXTERNAL_TIMEOUT_SECONDS", "5"))
EXTERNAL_MAX_RETRIES = int(os.environ.get("EXTERNAL_MAX_RETRIES", "1"))
