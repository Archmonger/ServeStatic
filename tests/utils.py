from __future__ import annotations

import os
from collections import UserDict
from urllib.parse import quote
from wsgiref.util import shift_path_info

import httpx

TEST_FILE_PATH = os.path.join(os.path.dirname(__file__), "test_files")


class AppServer:
    """
    Wraps a WSGI application and allows you to make real HTTP
    requests against it
    """

    PREFIX = "subdir"
    DEFAULT_ACCEPT_ENCODING = "gzip, deflate, br"

    def __init__(self, application):
        self.application = application
        self.client = httpx.Client(
            transport=httpx.WSGITransport(app=self.serve_under_prefix, raise_app_exceptions=False),
            base_url="http://testserver",
        )

    def serve_under_prefix(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")
        try:
            path_info.encode("iso-8859-1")
            path_info = ""
        except UnicodeEncodeError:
            # WSGI servers expose PATH_INFO as latin-1 decoded bytes. Recreate
            # that shape for non-ASCII paths so Django can recover UTF-8 bytes.
            environ["PATH_INFO"] = path_info.encode("utf-8").decode("iso-8859-1")

        prefix = shift_path_info(environ)
        if prefix == self.PREFIX:
            return self.application(environ, start_response)
        start_response("404 Not Found", [])
        return []

    def get(self, *args, **kwargs):
        return self.request("get", *args, **kwargs)

    def request(self, method, path, *args, **kwargs):
        # Keep compatibility with previous requests-based helpers.
        allow_redirects = kwargs.pop("allow_redirects", True)
        headers = dict(kwargs.pop("headers", {}) or {})

        # requests percent-encodes non-ASCII URL paths before they hit WSGI.
        path = quote(path, safe="/%?=&:+,;@#")

        # Always send Accept-Encoding unless tests explicitly set it to None.
        has_accept_encoding = any(key.lower() == "accept-encoding" for key in headers)
        if not has_accept_encoding:
            headers["Accept-Encoding"] = self.DEFAULT_ACCEPT_ENCODING

        # Preserve existing test semantics where `None` means "no accepted encodings".
        for key, value in list(headers.items()):
            if key.lower() == "accept-encoding" and value is None:
                headers[key] = ""

        # A value of None means "omit this header" in existing tests.
        headers = {key: value for key, value in headers.items() if value is not None}

        response = self.client.request(
            method,
            path,
            *args,
            headers=headers,
            follow_redirects=allow_redirects,
            **kwargs,
        )
        return _ResponseAdapter(response)

    def close(self):
        self.client.close()


class _ResponseAdapter:
    """Compat adapter that presents a requests-like interface over httpx responses."""

    def __init__(self, response: httpx.Response):
        self._response = response

    def __getattr__(self, item):
        return getattr(self._response, item)

    @property
    def url(self):
        return str(self._response.url)


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


class AsgiScopeEmulator(UserDict):
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
