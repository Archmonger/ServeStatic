from servestatic.manifest_hash import generate_hash, get_hashed_name, hash_path


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
