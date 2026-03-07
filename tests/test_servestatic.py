from __future__ import annotations

import asyncio
import errno
import os
import re
import shutil
import stat
import sys
import tempfile
import warnings
from contextlib import closing
from pathlib import Path
from urllib.parse import urljoin
from wsgiref.headers import Headers
from wsgiref.simple_server import demo_app

import pytest

from servestatic import ServeStatic
from servestatic.base import ServeStaticBase
from servestatic.responders import FileEntry, MissingFileError, NotARegularFileError, Redirect, StaticFile

from .utils import AppServer, Files


class DummyServeStaticBase(ServeStaticBase):
    def initialize(self):
        pass

    def __call__(self, *args, **kwargs):
        return None


@pytest.fixture(scope="module")
def files():
    return Files(
        "assets",
        js="subdir/javascript.js",
        gzip="compressed.css",
        gzipped="compressed.css.gz",
        custom_mime="custom-mime.foobar",
        index="with-index/index.html",
    )


@pytest.fixture(params=[True, False], scope="module")
def application(request, files):
    # When run all test the application with autorefresh enabled and disabled
    # When testing autorefresh mode we first initialise the application with an
    # empty temporary directory and then copy in the files afterwards so we can
    # test that files added after initialisation are picked up correctly
    if request.param:
        tmp = tempfile.mkdtemp()
        app = _init_application(tmp, autorefresh=True)
        copytree(files.directory, tmp)
        yield app
        shutil.rmtree(tmp)
    else:
        yield _init_application(files.directory)


def _init_application(directory, **kwargs):
    def custom_headers(headers, path, url):
        if url.endswith(".css"):
            headers["X-Is-Css-File"] = "True"

    return ServeStatic(
        demo_app,
        root=directory,
        max_age=1000,
        mimetypes={".foobar": "application/x-foo-bar"},
        add_headers_function=custom_headers,
        index_file=True,
        **kwargs,
    )


@pytest.fixture(scope="module")
def server(application):
    app_server = AppServer(application)
    with closing(app_server):
        yield app_server


def assert_is_default_response(response):
    assert "Hello world!" in response.text


def test_get_file(server, files):
    response = server.get(files.js_url)
    assert response.content == files.js_content
    assert re.search(r"text/javascript\b", response.headers["Content-Type"])
    assert re.search(r'.*\bcharset="utf-8"', response.headers["Content-Type"])


def test_get_not_accept_gzip(server, files):
    response = server.get(files.gzip_url, headers={"Accept-Encoding": ""})
    assert response.content == files.gzip_content
    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"


def test_get_accept_star(server, files):
    response = server.get(files.gzip_url, headers={"Accept-Encoding": "*"})
    assert response.content == files.gzip_content
    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"


def test_get_accept_missing(server, files):
    response = server.get(
        files.gzip_url,
        # Using None is required to override requests default Accept-Encoding
        headers={"Accept-Encoding": None},
    )
    assert response.content == files.gzip_content
    assert "Content-Encoding" not in response.headers
    assert response.headers["Vary"] == "Accept-Encoding"


def test_get_accept_gzip(server, files):
    response = server.get(files.gzip_url)
    assert response.content == files.gzip_content
    assert response.headers["Content-Encoding"] == "gzip"
    assert response.headers["Vary"] == "Accept-Encoding"


def test_cannot_directly_request_gzipped_file(server, files):
    response = server.get(f"{files.gzip_url}.gz")
    assert_is_default_response(response)


def test_not_modified_exact(server, files):
    response = server.get(files.js_url)
    last_mod = response.headers["Last-Modified"]
    response = server.get(files.js_url, headers={"If-Modified-Since": last_mod})
    assert response.status_code == 304


def test_not_modified_future(server, files):
    last_mod = "Fri, 11 Apr 2100 11:47:06 GMT"
    response = server.get(files.js_url, headers={"If-Modified-Since": last_mod})
    assert response.status_code == 304


def test_modified(server, files):
    last_mod = "Fri, 11 Apr 2001 11:47:06 GMT"
    response = server.get(files.js_url, headers={"If-Modified-Since": last_mod})
    assert response.status_code == 200


def test_modified_mangled_date_firefox_91_0b3(server, files):
    last_mod = "Fri, 16 Jul 2021 09:09:1626426577S GMT"
    response = server.get(files.js_url, headers={"If-Modified-Since": last_mod})
    assert response.status_code == 200


