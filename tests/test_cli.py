import json

import pytest

import servestatic.cli as servestatic_cli
from servestatic.cli import main


def test_cli_missing_args(capsys):
    with pytest.raises(SystemExit):
        main(["src", "dest"])
    captured = capsys.readouterr()
    assert "At least one of --hash, --manifest, --compress, or --all must be provided" in captured.err


def test_cli_invalid_src(capsys):
    with pytest.raises(SystemExit):
        main(["--hash", "does_not_exist", "dest"])
    captured = capsys.readouterr()
    assert "does not exist" in captured.err


def test_cli_hash_basic(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    (src / "subdir").mkdir()
    (src / "subdir" / "other.css").write_text("body { color: red; }")

    dest = tmp_path / "dest"

    main(["--hash", "--manifest", "--copy-original", str(src), str(dest)])

    assert (dest / "test.txt").exists()
    assert (dest / "subdir" / "other.css").exists()
    assert (dest / "staticfiles.json").exists()

    with open(dest / "staticfiles.json", encoding="utf-8") as f:
        manifest = json.load(f)

    # Check paths in manifest
    assert "test.txt" in manifest["paths"]
    assert "subdir/other.css" in manifest["paths"]

    # Check hashed files exist
    hashed_txt = manifest["paths"]["test.txt"]
    assert (dest / hashed_txt).exists()


def test_cli_hash_no_copy_original(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    dest = tmp_path / "dest"

    main(["--hash", str(src), str(dest)])

    assert not (dest / "test.txt").exists()
    # Find the hashed file
    assert len(list(dest.glob("test.*.txt"))) == 1


def test_cli_compress_basic(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    content = "console.log('hello');\n" * 1000
    (src / "script.js").write_text(content)
    dest = tmp_path / "dest"

    main(["--compress", str(src), str(dest)])

    assert (dest / "script.js").exists()
    assert (dest / "script.js.gz").exists()


def test_cli_exclude(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    content = "content\n" * 1000
    (src / "process_me.txt").write_text(content)
    (src / "ignore_me.txt").write_text(content)
    dest = tmp_path / "dest"

    # Exclude ignore_me.txt from processing
    # Note: It IS copied, but NOT hashed/compressed.
    main(["--hash", "--manifest", "--compress", "-e", "ignore_me.*", str(src), str(dest)])

    assert not (dest / "process_me.txt").exists()
    assert (dest / "ignore_me.txt").exists()

    # Check manifest
    with open(dest / "staticfiles.json", encoding="utf-8") as f:
        manifest = json.load(f)

    assert "process_me.txt" in manifest["paths"]
    assert "ignore_me.txt" in manifest["paths"]
    assert manifest["paths"]["ignore_me.txt"] == "ignore_me.txt"

    # Check compression
    # process_me.txt.gz should exist (if txt is compressible?)
    # existing compress.py extensions excludes nothing by default, but txt might be skipped if deemed not "compressible"?
    # Default SKIP_COMPRESS_EXTENSIONS includes 'gz', 'png' etc. NOT 'txt'.
    # So txt is compressed.
    # But wait, Compressor checks extensions to SKIP.
    # 'txt' is NOT in SKIP list. So it should compress.

    # Check if ignore_me.txt.gz exists (should NOT)
    assert not (dest / "ignore_me.txt.gz").exists()


def test_cli_hash_and_compress(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    content = "body { color: blue; }\n" * 1000
    (src / "style.css").write_text(content)
    dest = tmp_path / "dest"

    main(["--hash", "--compress", "--copy-original", str(src), str(dest)])

    # Expect:
    # style.css (original)
    # style.hash.css (hashed)
    # style.css.gz (compressed original)
    # style.hash.css.gz (compressed hashed)

    assert (dest / "style.css").exists()
    assert (dest / "style.css.gz").exists()

    # Find hash
    found = list(dest.glob("style.*.css"))
    assert len(found) == 1
    hashed_file = found[0]

    assert (dest / f"{hashed_file.name}.gz").exists()


def test_cli_all(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    content = "body { color: green; }\n" * 1000
    (src / "all_style.css").write_text(content)
    dest = tmp_path / "dest"

    main(["--all", "--copy-original", str(src), str(dest)])

    assert (dest / "all_style.css").exists()
    assert (dest / "all_style.css.gz").exists()

    found = list(dest.glob("all_style.*.css"))
    assert len(found) == 1
    assert (dest / f"{found[0].name}.gz").exists()


def test_cli_manifest_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    dest = tmp_path / "dest"

    main(["--manifest", str(src), str(dest)])

    assert (dest / "test.txt").exists()
    assert (dest / "staticfiles.json").exists()

    with open(dest / "staticfiles.json", encoding="utf-8") as f:
        manifest = json.load(f)

    # Check paths in manifest
    assert "test.txt" in manifest["paths"]
    assert manifest["paths"]["test.txt"] == "test.txt"


def test_cli_hash_only(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    dest = tmp_path / "dest"

    main(["--hash", "--copy-original", str(src), str(dest)])

    assert (dest / "test.txt").exists()
    assert not (dest / "staticfiles.json").exists()

    # Find the hashed file
    found = list(dest.glob("test.*.txt"))
    assert len(found) == 1


def test_cli_copy_original_behavior(tmp_path):
    """Test that --copy-original correctly determines if original files are kept."""
    # Test Without --copy-original (default behavior)
    src_no_copy = tmp_path / "src_no_copy"
    src_no_copy.mkdir()
    (src_no_copy / "test.txt").write_text("content")
    dest_no_copy = tmp_path / "dest_no_copy"

    main(["--hash", str(src_no_copy), str(dest_no_copy)])

    assert not (dest_no_copy / "test.txt").exists(), "Original file should NOT exist by default."
    assert len(list(dest_no_copy.glob("test.*.txt"))) == 1, "Hashed file should exist."

    # Test With --copy-original
    src_with_copy = tmp_path / "src_with_copy"
    src_with_copy.mkdir()
    (src_with_copy / "test.txt").write_text("content")
    dest_with_copy = tmp_path / "dest_with_copy"

    main(["--hash", "--copy-original", str(src_with_copy), str(dest_with_copy)])

    assert (dest_with_copy / "test.txt").exists(), "Original file should exist when --copy-original is provided."
    assert len(list(dest_with_copy.glob("test.*.txt"))) == 1, "Hashed file should exist."


def test_cli_quiet(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    dest = tmp_path / "dest"

    main(["--all", "--copy-original", "-q", str(src), str(dest)])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_cli_clear(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")

    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "old_file.txt").write_text("old")
    (dest / "old_subdir").mkdir()
    (dest / "old_subdir" / "foo.txt").write_text("bar")

    main(["--all", "--copy-original", "--clear", str(src), str(dest)])

    assert (dest / "test.txt").exists()
    assert not (dest / "old_file.txt").exists()
    assert not (dest / "old_subdir").exists()


def test_cli_clear_same_dir(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()

    with pytest.raises(SystemExit):
        main(["--all", "--clear", str(src), str(src)])
    captured = capsys.readouterr()
    assert "cannot be the same" in captured.err


def test_cli_same_dir_without_clear(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")

    with pytest.raises(SystemExit):
        main(["--manifest", str(src), str(src)])

    captured = capsys.readouterr()
    assert "cannot be the same" in captured.err


def test_cli_merge_manifest_success(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "new_file.txt").write_text("new content")

    dest = tmp_path / "dest"
    dest.mkdir()
    # Create an existing manifest
    existing_manifest = {"paths": {"old_file.txt": "old_file.12345.txt"}, "version": "1.0"}
    with open(dest / "staticfiles.json", "w", encoding="utf-8") as f:
        json.dump(existing_manifest, f)

    main(["--manifest", "--merge-manifest", str(src), str(dest)])

    with open(dest / "staticfiles.json", encoding="utf-8") as f:
        manifest = json.load(f)

    # Should have both old and new paths
    assert "old_file.txt" in manifest["paths"]
    assert manifest["paths"]["old_file.txt"] == "old_file.12345.txt"
    assert "new_file.txt" in manifest["paths"]
    assert manifest["paths"]["new_file.txt"] == "new_file.txt"


def test_cli_merge_manifest_preserves_top_level_values(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "new_file.txt").write_text("new content")

    dest = tmp_path / "dest"
    dest.mkdir()

    existing_manifest = {
        "paths": {"old_file.txt": "old_file.12345.txt"},
        "version": "1.0",
        "custom": {"environment": "prod"},
    }
    with open(dest / "staticfiles.json", "w", encoding="utf-8") as f:
        json.dump(existing_manifest, f)

    main(["--manifest", "--merge-manifest", str(src), str(dest)])

    with open(dest / "staticfiles.json", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["custom"] == {"environment": "prod"}
    assert "old_file.txt" in manifest["paths"]
    assert "new_file.txt" in manifest["paths"]


def test_cli_merge_manifest_missing(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(SystemExit):
        main(["--manifest", "--merge-manifest", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Existing manifest not found" in captured.err


def test_cli_merge_manifest_invalid_object(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    with open(dest / "staticfiles.json", "w", encoding="utf-8") as f:
        json.dump(["not", "an", "object"], f)

    with pytest.raises(SystemExit):
        main(["--manifest", "--merge-manifest", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Existing manifest must be a JSON object" in captured.err


def test_cli_merge_manifest_invalid_paths_object(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    with open(dest / "staticfiles.json", "w", encoding="utf-8") as f:
        json.dump({"paths": []}, f)

    with pytest.raises(SystemExit):
        main(["--manifest", "--merge-manifest", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Existing manifest 'paths' must be a JSON object" in captured.err


def test_cli_merge_manifest_invalid_json(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / "staticfiles.json").write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["--manifest", "--merge-manifest", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Failed to read existing manifest" in captured.err


def test_cli_hash_logs_worker_errors(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content")
    dest = tmp_path / "dest"

    def mock_process(*_args, **_kwargs):
        msg = "hash failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(servestatic_cli.ManifestHashGenerator, "process", mock_process)

    main(["--hash", "--manifest", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Error hashing" in captured.out


def test_cli_compress_logs_worker_errors(tmp_path, monkeypatch, capsys):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content\n" * 1000)
    dest = tmp_path / "dest"

    def mock_compress(*_args, **_kwargs):
        msg = "compress failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(servestatic_cli.Compressor, "compress", mock_compress)

    main(["--compress", str(src), str(dest)])

    captured = capsys.readouterr()
    assert "Error compressing" in captured.out


def test_cli_passes_zstd_options_to_compressor(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    (src / "test.txt").write_text("content\n" * 1000)
    dest = tmp_path / "dest"
    dict_file = tmp_path / "dict.bin"
    dict_file.write_bytes(b"dict")

    captured_args: dict[str, object] = {}

    class DummyCompressor:
        def __init__(self, **kwargs):
            captured_args.update(kwargs)

        @staticmethod
        def should_compress(_filename):
            return False

        @staticmethod
        def compress(_path):
            return []

    monkeypatch.setattr(servestatic_cli, "Compressor", DummyCompressor)

    main([
        "--compress",
        "--zstd-dict",
        str(dict_file),
        "--zstd-dict-raw",
        "--zstd-level",
        "9",
        str(src),
        str(dest),
    ])

    assert captured_args["use_zstd"] is True
    assert captured_args["zstd_dict"] == str(dict_file)
    assert captured_args["zstd_dict_is_raw"] is True
    assert captured_args["zstd_level"] == 9
