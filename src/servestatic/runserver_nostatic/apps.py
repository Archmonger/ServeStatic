"""Backward-compatible alias app for `servestatic.runserver_nostatic`."""

from __future__ import annotations

from servestatic.apps import ServeStaticConfig


class ServeStaticRunserverNoStaticAliasConfig(ServeStaticConfig):
    name = "servestatic.runserver_nostatic"
    label = "servestatic_runserver_nostatic"