def test_etag_matches(server, files):
    response = server.get(files.js_url)
    etag = response.headers["ETag"]
    response = server.get(files.js_url, headers={"If-None-Match": etag})
    assert response.status_code == 304


def test_etag_doesnt_match(server, files):
    etag = '"594bd1d1-36"'
    response = server.get(files.js_url, headers={"If-None-Match": etag})
    assert response.status_code == 200


def test_etag_overrules_modified_since(server, files):
    """
    Browsers send both headers so it's important that the ETag takes precedence
    over the last modified time, so that deploy-rollbacks are handled correctly.
    """
    headers = {
        "If-None-Match": '"594bd1d1-36"',
        "If-Modified-Since": "Fri, 11 Apr 2100 11:47:06 GMT",
    }
    response = server.get(files.js_url, headers=headers)
    assert response.status_code == 200


def test_max_age(server, files):
    response = server.get(files.js_url)
    assert response.headers["Cache-Control"], "max-age=1000 == public"


def test_other_requests_passed_through(server):
    response = server.get(f"/{AppServer.PREFIX}/not/static")
    assert_is_default_response(response)


def test_non_ascii_requests_safely_ignored(server):
    response = server.get(f"/{AppServer.PREFIX}/test\u263a")
    assert_is_default_response(response)


def test_add_under_prefix(server, files, application):
    prefix = "/prefix"
    application.add_files(files.directory, prefix=prefix)
    response = server.get(f"/{AppServer.PREFIX}{prefix}/{files.js_path}")
    assert response.content == files.js_content


def test_response_has_allow_origin_header(server, files):
    response = server.get(files.js_url)
    assert response.headers.get("Access-Control-Allow-Origin") == "*"


def test_response_has_correct_content_length_header(server, files):
    response = server.get(files.js_url)
    length = int(response.headers["Content-Length"])
    assert length == len(files.js_content)


def test_gzip_response_has_correct_content_length_header(server, files):
    response = server.get(files.gzip_url)
    length = int(response.headers["Content-Length"])
    assert length == len(files.gzipped_content)


def test_post_request_returns_405(server, files):
    response = server.request("post", files.js_url)
    assert response.status_code == 405


def test_head_request_has_no_body(server, files):
    response = server.request("head", files.js_url)
    assert response.status_code == 200
    assert not response.content


def test_custom_mimetype(server, files):
    response = server.get(files.custom_mime_url)
    assert re.search(r"application/x-foo-bar\b", response.headers["Content-Type"])


def test_custom_headers(server, files):
    response = server.get(files.gzip_url)
    assert response.headers["x-is-css-file"] == "True"


def test_index_file_served_at_directory_path(server, files):
    directory_url = files.index_url.rpartition("/")[0] + "/"
    response = server.get(directory_url)
    assert response.content == files.index_content


def test_index_file_path_redirected(server, files):
    directory_url = files.index_url.rpartition("/")[0] + "/"
    response = server.get(files.index_url, allow_redirects=False)
    location = urljoin(files.index_url, response.headers["Location"])
    assert response.status_code == 302
    assert location == directory_url


def test_index_file_path_redirected_with_query_string(server, files):
    directory_url = files.index_url.rpartition("/")[0] + "/"
    query_string = "v=1"
    response = server.get(f"{files.index_url}?{query_string}", allow_redirects=False)
    location = urljoin(files.index_url, response.headers["Location"])
    assert response.status_code == 302
    assert location == f"{directory_url}?{query_string}"


def test_directory_path_without_trailing_slash_redirected(server, files):
    directory_url = files.index_url.rpartition("/")[0] + "/"
    no_slash_url = directory_url.rstrip("/")
    response = server.get(no_slash_url, allow_redirects=False)
    location = urljoin(no_slash_url, response.headers["Location"])
    assert response.status_code == 302
    assert location == directory_url


