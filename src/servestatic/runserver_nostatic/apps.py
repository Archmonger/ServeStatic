"""Backward-compatible alias app for `servestatic.runserver_nostatic`."""

from __future__ import annotations

from warnings import warn

from servestatic.apps import ServeStaticConfig


class ServeStaticRunserverNoStaticAliasConfig(ServeStaticConfig):
    name = "servestatic.runserver_nostatic"
    label = "servestatic_runserver_nostatic"

    def ready(self):
        super().ready()
        warn(
            "The 'servestatic.runserver_nostatic' app is deprecated. Use 'servestatic' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
