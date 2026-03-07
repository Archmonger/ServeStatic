"""
Django app entry-point for ServeStatic. This defines Django-centric start-up behavior, such as
registering system checks.
"""

from __future__ import annotations

from django.apps import AppConfig


class ServeStaticConfig(AppConfig):
    name = "servestatic"

    def ready(self):
        super().ready()
        from servestatic import checks  # noqa: F401
