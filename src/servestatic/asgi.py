from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from asgiref.compatibility import guarantee_single_callable
from asgiref.typing import HTTPResponseBodyEvent, HTTPResponseStartEvent

from servestatic.base import ServeStaticBase
from servestatic.utils import decode_path_info, get_block_size

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
                static_file = await asyncio.to_thread(self.find_file, path)
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

        # Get the ServeStatic file response
        response = await self.static_file.aget_response(scope["method"], wsgi_headers)

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
