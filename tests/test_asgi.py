from __future__ import annotations

import asyncio
import concurrent.futures
import gc
from pathlib import Path

import httpx
import pytest

from servestatic import utils as servestatic_utils
from servestatic.asgi import ServeStaticASGI

from .utils import AsgiHttpScopeEmulator, AsgiReceiveEmulator, AsgiScopeEmulator, AsgiSendEmulator, Files


async def request_asgi(application, method, path, **kwargs):
    transport = httpx.ASGITransport(app=application, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


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
    response = asyncio.run(request_asgi(application, "GET", "/static/app.js"))
    assert response.content == test_files.js_content
    assert "text/javascript" in response.headers["content-type"]
    assert response.headers["content-length"] == str(len(test_files.js_content))


def test_redirect_preserves_query_string(application, test_files):
    response = asyncio.run(request_asgi(application, "GET", "/static/with-index?v=1&x=2"))
    assert response.headers["location"] == "with-index/?v=1&x=2"


def test_user_app(application):
    response = asyncio.run(request_asgi(application, "GET", "/"))
    assert response.content == b"Not Found"
    assert "text/plain" in response.headers["content-type"]
    assert response.status_code == 404


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
    response = asyncio.run(request_asgi(application, "HEAD", "/static/app.js"))
    assert response.content == b""
    assert "text/javascript" in response.headers["content-type"]
    assert response.headers["content-length"] == str(len(test_files.js_content))


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
    response = asyncio.run(request_asgi(application, "GET", "/static/app.js", headers={"range": "bytes=0-13"}))
    assert response.content == test_files.js_content[:14]


def test_out_of_range_error(application, test_files):
    response = asyncio.run(request_asgi(application, "GET", "/static/app.js", headers={"range": "bytes=10000-11000"}))
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */%d" % len(test_files.js_content)


def test_wrong_method_type(application, test_files):
    response = asyncio.run(request_asgi(application, "PUT", "/static/app.js"))
    assert response.status_code == 405


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


def test_async_file_del_does_not_join_current_thread(test_files, capsys):
    file_path = str(Path(test_files.directory) / test_files.js_path)
    holder = {"async_file": servestatic_utils.AsyncFile(file_path, "rb")}
    executor = holder["async_file"].executor

    def drop_last_reference_from_worker():
        holder.pop("async_file")
        gc.collect()

    future = executor.submit(drop_last_reference_from_worker)
    try:
        future.result(timeout=5)
    except concurrent.futures.TimeoutError as e:
        pytest.fail(f"AsyncFile cleanup deadlocked: {e}")
    gc.collect()

    assert "cannot join current thread" not in capsys.readouterr().err


def test_async_file_read_raises_after_close():
    async_file = servestatic_utils.AsyncFile(__file__, "rb")
    asyncio.run(async_file.close())
    with pytest.raises(ValueError, match="closed file"):
        asyncio.run(async_file.read(1))


def test_async_file_shutdown_exception_is_ignored(monkeypatch):
    async_file = servestatic_utils.AsyncFile(__file__, "rb")

    def mock_shutdown(*_args, **_kwargs):
        msg = "shutdown failed"
        raise RuntimeError(msg)

    monkeypatch.setattr(async_file.executor, "shutdown", mock_shutdown)
    async_file._shutdown_executor()
    assert async_file._executor_shutdown is False


def test_asgi_initialize_preserves_user_application():
    async def user_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    app = ServeStaticASGI(user_app)
    response = asyncio.run(request_asgi(app, "GET", "/"))
    assert response.status_code == 200
    assert response.content == b"ok"
