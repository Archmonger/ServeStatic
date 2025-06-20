from __future__ import annotations

import os
import threading
from wsgiref.simple_server import WSGIRequestHandler, make_server
from wsgiref.util import shift_path_info

import requests

TEST_FILE_PATH = os.path.join(os.path.dirname(__file__), "test_files")


class AppServer:
    """
    Wraps a WSGI application and allows you to make real HTTP
    requests against it
    """

    PREFIX = "subdir"

    def __init__(self, application):
        self.application = application
        self.server = make_server("127.0.0.1", 0, self.serve_under_prefix, handler_class=WSGIRequestHandler)

    def serve_under_prefix(self, environ, start_response):
        prefix = shift_path_info(environ)
        if prefix == self.PREFIX:
            return self.application(environ, start_response)
        start_response("404 Not Found", [])
        return []

    def get(self, *args, **kwargs):
        return self.request("get", *args, **kwargs)

    def request(self, method, path, *args, **kwargs):
        domain = self.server.server_address[0]
        port = self.server.server_address[1]
        url = f"http://{domain}:{port}{path}"
        thread = threading.Thread(target=self.server.handle_request)
        thread.start()
        response = requests.request(method, url, *args, **kwargs, timeout=5)
        thread.join()
        return response

    def close(self):
        self.server.server_close()


class AsgiAppServer:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":  # pragma: no cover
            msg = "Incorrect response type!"
            raise RuntimeError(msg)

        # Remove the prefix from the path
        scope["path"] = scope["path"].replace(f"/{AppServer.PREFIX}", "", 1)
        await self.application(scope, receive, send)


class Files:
    def __init__(self, directory="", **files):
        self.directory = os.path.join(TEST_FILE_PATH, directory)
        for name, path in files.items():
            url = f"/{AppServer.PREFIX}/{path}"
            with open(os.path.join(self.directory, path), "rb") as f:
                content = f.read()
            setattr(self, f"{name}_path", path)
            setattr(self, f"{name}_url", url)
            setattr(self, f"{name}_content", content)


class AsgiScopeEmulator(dict):
    """
    Simulate a minimal ASGI scope.
    Individual scope values can be overridden by passing a dictionary to the constructor.
    """

    def __init__(self, scope_overrides: dict | None = None):
        scope = {
            "asgi": {"version": "3.0"},
        }

        if scope_overrides:  # pragma: no cover
            scope.update(scope_overrides)

        super().__init__(scope)


class AsgiHttpScopeEmulator(AsgiScopeEmulator):
    """
    Simulate a HTTP ASGI scope.
    Individual scope values can be overridden by passing a dictionary to the constructor.
    """

    def __init__(self, scope_overrides: dict | None = None):
        scope = {
            "client": ["127.0.0.1", 64521],
            "headers": [
                (b"host", b"127.0.0.1:8000"),
                (b"connection", b"keep-alive"),
                (
                    b"sec-ch-ua",
                    b'"Not/A)Brand";v="99", "Brave";v="115", "Chromium";v="115"',
                ),
                (b"sec-ch-ua-mobile", b"?0"),
                (b"sec-ch-ua-platform", b'"Windows"'),
                (b"dnt", b"1"),
                (b"upgrade-insecure-requests", b"1"),
                (
                    b"user-agent",
                    b"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    b" (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                ),
                (
                    b"accept",
                    b"text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                ),
                (b"sec-gpc", b"1"),
                (b"sec-fetch-site", b"none"),
                (b"sec-fetch-mode", b"navigate"),
                (b"sec-fetch-user", b"?1"),
                (b"sec-fetch-dest", b"document"),
                (b"accept-encoding", b"gzip, deflate, br"),
                (b"accept-language", b"en-US,en;q=0.9"),
            ],
            "http_version": "1.1",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "raw_path": b"/",
            "root_path": "",
            "scheme": "http",
            "server": ["127.0.0.1", 8000],
            "type": "http",
        }

        if scope_overrides:  # pragma: no cover
            scope.update(scope_overrides)

        super().__init__(scope)


class AsgiReceiveEmulator:
    """Provides a list of events to be awaited by the ASGI application. This is designed
    be emulate HTTP events."""

    def __init__(self, *events):
        self.events = [{"type": "http.connect"}, *list(events)]

    async def __call__(self):
        return self.events.pop(0) if self.events else {"type": "http.disconnect"}


class AsgiSendEmulator:
    """Any events sent to this object will be stored in a list."""

    def __init__(self):
        self.message = []

    async def __call__(self, event):
        self.message.append(event)

    def __getitem__(self, index):
        return self.message[index]

    @property
    def body(self):
        """Combine all HTTP body messages into a single bytestring."""
        return b"".join([msg["body"] for msg in self.message if msg.get("body")])

    @property
    def body_count(self):
        """Return the number messages that contain body content."""
        return sum(bool(msg.get("body")) for msg in self.message)

    @property
    def headers(self):
        """Return the headers from the first event."""
        return dict(self[0]["headers"])

    @property
    def status(self):
        """Return the status from the first event."""
        return self[0]["status"]
