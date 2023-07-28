from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from whitenoise.asgi import AsgiWhiteNoise

from .utils import AsgiReceiveEmulator, AsgiScopeEmulator, AsgiSendEmulator, Files


@pytest.fixture()
def test_files():
    return Files(
        js=str(Path("static") / "app.js"),
    )


@pytest.fixture(params=[True, False])
def application(request, test_files):
    """Return an ASGI application can serve the test files."""

    async def asgi_app(scope, receive, send):
        if scope["type"] != "http":
            raise RuntimeError("Incorrect response type!")

        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [[b"content-type", b"text/plain"]],
            }
        )
        await send({"type": "http.response.body", "body": b"Not Found"})

    return AsgiWhiteNoise(
        asgi_app, root=test_files.directory, autorefresh=request.param
    )


def test_get_js_static_file(application, test_files):
    scope = AsgiScopeEmulator({"path": "/static/app.js"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == test_files.js_content
    assert b"text/javascript" in send.headers[b"content-type"]
    assert send.headers[b"content-length"] == str(len(test_files.js_content)).encode()


def test_user_app(application):
    scope = AsgiScopeEmulator({"path": "/"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == b"Not Found"
    assert b"text/plain" in send.headers[b"content-type"]
    assert send.status == 404


def test_ws_scope(application):
    scope = AsgiScopeEmulator({"type": "websocket"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    with pytest.raises(RuntimeError):
        asyncio.run(application(scope, receive, send))


def test_head_request(application, test_files):
    scope = AsgiScopeEmulator({"path": "/static/app.js", "method": "HEAD"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    asyncio.run(application(scope, receive, send))
    assert send.body == b""
    assert b"text/javascript" in send.headers[b"content-type"]
    assert send.headers[b"content-length"] == str(len(test_files.js_content)).encode()
    assert len(send.events) == 2


def test_small_block_size(application, test_files):
    scope = AsgiScopeEmulator({"path": "/static/app.js"})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    application.block_size = 10
    asyncio.run(application(scope, receive, send))
    assert send[1]["body"] == test_files.js_content[:10]
