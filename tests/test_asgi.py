from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from servestatic import utils as servestatic_utils
from servestatic.asgi import ServeStaticASGI

from .utils import AsgiHttpScopeEmulator, AsgiReceiveEmulator, AsgiScopeEmulator, AsgiSendEmulator, Files


@pytest.fixture
def test_files():
    return Files(
        js=str(Path("static") / "app.js"),
        index=str(Path("static") / "with-index" / "index.html"),
        txt=str(Path("static") / "large-file.txt"),
    )


@pytest.fixture(params=[True, False])
def application(request, test_files):
    """Return an ASGI application can serve the test files."""

    return ServeStaticASGI(None, root=test_files.directory, autorefresh=request.param, index_file=True)


def test_get_js_static_file(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == test_files.js_content
    assert b"text/javascript" in send.headers[b"content-type"]
    assert send.headers[b"content-length"] == str(len(test_files.js_content)).encode()


def test_redirect_preserves_query_string(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/with-index", "query_string": b"v=1&x=2"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.headers[b"location"] == b"with-index/?v=1&x=2"


def test_user_app(application):
    scope = AsgiHttpScopeEmulator({"path": "/"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == b"Not Found"
    assert b"text/plain" in send.headers[b"content-type"]
    assert send.status == 404


def test_ws_scope(application):
    scope = AsgiHttpScopeEmulator({"type": "websocket"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    with pytest.raises(RuntimeError):
        asyncio.run(application(scope, receive, send))


def test_lifespan_scope(application):
    scope = AsgiScopeEmulator({"type": "lifespan"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    with pytest.raises(RuntimeError):
        asyncio.run(application(scope, receive, send))


def test_head_request(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js", "method": "HEAD"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == b""
    assert b"text/javascript" in send.headers[b"content-type"]
    assert send.headers[b"content-length"] == str(len(test_files.js_content)).encode()
    assert len(send.message) == 2


def test_small_block_size(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()

    default_block_size = servestatic_utils.ASGI_BLOCK_SIZE
    servestatic_utils.ASGI_BLOCK_SIZE = 10
    asyncio.run(application(scope, receive, send))
    assert send[1]["body"] == test_files.js_content[:10]
    servestatic_utils.ASGI_BLOCK_SIZE = default_block_size


def test_request_range_response(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js", "headers": [(b"range", b"bytes=0-13")]})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == test_files.js_content[:14]


def test_out_of_range_error(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js", "headers": [(b"range", b"bytes=10000-11000")]})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.status == 416
    assert send.headers[b"content-range"] == b"bytes */%d" % len(test_files.js_content)


def test_wrong_method_type(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/app.js", "method": "PUT"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.status == 405


def test_large_static_file(application, test_files):
    scope = AsgiHttpScopeEmulator({"path": "/static/large-file.txt", "headers": []})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert len(send.body) == len(test_files.txt_content)
    assert len(send.body) == 10001
    assert send.body == test_files.txt_content
    assert send.body_count == 2
    assert send.headers[b"content-length"] == str(len(test_files.txt_content)).encode()
    assert b"text/plain" in send.headers[b"content-type"]
