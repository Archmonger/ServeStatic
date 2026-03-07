"""Backward-compatible import path for ``servestatic.runserver_nostatic``."""

from __future__ import annotations

from servestatic.management.commands import runserver as canonical_runserver

Command = canonical_runserver.Command
BaseRunserverCommand = canonical_runserver.BaseRunserverCommand
find_fallback_runserver_command = canonical_runserver.find_fallback_runserver_command
iter_lower_priority_apps = canonical_runserver.iter_lower_priority_apps

# Backward-compatible aliases for previous helper names.
get_next_runserver_command = find_fallback_runserver_command
get_lower_priority_apps = iter_lower_priority_apps
RunserverCommand = BaseRunserverCommand
