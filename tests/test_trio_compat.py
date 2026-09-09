"""Verify ServeStatic's ASGI serving core works under the trio async backend.

ServeStatic's file-serving path historically used asyncio-specific primitives
(``asyncio.to_thread`` and ``asyncio.get_running_loop``), which crash under a
trio event loop with ``RuntimeError: no running event loop`` and yield empty
response bodies. These tests drive the application and the low-level thread
offload helpers under ``trio.run`` to lock in multi-backend compatibility.
"""

from __future__ import annotations

from pathlib import Path

import pytest

trio = pytest.importorskip("trio")

from servestatic import utils as servestatic_utils
from servestatic.asgi import ServeStaticASGI

from .utils import AsgiHttpScopeEmulator, AsgiReceiveEmulator, AsgiSendEmulator, Files


async def run_asgi_under_trio(application, path: str) -> AsgiSendEmulator:
    """Run a single ASGI request through the app on a trio event loop."""
    scope = AsgiHttpScopeEmulator({"path": path})
    receive = AsgiReceiveEmulator()
    send = AsgiSendEmulator()
    await application(scope, receive, send)
    return send


@pytest.fixture
def test_files():
    return Files(
        js=str(Path("static") / "app.js"),
        txt=str(Path("static") / "large-file.txt"),
    )


@pytest.mark.parametrize("autorefresh", [True, False])
def test_trio_serves_static_file(autorefresh, test_files):
    application = ServeStaticASGI(None, root=test_files.directory, autorefresh=autorefresh)

    async def run():
        return await run_asgi_under_trio(application, "/static/app.js")

    send = trio.run(run)
    assert send.body == test_files.js_content
    assert send.headers[b"content-length"] == str(len(test_files.js_content)).encode()


def test_trio_large_file(test_files):
    application = ServeStaticASGI(None, root=test_files.directory)

    async def run():
        return await run_asgi_under_trio(application, "/static/large-file.txt")

    send = trio.run(run)
    assert len(send.body) > 0
    assert send.body == test_files.txt_content


def test_trio_current_async_library_reports_trio():
    async def check():
        assert servestatic_utils.current_async_library() == "trio"

    trio.run(check)


def test_trio_run_async_in_thread():
    async def check():
        value = await servestatic_utils.run_async_in_thread(lambda: 21 * 2)
        assert value == 42

    trio.run(check)


def test_trio_async_file_read(test_files):
    file_path = str(Path(test_files.directory) / test_files.js_path)
    async_file = servestatic_utils.AsyncFile(file_path, "rb")

    async def run():
        # The first read triggers the lazy open, which offloads to a thread.
        data = await async_file.read(-1)
        await async_file.close()
        return data

    content = trio.run(run)
    assert content == test_files.js_content
