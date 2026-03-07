"""
Subclass the existing Django 'runserver' command and change the default options
to disable static file serving, allowing ServeStatic to handle static files.

There is some unpleasant hackery here because we don't know which command class
to subclass until runtime as it depends on which INSTALLED_APPS we have, so we
have to determine this dynamically.
"""

from __future__ import annotations

import contextlib
from importlib import import_module
from typing import TYPE_CHECKING, cast

from django.apps import apps

if TYPE_CHECKING:
    from django.core.management.base import BaseCommand

SERVESTATIC_APP_NAME = "servestatic"


def find_fallback_runserver_command():
    """
    Return the next highest priority "runserver" command class.
    """
    for app_name in iter_lower_priority_apps():
        module_path = f"{app_name}.management.commands.runserver"
        with contextlib.suppress(ImportError, AttributeError):
            return import_module(module_path).Command
    return None


def iter_lower_priority_apps():
    """
    Yield all app module names below the current app in INSTALLED_APPS.
    """
    reached_servestatic = False
    for app_config in apps.get_app_configs():
        if app_config.name == SERVESTATIC_APP_NAME:
            reached_servestatic = True
        elif reached_servestatic:
            yield app_config.name
    yield "django.core"


BaseRunserverCommand = cast("type[BaseCommand]", find_fallback_runserver_command())


class Command(BaseRunserverCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        if not parser.description:
            parser.description = ""
        if parser.get_default("use_static_handler") is True:
            parser.set_defaults(use_static_handler=False)
            parser.description += "\n(Wrapped by 'servestatic' to always enable '--nostatic')"
