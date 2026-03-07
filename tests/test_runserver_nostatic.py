from __future__ import annotations

import argparse
from types import SimpleNamespace

from django.core.management import get_commands, load_command_class


def get_command_instance(name):
    app_name = get_commands()[name]
    return load_command_class(app_name, name)


def get_canonical_runserver_module():
    import servestatic.management.commands.runserver as runserver_module

    return runserver_module


def get_legacy_alias_runserver_module():
    import servestatic.runserver_nostatic.management.commands.runserver as runserver_module

    return runserver_module


def test_command_output():
    command = get_command_instance("runserver")
    parser = command.create_parser("manage.py", "runserver")
    assert "Wrapped by 'servestatic'" in parser.format_help()
    assert not parser.get_default("use_static_handler")


def test_find_fallback_runserver_command_returns_none_when_no_imports_work(monkeypatch):
    runserver_module = get_canonical_runserver_module()
    monkeypatch.setattr(runserver_module, "iter_lower_priority_apps", lambda: iter(["missing.app"]))

    def raise_import_error(_module_path):
        raise ImportError

    monkeypatch.setattr(runserver_module, "import_module", raise_import_error)
    assert runserver_module.find_fallback_runserver_command() is None


def test_iter_lower_priority_apps_yields_remaining_apps_and_django_core(monkeypatch):
    runserver_module = get_canonical_runserver_module()
    app_configs = [
        SimpleNamespace(name="before.self"),
        SimpleNamespace(name=runserver_module.SERVESTATIC_APP_NAME),
        SimpleNamespace(name="after.self"),
    ]
    monkeypatch.setattr(runserver_module.apps, "get_app_configs", lambda: app_configs)
    assert list(runserver_module.iter_lower_priority_apps()) == ["after.self", "django.core"]


def test_command_add_arguments_handles_empty_description_without_toggling_false_default(monkeypatch):
    runserver_module = get_canonical_runserver_module()
    monkeypatch.setattr(runserver_module.BaseRunserverCommand, "add_arguments", lambda self, parser: None)
    parser = argparse.ArgumentParser(description=None)
    parser.set_defaults(use_static_handler=False)
    runserver_module.Command().add_arguments(parser)
    assert parser.description == ""
    assert parser.get_default("use_static_handler") is False


def test_legacy_module_aliases_canonical_command_exports():
    canonical = get_canonical_runserver_module()
    alias = get_legacy_alias_runserver_module()

    assert alias.Command is canonical.Command
    assert alias.RunserverCommand is canonical.BaseRunserverCommand
    assert alias.get_next_runserver_command is canonical.find_fallback_runserver_command
    assert alias.get_lower_priority_apps is canonical.iter_lower_priority_apps


def test_legacy_alias_app_config_points_to_runserver_nostatic_path():
    from servestatic.apps import ServeStaticConfig
    from servestatic.runserver_nostatic.apps import ServeStaticRunserverNoStaticAliasConfig

    assert issubclass(ServeStaticRunserverNoStaticAliasConfig, ServeStaticConfig)
    assert ServeStaticRunserverNoStaticAliasConfig.name == "servestatic.runserver_nostatic"
    assert ServeStaticRunserverNoStaticAliasConfig.label == "servestatic_runserver_nostatic"
