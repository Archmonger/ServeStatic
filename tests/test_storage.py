from __future__ import annotations

import errno
import os
import re
import shutil
import tempfile
from posixpath import basename

import pytest
from django.conf import settings
from django.contrib.staticfiles.storage import HashedFilesMixin, ManifestStaticFilesStorage, staticfiles_storage
from django.core.management import call_command
from django.test.utils import override_settings
from django.utils.functional import empty

from servestatic.storage import CompressedManifestStaticFilesStorage, MissingFileError

from .utils import Files


@pytest.fixture
def setup():
    staticfiles_storage._wrapped = empty
    files = Files("static")
    tmp = tempfile.mkdtemp()
    with override_settings(
        STATICFILES_DIRS=[files.directory],
        STATIC_ROOT=tmp,
    ):
        yield settings
    staticfiles_storage._wrapped = empty
    shutil.rmtree(tmp)


@pytest.fixture
def _compressed_storage(setup):
    backend = "servestatic.storage.CompressedStaticFilesStorage"
    storages = {
        "STORAGES": {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": backend},
        }
    }

    with override_settings(**storages):
        yield


@pytest.fixture
def _compressed_manifest_storage(setup):
    backend = "servestatic.storage.CompressedManifestStaticFilesStorage"
    storages = {
        "STORAGES": {
            **settings.STORAGES,
            "staticfiles": {"BACKEND": backend},
        }
    }

    with override_settings(**storages, SERVESTATIC_KEEP_ONLY_HASHED_FILES=True):
        call_command("collectstatic", verbosity=0, interactive=False)


@pytest.mark.usefixtures("_compressed_storage")
def test_compressed_static_files_storage():
    call_command("collectstatic", verbosity=0, interactive=False)

    for name in ["styles.css.gz", "styles.css.br"]:
        path = os.path.join(settings.STATIC_ROOT, name)
        assert os.path.exists(path)


@pytest.mark.usefixtures("_compressed_storage")
def test_compressed_static_files_storage_dry_run():
    call_command("collectstatic", "--dry-run", verbosity=0, interactive=False)

    for name in ["styles.css.gz", "styles.css.br"]:
        path = os.path.join(settings.STATIC_ROOT, name)
        assert not os.path.exists(path)


@pytest.mark.usefixtures("_compressed_manifest_storage")
def test_make_helpful_exception():
    class TriggerException(HashedFilesMixin):
        def exists(self, path):
            return False

    exception = None
    try:
        TriggerException().hashed_name("/missing/file.png")
    except ValueError as e:
        exception = e
    helpful_exception = CompressedManifestStaticFilesStorage().make_helpful_exception(exception, "styles/app.css")
    assert isinstance(helpful_exception, MissingFileError)


@pytest.mark.usefixtures("_compressed_manifest_storage")
def test_unversioned_files_are_deleted():
    name = "styles.css"
    versioned_url = staticfiles_storage.url(name)
    versioned_name = basename(versioned_url)
    name_pattern = re.compile("^" + name.replace(".", r"\.([0-9a-f]+\.)?") + "$")
    remaining_files = [f for f in os.listdir(settings.STATIC_ROOT) if name_pattern.match(f)]
    assert [versioned_name] == remaining_files


@pytest.mark.usefixtures("_compressed_manifest_storage")
def test_manifest_file_is_left_in_place():
    manifest_file = os.path.join(settings.STATIC_ROOT, "staticfiles.json")
    assert os.path.exists(manifest_file)


def test_manifest_strict_attribute_is_set():
    with override_settings(SERVESTATIC_MANIFEST_STRICT=True):
        storage = CompressedManifestStaticFilesStorage()
        assert storage.manifest_strict is True
    with override_settings(SERVESTATIC_MANIFEST_STRICT=False):
        storage = CompressedManifestStaticFilesStorage()
        assert storage.manifest_strict is False


def test_storage_stat_static_root_none_returns_empty():
    storage = object.__new__(CompressedManifestStaticFilesStorage)
    storage.manifest_name = "staticfiles.json"
    with override_settings(STATIC_ROOT=None):
        assert storage.stat_static_root() == {}


def test_storage_load_manifest_stats_none_content(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(storage, "read_manifest", lambda: None)
    assert storage.load_manifest_stats() == {}


def test_storage_load_manifest_stats_invalid_json_raises(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(storage, "read_manifest", lambda: "{not-json")
    with pytest.raises(ValueError, match="Couldn't load stats"):
        storage.load_manifest_stats()


def test_storage_delete_files_reraises_non_enoent_errors(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(storage, "path", lambda name: name)

    def raise_permission_error(_name):
        raise OSError(errno.EPERM, "permission denied")

    monkeypatch.setattr(os, "unlink", raise_permission_error)
    with pytest.raises(OSError):
        storage.delete_files(["forbidden.txt"])


def test_storage_hashed_name_tracks_new_files(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(ManifestStaticFilesStorage, "hashed_name", lambda self, *args, **kwargs: "css/app.abc.css")
    storage.start_tracking_new_files(set())
    try:
        assert storage.hashed_name("css/app.css") == "css/app.abc.css"
        assert "css/app.abc.css" in storage._new_files
    finally:
        storage.stop_tracking_new_files()


def test_storage_hashed_name_without_tracking_does_not_record(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(ManifestStaticFilesStorage, "hashed_name", lambda self, *args, **kwargs: "css/app.abc.css")
    storage._new_files = None
    assert storage.hashed_name("css/app.css") == "css/app.abc.css"


def test_storage_make_helpful_exception_returns_original_for_non_matching_message():
    storage = CompressedManifestStaticFilesStorage()
    exception = ValueError("A different error message")
    assert storage.make_helpful_exception(exception, "styles.css") is exception


def test_storage_make_helpful_exception_returns_original_for_non_value_error():
    storage = CompressedManifestStaticFilesStorage()
    exception = RuntimeError("Not a value error")
    assert storage.make_helpful_exception(exception, "styles.css") is exception


def test_storage_post_process_dry_run_skips_compression(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    raw_error = ValueError("The file 'missing.png' could not be found")

    monkeypatch.setattr(
        ManifestStaticFilesStorage,
        "post_process",
        lambda self, *args, **kwargs: iter([("styles.css", "styles.abc.css", raw_error)]),
    )

    was_called = {"compression": False}

    def fake_post_process_with_compression(files):
        was_called["compression"] = True
        return files

    monkeypatch.setattr(storage, "post_process_with_compression", fake_post_process_with_compression)
    monkeypatch.setattr(storage, "add_stats_to_manifest", lambda: None)

    results = list(storage.post_process({}, dry_run=True))

    assert was_called["compression"] is False
    assert isinstance(results[0][2], MissingFileError)


def test_storage_post_process_with_compression_handles_items_without_hashed_name(monkeypatch):
    storage = CompressedManifestStaticFilesStorage()
    monkeypatch.setattr(storage, "delete_files", lambda _items: None)
    monkeypatch.setattr(storage, "compress_files", lambda _items: [])

    results = list(storage.post_process_with_compression([("styles.css", None, True)]))

    assert results == [("styles.css", None, True)]
