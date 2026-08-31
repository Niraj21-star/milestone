"""
Production settings for Milepost backend.

Inherits everything from base.py; overrides security-critical values.
DJANGO_SETTINGS_MODULE should be set to 'config.settings.prod' on the hosting
platform (Render, Railway, etc.).  SPEC §36.
"""

from .base import *  # noqa: F401, F403
import os

# ---------------------------------------------------------------------------
# Production security overrides
# ---------------------------------------------------------------------------

DEBUG = False

# SECRET_KEY must be set as an environment variable on the hosting platform.
# The base.py insecure fallback is intentionally not reachable here.
if not os.environ.get("DJANGO_SECRET_KEY"):
    raise RuntimeError(
        "DJANGO_SECRET_KEY environment variable is not set. "
        "Set it on the hosting platform before deploying."
    )

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# ALLOWED_HOSTS — set DJANGO_ALLOWED_HOSTS env var on the hosting platform.
# Example: "milepost-api.onrender.com"
ALLOWED_HOSTS_ENV = os.environ.get("DJANGO_ALLOWED_HOSTS", "")
ALLOWED_HOSTS = [h.strip() for h in ALLOWED_HOSTS_ENV.split(",") if h.strip()]

# ---------------------------------------------------------------------------
# HTTPS / security headers
# ---------------------------------------------------------------------------

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
