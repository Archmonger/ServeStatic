from __future__ import annotations

import contextlib
import gzip
import os
import re
import shutil
import tempfile
from unittest import mock

import pytest

import servestatic.compress as compress_module
from servestatic.compress import Compressor
from servestatic.compress import main as compress_main

COMPRESSABLE_FILE = "application.css"
TOO_SMALL_FILE = "too-small.css"
WRONG_EXTENSION = "image.jpg"
TEST_FILES = {COMPRESSABLE_FILE: b"a" * 1000, TOO_SMALL_FILE: b"hi"}


@pytest.fixture(scope="module", autouse=True)
def files_dir():
    # Make a temporary directory and copy in test files
    tmp = tempfile.mkdtemp()
    timestamp = 1498579535
    for path, contents in TEST_FILES.items():
        current_path = os.path.join(tmp, path.lstrip("/"))
        with contextlib.suppress(FileExistsError):
            os.makedirs(os.path.dirname(current_path))
        with open(current_path, "wb") as f:
            f.write(contents)
        os.utime(current_path, (timestamp, timestamp))
    compress_main([tmp, "--quiet"])
    yield tmp
    shutil.rmtree(tmp)


def test_compresses_file(files_dir):
    with contextlib.closing(gzip.open(os.path.join(files_dir, f"{COMPRESSABLE_FILE}.gz"), "rb")) as f:
        contents = f.read()
    assert TEST_FILES[COMPRESSABLE_FILE] == contents


def test_doesnt_compress_if_no_saving(files_dir):
    assert not os.path.exists(os.path.join(files_dir, f"{TOO_SMALL_FILE}gz"))


def test_ignores_other_extensions(files_dir):
    assert not os.path.exists(os.path.join(files_dir, f"{WRONG_EXTENSION}.gz"))


def test_mtime_is_preserved(files_dir):
    path = os.path.join(files_dir, COMPRESSABLE_FILE)
    gzip_path = f"{path}.gz"
    assert os.path.getmtime(path) == os.path.getmtime(gzip_path)


def test_with_custom_extensions():
    compressor = Compressor(extensions=["jpg"], quiet=True)
    assert compressor.extension_re == re.compile(r"\.(jpg)$", re.IGNORECASE)


def test_with_falsey_extensions():
    compressor = Compressor(quiet=True)
    assert compressor.get_extension_re("") == re.compile(r"^$")


def test_custom_log():
    compressor = Compressor(log="test")
    assert compressor.log == "test"


def test_compress():
    compressor = Compressor(use_brotli=False, use_gzip=False, use_zstd=False)
    assert not list(compressor.compress("tests/test_files/static/styles.css"))


def test_compressed_effectively_no_orig_size():
    compressor = Compressor(quiet=True)
    assert not compressor.is_compressed_effectively("test_encoding", "test_path", 0, "test_data")


def test_main_error(files_dir):
    with (
        pytest.raises(ValueError, match="woops") as excinfo,
        mock.patch.object(Compressor, "compress", side_effect=ValueError("woops")),
    ):
        compress_main([files_dir, "--quiet"])

    assert excinfo.value.args == ("woops",)


def test_compress_brotli_raises_when_dependency_missing(monkeypatch):
    monkeypatch.setattr(compress_module, "brotli", None)
    with pytest.raises(RuntimeError, match="Brotli is not installed"):
        Compressor.compress_brotli(b"abc")


def test_compress_zstd_raises_when_dependency_missing(monkeypatch):
    monkeypatch.setattr(compress_module, "zstd", None)
    with pytest.raises(RuntimeError, match="Zstandard is not available"):
        Compressor.compress_zstd(b"abc")


def test_compressor_rejects_dictionary_when_zstd_is_unavailable(monkeypatch):
    monkeypatch.setattr(compress_module, "zstd", None)
    with pytest.raises(RuntimeError, match="requires Python 3.14"):
        Compressor(zstd_dict=b"dict")


def test_compress_generates_zstd_with_dictionary(tmp_path, monkeypatch):
    class FakeZstdDict:
        def __init__(self, dict_content, is_raw=False):
            self.dict_content = dict_content
            self.is_raw = is_raw

    class FakeZstd:
        def __init__(self):
            self.last_call = None

        ZstdDict = FakeZstdDict

        def compress(self, data, **kwargs):
            self.last_call = {"data": data, **kwargs}
            return b"zstd" + data[:1]

    fake_zstd = FakeZstd()
    monkeypatch.setattr(compress_module, "zstd", fake_zstd)

    source_path = tmp_path / "styles.css"
    source_path.write_bytes(b"a" * 1000)
    dict_path = tmp_path / "dict.bin"
    dict_path.write_bytes(b"dictionary-bytes")

    compressor = Compressor(
        use_gzip=False,
        use_brotli=False,
        use_zstd=True,
        zstd_dict=dict_path,
        zstd_dict_is_raw=True,
        zstd_level=7,
        quiet=True,
    )
    outputs = compressor.compress(str(source_path))

    assert outputs == [f"{source_path}.zstd"]
    assert os.path.exists(f"{source_path}.zstd")
    assert fake_zstd.last_call is not None
    assert fake_zstd.last_call["level"] == 7
    assert fake_zstd.last_call["zstd_dict"].dict_content == b"dictionary-bytes"
    assert fake_zstd.last_call["zstd_dict"].is_raw is True


def test_load_zstd_dictionary_raises_when_module_missing(monkeypatch):
    monkeypatch.setattr(compress_module, "zstd", None)
    with pytest.raises(RuntimeError, match="Zstandard is not available"):
        Compressor.load_zstd_dictionary(b"abc")


def test_load_zstd_dictionary_from_bytes_uses_zstd_dict(monkeypatch):
    class FakeZstdDict:
        def __init__(self, content, is_raw=False):
            self.content = content
            self.is_raw = is_raw

    class FakeZstd:
        ZstdDict = FakeZstdDict

    monkeypatch.setattr(compress_module, "zstd", FakeZstd())
    loaded = Compressor.load_zstd_dictionary(b"dict-bytes", is_raw=True)

    assert isinstance(loaded, FakeZstdDict)
    assert loaded.content == b"dict-bytes"
    assert loaded.is_raw is True


def test_load_zstd_dictionary_returns_prebuilt_object(monkeypatch):
    class FakeZstdDict:
        pass

    class FakeZstd:
        ZstdDict = FakeZstdDict

    monkeypatch.setattr(compress_module, "zstd", FakeZstd())
    sentinel = object()

    assert Compressor.load_zstd_dictionary(sentinel) is sentinel
