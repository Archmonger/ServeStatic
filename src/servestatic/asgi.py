from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from asgiref.compatibility import guarantee_single_callable
from asgiref.typing import HTTPResponseBodyEvent, HTTPResponseStartEvent

from servestatic.base import ServeStaticBase
from servestatic.utils import decode_path_info, get_block_size, run_async_in_thread

if TYPE_CHECKING:
    from asgiref.typing import (
        ASGI3Application,
        ASGIReceiveCallable,
        ASGISendCallable,
        HTTPScope,
        Scope,
    )

    from servestatic.responders import AsyncSlicedFile, Redirect, StaticFile
    from servestatic.utils import AsyncFile


class ServeStaticASGI(ServeStaticBase):
    application: ASGI3Application

    async def __call__(self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        # Determine if the request is for a static file
        static_file = None
        if scope["type"] == "http":
            http_scope = cast("HTTPScope", scope)
            path = decode_path_info(http_scope["path"])
            if self.autorefresh:
                static_file = await run_async_in_thread(self.find_file, path)
            else:
                static_file = self.files.get(path)

        # Serve static file if it exists
        if static_file:
            return await FileServerASGI(static_file)(cast("HTTPScope", scope), receive, send)

        # Could not find a static file. Serve the default application instead.
        return await self.application(scope, receive, send)

    def initialize(self) -> None:
        """Ensure the ASGI application is initialized"""
        # If no application is provided, default to a "404 Not Found" app
        if not self.application:
            self.application = NotFoundASGI()

        # Ensure ASGI v2 is converted to ASGI v3
        self.application = guarantee_single_callable(self.application)


class FileServerASGI:
    """Primitive ASGI v3 application that streams a StaticFile over HTTP in chunks."""

    def __init__(self, static_file: StaticFile | Redirect) -> None:
        self.static_file = static_file
        self.block_size = get_block_size()

    async def __call__(self, scope: HTTPScope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        # Convert ASGI headers into WSGI headers. Allows us to reuse all of our WSGI
        # header logic inside of aget_response().
        wsgi_headers = {
            "HTTP_" + key.decode("latin-1").upper().replace("-", "_"): value.decode("latin-1")
            for key, value in scope["headers"]
        }
        wsgi_headers["QUERY_STRING"] = scope["query_string"].decode("latin-1")

        # Check which efficient file-transmission extensions the ASGI server
        # advertises (e.g. os.sendfile). `zerocopysend` supports slicing, so it is
        # preferred when available; `pathsend` is a full-file-only fallback.
        extensions = scope.get("extensions") or {}
        pathsend_supported = "http.response.pathsend" in extensions
        zerocopysend_supported = "http.response.zerocopysend" in extensions

        # Get the ServeStatic file response
        response = await self.static_file.aget_response(
            scope["method"], wsgi_headers, pathsend=pathsend_supported, zerocopysend=zerocopysend_supported
        )

        # Start a new HTTP response for the file
        await send(
            HTTPResponseStartEvent(
                type="http.response.start",
                status=int(response.status),
                headers=[
                    # Convert headers back to ASGI spec
                    (key.lower().replace("_", "-").encode("latin-1"), value.encode("latin-1"))
                    for key, value in response.headers
                    if value is not None
                ],
                trailers=False,
            )
        )

        # A pathsend response has no body streamed by us: the server sends the
        # file located at `response.path` (a full-file send only).
        # `http.response.pathsend` is not part of asgiref's `ASGISendEvent` union,
        # and `HTTPResponsePathsendEvent` is only available on asgiref >= 3.8, so
        # construct the event inline and cast it to satisfy the send callable's
        # type signature without a hard runtime dependency on that symbol.
        if response.file is None and response.path is not None:
            await send(cast("Any", {"type": "http.response.pathsend", "path": response.path}))
            return

        # A zero-copy response carries a real fd-backed file object that the server
        # transmits via `os.sendfile`. The ASGI spec requires the application to
        # close the descriptor once the send completes.
        if response.offset is not None and response.file is not None:
            event: dict[str, object] = {
                "type": "http.response.zerocopysend",
                "file": response.file,
                "offset": response.offset,
                "more_body": False,
            }
            if response.count is not None:
                event["count"] = response.count
            await send(cast("Any", event))
            response.file.close()
            return

        # Head responses have no body, so we terminate early
        if response.file is None:
            await send(HTTPResponseBodyEvent(type="http.response.body", body=b"", more_body=False))
            return

        # Stream the file response body
        async with cast("AsyncFile | AsyncSlicedFile", response.file) as async_file:
            while True:
                chunk = await async_file.read(self.block_size)
                more_body = bool(chunk)
                await send(HTTPResponseBodyEvent(type="http.response.body", body=chunk, more_body=more_body))
                if not more_body:
                    break


class NotFoundASGI:
    """ASGI v3 application that returns a 404 Not Found response."""

    async def __call__(self, scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        # Ensure this is an HTTP request
        if scope["type"] != "http":
            msg = "Default ASGI application only supports HTTP requests."
            raise RuntimeError(msg)

        # Send a 404 Not Found response
        await send(
            HTTPResponseStartEvent(
                type="http.response.start", status=404, headers=[(b"content-type", b"text/plain")], trailers=False
            )
        )
        await send(HTTPResponseBodyEvent(type="http.response.body", body=b"Not Found", more_body=False))
