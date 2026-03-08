from __future__ import annotations

from typing import TYPE_CHECKING
from wsgiref.util import FileWrapper

from servestatic.base import ServeStaticBase
from servestatic.utils import decode_path_info

if TYPE_CHECKING:
    from collections.abc import Iterable
    from wsgiref.types import StartResponse, WSGIApplication, WSGIEnvironment

    from servestatic.responders import Redirect, StaticFile


class ServeStatic(ServeStaticBase):
    application: WSGIApplication

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        # Determine if the request is for a static file
        path = decode_path_info(environ.get("PATH_INFO", ""))
        static_file = self.find_file(path) if self.autorefresh else self.files.get(path)

        # Serve static file if it exists
        if static_file:
            return FileServerWSGI(static_file)(environ, start_response)

        # Could not find a static file. Serve the default application instead.
        return self.application(environ, start_response)

    def initialize(self) -> None:
        """Ensure the WSGI application is initialized."""
        # If no application is provided, default to a "404 Not Found" app
        self.application = self.application or NotFoundWSGI()


class FileServerWSGI:
    """Primitive WSGI application that streams a StaticFile over HTTP in chunks."""

    def __init__(self, static_file: StaticFile | Redirect) -> None:
        self.static_file = static_file

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        response = self.static_file.get_response(environ["REQUEST_METHOD"], environ)
        status_line = f"{response.status} {response.status.phrase}"
        headers = [(key, value) for key, value in response.headers if value is not None]
        start_response(status_line, headers)
        if response.file is not None:
            # Try to use a more efficient transmit method, if available
            file_wrapper = environ.get("wsgi.file_wrapper", FileWrapper)
            return file_wrapper(response.file)
        return []


class NotFoundWSGI:
    """A WSGI application that returns a 404 Not Found response."""

    def __call__(self, environ: WSGIEnvironment, start_response: StartResponse) -> Iterable[bytes]:
        status = "404 Not Found"
        headers = [("Content-Type", "text/plain; charset=utf-8")]
        start_response(status, headers)
        return [b"Not Found"]
