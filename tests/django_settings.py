from __future__ import annotations

import os.path


from .utils import TEST_FILE_PATH, AppServer

ALLOWED_HOSTS = ["*"]

ROOT_URLCONF = "tests.django_urls"

SECRET_KEY = "test_secret"

INSTALLED_APPS = ["servestatic.runserver_nostatic", "django.contrib.staticfiles"]

FORCE_SCRIPT_NAME = f"/{AppServer.PREFIX}"
STATIC_URL = f"{FORCE_SCRIPT_NAME}/static/"

STATIC_ROOT = os.path.join(TEST_FILE_PATH, "root")

STORAGES = {
    "staticfiles": {
        "BACKEND": "servestatic.storage.CompressedManifestStaticFilesStorage",
    },
}


MIDDLEWARE = [
    "tests.middleware.sync_middleware_1",
    "tests.middleware.async_middleware_1",
    "servestatic.middleware.ServeStaticMiddleware",
    "tests.middleware.sync_middleware_2",
    "tests.middleware.async_middleware_2",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"require_debug_false": {"()": "django.utils.log.RequireDebugFalse"}},
    "handlers": {"log_to_stderr": {"level": "ERROR", "class": "logging.StreamHandler"}},
    "loggers": {
        "django.request": {
            "handlers": ["log_to_stderr"],
            "level": "ERROR",
            "propagate": True,
        }
    },
}

USE_TZ = True
