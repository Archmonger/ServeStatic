from __future__ import annotations

import asyncio
from typing import Callable

from asgiref.compatibility import guarantee_single_callable

from servestatic.base import ServeStaticBase
from servestatic.utils import decode_path_info, get_block_size


class ServeStaticASGI(ServeStaticBase):
    application: Callable

    async def __call__(self, scope, receive, send) -> None:
        # Determine if the request is for a static file
        static_file = None
        if scope["type"] == "http":
            path = decode_path_info(scope["path"])
            if self.autorefresh:
                static_file = await asyncio.to_thread(self.find_file, path)
            else:
                static_file = self.files.get(path)

        # Serve static file if it exists
        if static_file:
            return await FileServerASGI(static_file)(scope, receive, send)

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

    def __init__(self, static_file) -> None:
        self.static_file = static_file
        self.block_size = get_block_size()

    async def __call__(self, scope, receive, send) -> None:
        # Convert ASGI headers into WSGI headers. Allows us to reuse all of our WSGI
        # header logic inside of aget_response().
        wsgi_headers = {
            "HTTP_" + key.decode().upper().replace("-", "_"): value.decode() for key, value in scope["headers"]
        }
        wsgi_headers["QUERY_STRING"] = scope["query_string"].decode()

        # Get the ServeStatic file response
        response = await self.static_file.aget_response(scope["method"], wsgi_headers)

        # Start a new HTTP response for the file
        await send({
            "type": "http.response.start",
            "status": response.status,
            "headers": [
                # Convert headers back to ASGI spec
                (key.lower().replace("_", "-").encode(), value.encode())
                for key, value in response.headers
            ],
        })

        # Head responses have no body, so we terminate early
        if response.file is None:
            await send({"type": "http.response.body", "body": b""})
            return

        # Stream the file response body
        async with response.file as async_file:
            while True:
                chunk = await async_file.read(self.block_size)
                more_body = bool(chunk)
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": more_body,
                })
                if not more_body:
                    break


class NotFoundASGI:
    """ASGI v3 application that returns a 404 Not Found response."""

    async def __call__(self, scope, receive, send) -> None:
        # Ensure this is an HTTP request
        if scope["type"] != "http":
            msg = "Default ASGI application only supports HTTP requests."
            raise RuntimeError(msg)

        # Send a 404 Not Found response
        await send({
            "type": "http.response.start",
            "status": 404,
            "headers": [(b"content-type", b"text/plain")],
        })
        await send({"type": "http.response.body", "body": b"Not Found"})
