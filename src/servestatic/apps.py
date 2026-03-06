from __future__ import annotations

from django.apps import AppConfig


class ServeStaticConfig(AppConfig):
    name = "servestatic"

    def ready(self):
        from servestatic import checks  # noqa: F401
