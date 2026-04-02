"""
Django system checks for ServeStatic configuration issues.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import TYPE_CHECKING

from django.conf import settings
from django.core.checks import Error, register
from django.core.checks import Warning as CheckWarning

if TYPE_CHECKING:
    from django.apps import AppConfig

try:
    zstd = import_module("compression.zstd")
except ImportError:  # pragma: no cover
    zstd = None

SERVESTATIC_MIDDLEWARE = "servestatic.middleware.ServeStaticMiddleware"
GZIP_MIDDLEWARE = "django.middleware.gzip.GZipMiddleware"
LEGACY_SERVESTATIC_APPS = {
    "servestatic.runserver_nostatic",
    "servestatic.runserver_nostatic.apps.ServeStaticRunserverNoStaticAliasConfig",
}


def _is_non_negative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _get_setting(name: str) -> object | None:
    return getattr(settings, name, None)


def _validate_type(
    name: str, *, expected: type[object] | tuple[type[object], ...], code: str, message: str
) -> list[Error]:
    value = _get_setting(name)
    if value is None:
        return []
    return [] if isinstance(value, expected) else [Error(message, id=code)]


def _validate_bool_setting(name: str, code: str) -> list[Error]:
    return _validate_type(
        name,
        expected=bool,
        code=code,
        message=f"{name} must be a boolean.",
    )


def _validate_servestatic_root() -> list[Error]:
    value = _get_setting("SERVESTATIC_ROOT")
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike)):
        return []
    return [Error("SERVESTATIC_ROOT must be a string path, os.PathLike, or None.", id="servestatic.E010")]


def _validate_servestatic_max_age() -> list[Error]:
    value = _get_setting("SERVESTATIC_MAX_AGE")
    if value is None or _is_non_negative_int(value):
        return []
    return [Error("SERVESTATIC_MAX_AGE must be a non-negative integer or None.", id="servestatic.E014")]


def _validate_servestatic_index_file() -> list[Error]:
    value = _get_setting("SERVESTATIC_INDEX_FILE")
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str) and value:
        return []
    return [
        Error(
            "SERVESTATIC_INDEX_FILE must be a boolean, a non-empty string, or None.",
            id="servestatic.E015",
        )
    ]


def _validate_servestatic_mimetypes() -> list[Error]:
    value = _get_setting("SERVESTATIC_MIMETYPES")
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [
            Error("SERVESTATIC_MIMETYPES must be a mapping of string keys to string values.", id="servestatic.E016")
        ]
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            return [Error("SERVESTATIC_MIMETYPES keys must be non-empty strings.", id="servestatic.E016")]
        if not isinstance(item, str) or not item:
            return [Error("SERVESTATIC_MIMETYPES values must be non-empty strings.", id="servestatic.E016")]
    return []


def _validate_servestatic_charset() -> list[Error]:
    value = _get_setting("SERVESTATIC_CHARSET")
    if value is None or (isinstance(value, str) and value):
        return []
    return [Error("SERVESTATIC_CHARSET must be a non-empty string.", id="servestatic.E017")]


def _validate_servestatic_skip_compress_extensions() -> list[Error]:
    value = _get_setting("SERVESTATIC_SKIP_COMPRESS_EXTENSIONS")
    if value is None:
        return []
    if isinstance(value, (str, bytes, bytearray, memoryview)) or not isinstance(value, Iterable):
        return [Error("SERVESTATIC_SKIP_COMPRESS_EXTENSIONS must be an iterable of strings.", id="servestatic.E019")]
    for item in value:
        if not isinstance(item, str) or not item:
            return [
                Error("SERVESTATIC_SKIP_COMPRESS_EXTENSIONS must contain non-empty strings.", id="servestatic.E019")
            ]
    return []


def _validate_servestatic_zstd_dictionary() -> list[Error]:
    value = _get_setting("SERVESTATIC_ZSTD_DICTIONARY")
    if value is None:
        return []
    if isinstance(value, (str, os.PathLike, bytes, bytearray, memoryview)):
        return []
    if zstd is not None and isinstance(value, zstd.ZstdDict):
        return []
    return [
        Error(
            "SERVESTATIC_ZSTD_DICTIONARY must be a path, bytes-like value, zstd dictionary object, or None.",
            id="servestatic.E021",
        )
    ]


def _validate_servestatic_zstd_level() -> list[Error]:
    value = _get_setting("SERVESTATIC_ZSTD_LEVEL")
    if value is None:
        return []
    if isinstance(value, int) and not isinstance(value, bool):
        return []
    return [Error("SERVESTATIC_ZSTD_LEVEL must be an integer or None.", id="servestatic.E023")]


def _validate_servestatic_add_headers_function() -> list[Error]:
    value = _get_setting("SERVESTATIC_ADD_HEADERS_FUNCTION")
    if value is None or callable(value):
        return []
    return [Error("SERVESTATIC_ADD_HEADERS_FUNCTION must be callable or None.", id="servestatic.E024")]


def _validate_servestatic_immutable_file_test() -> list[Error]:
    value = _get_setting("SERVESTATIC_IMMUTABLE_FILE_TEST")
    if value is None or callable(value):
        return []
    if isinstance(value, str):
        try:
            re.compile(value)
        except re.error:
            return [Error("SERVESTATIC_IMMUTABLE_FILE_TEST regex is invalid.", id="servestatic.E025")]
        return []
    return [Error("SERVESTATIC_IMMUTABLE_FILE_TEST must be callable, regex string, or None.", id="servestatic.E025")]


def _validate_servestatic_static_prefix() -> list[Error]:
    value = _get_setting("SERVESTATIC_STATIC_PREFIX")
    if value is None or isinstance(value, str):
        return []
    return [Error("SERVESTATIC_STATIC_PREFIX must be a string or None.", id="servestatic.E026")]


@register()
def check_middleware_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[Error]:
    middleware = list(getattr(settings, "MIDDLEWARE", []))

    if SERVESTATIC_MIDDLEWARE not in middleware or GZIP_MIDDLEWARE not in middleware:
        return []

    if middleware.index(SERVESTATIC_MIDDLEWARE) < middleware.index(GZIP_MIDDLEWARE):
        return []

    return [
        Error(
            "ServeStatic middleware ordering is invalid.",
            hint=(
                "Move 'servestatic.middleware.ServeStaticMiddleware' before "
                "'django.middleware.gzip.GZipMiddleware' in MIDDLEWARE."
            ),
            id="servestatic.E001",
        )
    ]


@register()
def check_deprecated_app_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[CheckWarning]:
    installed_apps = set(getattr(settings, "INSTALLED_APPS", []))
    if not installed_apps.intersection(LEGACY_SERVESTATIC_APPS):
        return []

    return [
        CheckWarning(
            "Deprecated ServeStatic app path detected.",
            hint="Replace 'servestatic.runserver_nostatic' with 'servestatic' in INSTALLED_APPS.",
            id="servestatic.W001",
        )
    ]


@register()
def check_setting_configuration(
    app_configs: Iterable[AppConfig] | None = None,
    **kwargs: object,
) -> list[Error]:
    errors = []

    errors.extend(_validate_servestatic_root())
    errors.extend(_validate_bool_setting("SERVESTATIC_AUTOREFRESH", "servestatic.E011"))
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_MANIFEST", "servestatic.E012"))
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_FINDERS", "servestatic.E013"))
    errors.extend(_validate_servestatic_max_age())
    errors.extend(_validate_servestatic_index_file())
    errors.extend(_validate_servestatic_mimetypes())
    errors.extend(_validate_servestatic_charset())
    errors.extend(_validate_bool_setting("SERVESTATIC_ALLOW_ALL_ORIGINS", "servestatic.E018"))
    errors.extend(_validate_servestatic_skip_compress_extensions())
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_ZSTD", "servestatic.E020"))
    errors.extend(_validate_servestatic_zstd_dictionary())
    errors.extend(_validate_bool_setting("SERVESTATIC_ZSTD_DICTIONARY_IS_RAW", "servestatic.E022"))
    errors.extend(_validate_servestatic_zstd_level())
    errors.extend(_validate_servestatic_add_headers_function())
    errors.extend(_validate_servestatic_immutable_file_test())
    errors.extend(_validate_servestatic_static_prefix())
    errors.extend(_validate_bool_setting("SERVESTATIC_KEEP_ONLY_HASHED_FILES", "servestatic.E027"))
    errors.extend(_validate_bool_setting("SERVESTATIC_MANIFEST_STRICT", "servestatic.E028"))
    errors.extend(_validate_bool_setting("SERVESTATIC_ALLOW_UNSAFE_SYMLINKS", "servestatic.E029"))
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_STATIC_ROOT", "servestatic.E030"))
    errors.extend(_validate_bool_setting("SERVESTATIC_MINIFY", "servestatic.E031"))
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_GZIP", "servestatic.E032"))
    errors.extend(_validate_bool_setting("SERVESTATIC_USE_BROTLI", "servestatic.E033"))

    return errors
