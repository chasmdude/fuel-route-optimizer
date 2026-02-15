"""
Development settings.

Used for local development via manage.py runserver.
Inherits from base and overrides for developer convenience.
"""

from .base import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ---------------------------------------------------------------------------
# DRF -- add browsable API in development
# ---------------------------------------------------------------------------
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [  # noqa: F405
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

# ---------------------------------------------------------------------------
# Logging -- verbose SQL queries in development
# ---------------------------------------------------------------------------
LOGGING["loggers"] = {  # noqa: F405
    "django.db.backends": {
        "handlers": ["console"],
        "level": "DEBUG" if DEBUG else "INFO",
        "propagate": False,
    },
}
