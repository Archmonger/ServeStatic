from servestatic import manifest_hash
from servestatic.manifest_hash import ManifestHashGenerator, generate_hash, get_hashed_name, hash_path


def test_generate_hash():
    assert generate_hash(b"testcontent") == "296ab49302a4"


def test_hash_path(tmp_path):
    p = tmp_path / "test.txt"
    p.write_bytes(b"testcontent")
    assert hash_path(p) == "296ab49302a4"

    # Also test with str path
    assert hash_path(str(p)) == "296ab49302a4"


def test_get_hashed_name():
    assert get_hashed_name("test.txt", content=b"testcontent") == "test.296ab49302a4.txt"
    assert get_hashed_name("styles.css", content=b"testcontent") == "styles.296ab49302a4.css"
    assert get_hashed_name("scripts/app.js", content=b"testcontent") == "scripts/app.296ab49302a4.js"

    # Or with windows backslashes
    assert get_hashed_name(r"scripts\app.js", content=b"testcontent") == r"scripts\app.296ab49302a4.js"


def test_get_hashed_name_from_file(tmp_path):
    p = tmp_path / "test.txt"
    p.write_bytes(b"testcontent")

    hashed_p = get_hashed_name(p)

    # Check that the suffix is correct
    assert hashed_p.endswith("test.296ab49302a4.txt")


def test_process_skips_copy_when_hashed_name_matches_input(tmp_path, monkeypatch):
    path = tmp_path / "test.txt"
    path.write_bytes(b"testcontent")

    monkeypatch.setattr(manifest_hash, "get_hashed_name", str)

    def fail_copy(*_args, **_kwargs):
        msg = "copy2 should not be called when hashed path matches input path"
        raise AssertionError(msg)

    monkeypatch.setattr(manifest_hash.shutil, "copy2", fail_copy)

    generator = ManifestHashGenerator(root=tmp_path, keep_original=False)
    rel_original, rel_hashed = generator.process(path)

    assert rel_original == "test.txt"
    assert rel_hashed == "test.txt"
    assert path.exists()