def test_request_initial_bytes(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=0-13"})
    assert response.content == files.js_content[:14]


def test_request_trailing_bytes(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=-3"})
    assert response.content == files.js_content[-3:]


def test_request_middle_bytes(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=21-30"})
    assert response.content == files.js_content[21:31]


def test_overlong_ranges_truncated(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=21-100000"})
    assert response.content == files.js_content[21:]


def test_overlong_trailing_ranges_return_entire_file(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=-100000"})
    assert response.content == files.js_content


def test_out_of_range_error(server, files):
    response = server.get(files.js_url, headers={"Range": "bytes=10000-11000"})
    assert response.status_code == 416
    assert response.headers["Content-Range"] == f"bytes */{len(files.js_content)}"


def test_warn_about_missing_directories(application):
    # This is the one minor behavioural difference when autorefresh is
    # enabled: we don't warn about missing directories as these can be
    # created after the application is started
    if application.autorefresh:
        pytest.skip()
    with warnings.catch_warnings(record=True) as warning_list:
        application.add_files("/dev/null/nosuchdir\u2713")
    assert len(warning_list) == 1


def test_handles_missing_path_info_key(application):
    response = application(environ={}, start_response=lambda *_args: None)
    assert response


def test_cant_read_absolute_paths_on_windows(server):
    response = server.get(rf"/{AppServer.PREFIX}/C:/Windows/System.ini")
    assert_is_default_response(response)


def test_no_error_on_very_long_filename(server):
    response = server.get("/blah" * 1000)
    assert response.status_code != 500


def copytree(src, dst):
    for name in os.listdir(src):
        src_path = os.path.join(src, name)
        dst_path = os.path.join(dst, name)
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path)
        else:
            shutil.copy2(src_path, dst_path)


def build_symlink_escape_fixture():
    tmp_dir = tempfile.mkdtemp()
    static_dir = os.path.join(tmp_dir, "static")
    os.makedirs(static_dir, exist_ok=True)

    outside_content = b"outside-file-marker"
    outside_path = os.path.join(tmp_dir, "outside.txt")
    with open(outside_path, "wb") as outside_file:
        outside_file.write(outside_content)

    link_path = os.path.join(static_dir, "link-outside.txt")
    try:
        os.symlink(outside_path, link_path)
    except (OSError, NotImplementedError):
        shutil.rmtree(tmp_dir)
        pytest.skip("Symlink creation is unavailable in this environment")

    return tmp_dir, static_dir, outside_content


@pytest.mark.parametrize("autorefresh", [True, False])
def test_symlink_escape_is_blocked_by_default(autorefresh):
    tmp_dir, static_dir, _outside_content = build_symlink_escape_fixture()
    try:
        app = ServeStatic(None, root=static_dir, autorefresh=autorefresh)
        app_server = AppServer(app)
        with closing(app_server):
            response = app_server.get(f"/{AppServer.PREFIX}/link-outside.txt")
        assert response.status_code == 404
    finally:
        shutil.rmtree(tmp_dir)


@pytest.mark.parametrize("autorefresh", [True, False])
def test_symlink_escape_can_be_enabled(autorefresh):
    tmp_dir, static_dir, outside_content = build_symlink_escape_fixture()
    try:
        app = ServeStatic(None, root=static_dir, autorefresh=autorefresh, allow_unsafe_symlinks=True)
        app_server = AppServer(app)
        with closing(app_server):
            response = app_server.get(f"/{AppServer.PREFIX}/link-outside.txt")
        assert response.status_code == 200
        assert response.content == outside_content
    finally:
        shutil.rmtree(tmp_dir)


def test_immutable_file_test_accepts_regex():
    instance = ServeStatic(None, immutable_file_test=r"\.test$")
    assert instance.immutable_file_test("", "/myfile.test")
    assert not instance.immutable_file_test("", "file.test.txt")


def test_immutable_file_test_defaults_to_cli_hash_pattern():
    app = DummyServeStaticBase(None)
    assert app.immutable_file_test("", "/static/app.db8f2edc0c8a.js")
    assert not app.immutable_file_test("", "/static/app.js")


@pytest.mark.skipif(sys.version_info < (3, 4), reason="Pathlib was added in Python 3.4")
def test_directory_path_can_be_pathlib_instance():
    root = Path(Files("root").directory)
    # Check we can construct instance without it blowing up
    ServeStatic(None, root=root, autorefresh=True)


def fake_stat_entry(st_mode: int = stat.S_IFREG, st_size: int = 1024, st_mtime: int = 0) -> os.stat_result:
    return os.stat_result((
        st_mode,
        0,  # st_ino
        0,  # st_dev
        0,  # st_nlink
        0,  # st_uid
        0,  # st_gid
        st_size,
        0,  # st_atime
        st_mtime,
        0,  # st_ctime
    ))


def test_base_init_accepts_string_index_file():
    app = DummyServeStaticBase(None, index_file="home.html")
    assert app.index_file == "home.html"


def test_base_initialize_requires_override():
    with pytest.raises(NotImplementedError):
        ServeStaticBase(None)


def test_find_file_returns_none_for_trailing_slash_without_index_file():
    app = DummyServeStaticBase(None, autorefresh=True, index_file=None)
    assert app.find_file("/any/path/") is None


def test_find_file_at_path_without_index_file_returns_static_file():
    app = DummyServeStaticBase(None, index_file=None)
    result = app.find_file_at_path(__file__, "/test_servestatic.py")
    assert isinstance(result, StaticFile)


def test_find_file_at_path_index_file_missing_raises_missing_file_error():
    app = DummyServeStaticBase(None, index_file=True)
    with pytest.raises(MissingFileError):
        app.find_file_at_path("/tmp/does-not-exist/index.html", "/tmp/index.html")


def test_url_is_canonical_rejects_backslashes():
    assert not DummyServeStaticBase.url_is_canonical(r"/static\file.js")


def test_path_is_within_returns_false_when_commonpath_raises_value_error():
    assert not DummyServeStaticBase._path_is_within("/tmp/root", "relative/path")


def test_is_compressed_variant_detects_zstd_suffix_with_cache():
    cache = {"/tmp/app.js": fake_stat_entry(st_mtime=1)}
    assert DummyServeStaticBase.is_compressed_variant("/tmp/app.js.zstd", stat_cache=cache)


def test_immutable_file_test_supports_callable():
    app = DummyServeStaticBase(None, immutable_file_test=lambda path, url: url.endswith(".ok"))
    assert app.immutable_file_test("ignored", "/file.ok")


def test_redirect_raises_for_unhandled_pattern():
    app = DummyServeStaticBase(None, index_file="index.html")
    with pytest.raises(ValueError):
        app.redirect("/from", "/to")


def test_add_cache_headers_omits_header_when_max_age_none():
    app = DummyServeStaticBase(None, max_age=None)
    headers = Headers([])
    app.add_cache_headers(headers, __file__, "/file")
    assert "Cache-Control" not in headers


def test_get_static_file_omits_allow_all_origins_header_when_disabled():
    app = DummyServeStaticBase(None, allow_all_origins=False)
    static_file = app.get_static_file(__file__, "/coverage.py", stat_cache={__file__: fake_stat_entry(st_mtime=1)})
    headers = dict(static_file.alternatives[0][2])
    assert "Access-Control-Allow-Origin" not in headers


def test_get_static_file_prefers_zstd_when_requested():
    app = DummyServeStaticBase(None)
    stat_cache = {
        __file__: fake_stat_entry(st_size=1000, st_mtime=1),
        f"{__file__}.zstd": fake_stat_entry(st_size=200, st_mtime=1),
    }
    static_file = app.get_static_file(__file__, "/coverage.py", stat_cache=stat_cache)
    path, headers = static_file.get_path_and_headers({"HTTP_ACCEPT_ENCODING": "zstd, gzip"})
    assert path == f"{__file__}.zstd"
    assert Headers(headers)["Content-Encoding"] == "zstd"


def test_last_modified_not_set_when_mtime_is_zero():
    stat_cache = {__file__: fake_stat_entry()}
    responder = StaticFile(__file__, [], stat_cache=stat_cache)
    response = responder.get_response("GET", {})
    response.file.close()
    headers_dict = Headers(response.headers)
    assert "Last-Modified" not in headers_dict
    assert "ETag" not in headers_dict


def test_static_file_range_requires_content_length_header():
    responder = StaticFile(__file__, [], stat_cache={__file__: fake_stat_entry(st_mtime=1)})
    with pytest.raises(ValueError, match="Content-Length"):
        responder.get_range_response("bytes=0-3", [("X-Test", "1")], None)


def test_static_file_async_range_requires_content_length_header():
    responder = StaticFile(__file__, [], stat_cache={__file__: fake_stat_entry(st_mtime=1)})
    with pytest.raises(ValueError, match="Content-Length"):
        asyncio.run(responder.aget_range_response("bytes=0-3", [("X-Test", "1")], None))


def test_parse_byte_range_rejects_invalid_units_and_missing_separator():
    with pytest.raises(ValueError):
        StaticFile.parse_byte_range("items=0-1")
    with pytest.raises(ValueError):
        StaticFile.parse_byte_range("bytes0-1")


def test_parse_byte_range_requires_dash_separator():
    with pytest.raises(ValueError):
        StaticFile.parse_byte_range("bytes=10")


def test_get_path_and_headers_raises_when_no_alternatives_match():
    responder = StaticFile(__file__, [], stat_cache={__file__: fake_stat_entry(st_mtime=1)})
    responder.alternatives = []
    with pytest.raises(MissingFileError, match="No matching file"):
        responder.get_path_and_headers({"HTTP_ACCEPT_ENCODING": "gzip"})


def test_get_range_not_satisfiable_response_closes_file_handle():
    class DummyFile:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    handle = DummyFile()
    response = StaticFile.get_range_not_satisfiable_response(handle, 123)
    assert handle.closed
    assert int(response.status) == 416


def test_get_range_not_satisfiable_response_allows_none_file_handle():
    response = StaticFile.get_range_not_satisfiable_response(None, 10)
    assert int(response.status) == 416


def test_get_range_response_keeps_none_file_handle():
    responder = StaticFile(__file__, [], stat_cache={__file__: fake_stat_entry(st_size=32, st_mtime=1)})
    response = responder.get_range_response("bytes=0-1", [("Content-Length", "10")], None)
    assert response.file is None


def test_get_async_range_response_keeps_none_file_handle():
    responder = StaticFile(__file__, [], stat_cache={__file__: fake_stat_entry(st_size=32, st_mtime=1)})
    response = asyncio.run(responder.aget_range_response("bytes=0-1", [("Content-Length", "10")], None))
    assert response.file is None


def test_get_headers_preserves_existing_last_modified_and_etag():
    files = {None: FileEntry(__file__, {__file__: fake_stat_entry(st_size=10, st_mtime=5)})}
    headers = StaticFile.get_headers(
        [("Last-Modified", "Wed, 21 Oct 2015 07:28:00 GMT"), ("ETag", '"existing"')],
        files,
    )
    assert headers["Last-Modified"] == "Wed, 21 Oct 2015 07:28:00 GMT"
    assert headers["ETag"] == '"existing"'


def test_file_entry_reraises_unexpected_oserror():
    def raise_permission_error(_path):
        raise OSError(errno.EPERM, "permission denied")

    with pytest.raises(OSError):
        FileEntry.stat_regular_file("/tmp/no-access", raise_permission_error)


def test_file_entry_rejects_non_regular_non_directory_file():
    character_device_stat = fake_stat_entry(st_mode=stat.S_IFCHR)
    with pytest.raises(NotARegularFileError, match="Not a regular file"):
        FileEntry.stat_regular_file("/dev/char", lambda _path: character_device_stat)


def test_file_size_matches_range_with_range_header():
    stat_cache = {__file__: fake_stat_entry()}
    responder = StaticFile(__file__, [], stat_cache=stat_cache)
    response = responder.get_response("GET", {"HTTP_RANGE": "bytes=0-13"})
    file_size = len(response.file.read())
    assert file_size == 14


def test_single_byte_range_is_supported():
    stat_cache = {__file__: fake_stat_entry()}
    responder = StaticFile(__file__, [], stat_cache=stat_cache)
    response = responder.get_response("GET", {"HTTP_RANGE": "bytes=0-0"})
    assert int(response.status) == 206
    assert response.file is not None
    with open(__file__, "rb") as source:
        assert response.file.read() == source.read(1)
    response.file.close()


def test_chunked_file_size_matches_range_with_range_header():
    stat_cache = {__file__: fake_stat_entry()}
    responder = StaticFile(__file__, [], stat_cache=stat_cache)
    response = responder.get_response("GET", {"HTTP_RANGE": "bytes=0-13"})
    file_size = 0
    assert response.file is not None
    while response.file.read(1):
        file_size += 1
    assert file_size == 14


def test_redirect_preserves_query_string():
    responder = Redirect("/redirect/to/here/")
    response = responder.get_response("GET", {"QUERY_STRING": "foo=1&bar=2"})
    assert response.headers[0] == ("Location", "/redirect/to/here/?foo=1&bar=2")


def test_user_app():
    """Test that the user app is called when no static file is found."""
    application = ServeStatic(None)
    result = {}

    def start_response(status, headers):
        result["status"] = status
        result["headers"] = headers

    response = b"".join(application(environ={}, start_response=start_response))

    # Check if the response is a 404 Not Found
    assert result["status"] == "404 Not Found"
    assert b"Not Found" in response
