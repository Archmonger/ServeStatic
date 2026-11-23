from __future__ import annotations

import contextlib
import errno
import os
import re
import stat
from calendar import timegm
from email.utils import formatdate, parsedate
from http import HTTPStatus
from io import BufferedIOBase
from typing import TYPE_CHECKING, cast
from urllib.parse import quote
from wsgiref.headers import Headers

from servestatic.utils import AsyncFile, parse_accept_encoding

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence


class Response:  # noqa: B903
    __slots__ = ("count", "file", "headers", "offset", "path", "status")

    def __init__(
        self,
        status: HTTPStatus,
        headers: list[tuple[str, str | None]],
        file: BufferedIOBase | AsyncFile | AsyncSlicedFile | None,
        path: str | None = None,
        *,
        offset: int | None = None,
        count: int | None = None,
    ) -> None:
        self.status = status
        self.headers = headers
        self.file = file
        # Absolute path of the file being sent. This is only populated for a
        # full-file (non-sliced) response so the ASGI server can offload the
        # file transmission via the `http.response.pathsend` extension.
        self.path = path
        # Byte offset / count for the `http.response.zerocopysend` extension.
        # When `offset` is set, `file` is a real (fd-backed) file object that the
        # ASGI server transmits via `os.sendfile` and the application must close
        # once the send completes.
        self.offset = offset
        self.count = count


NOT_ALLOWED_RESPONSE = Response(
    status=HTTPStatus.METHOD_NOT_ALLOWED,
    headers=[("Allow", "GET, HEAD")],
    file=None,
)

# Headers which should be returned with a 304 Not Modified response as
# specified here: https://www.rfc-editor.org/rfc/rfc9110#section-15.4.5
NOT_MODIFIED_HEADERS = (
    "Access-Control-Allow-Origin",
    "Cache-Control",
    "Content-Location",
    "Date",
    "ETag",
    "Expires",
    "Vary",
)

# 416 responses should not be cached, so deliberately keep only the CORS
# header from the base headers so cross-origin range probes can read the
# response.
RANGE_NOT_SATISFIABLE_HEADERS = frozenset({"access-control-allow-origin"})

# Header names whose values are constant for a given file, and which are
# therefore safe to intern and share between `StaticFile` instances. Headers
# whose values can vary per response (such as Content-Length) are deliberately
# excluded.
SHARED_HEADERS = frozenset({
    "Access-Control-Allow-Origin",
    "Cache-Control",
    "Content-Encoding",
    "Content-Type",
    "Vary",
})

# Bound the header interning cache so that applications which generate unique
# per-file header values (for example through `SERVESTATIC_ADD_HEADERS_FUNCTION`)
# cannot make it grow without limit.
_MAX_SHARED_HEADERS = 1024

_shared_headers: dict[tuple[str, str | None], tuple[str, str | None]] = {}

# RFC 9110 section 13.1.2 allows `*` or a comma-separated list of entity tags.
# Opaque tags may themselves contain commas, so split the header into tokens
# rather than naively splitting on ",". Tokens may be quoted (the RFC form) or
# unquoted for backwards compatibility with custom ETag values supplied through
# `SERVESTATIC_ADD_HEADERS_FUNCTION`.
_IF_NONE_MATCH_TAG_RE = re.compile(r'(?:[^,"]|"[^"]*")+')

# Cap the amount of header data we parse, matching the limit used for
# `Accept-Encoding`, so an attacker cannot force unbounded work per request.
_MAX_IF_NONE_MATCH_LENGTH = 2048


def share_headers(headers: Sequence[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """
    Return a header list where repeated common header tuples are replaced with
    a single shared tuple object.

    This reduces the memory footprint of `StaticFile` instances, which each
    keep several header lists. The cache is bounded, so once it is full any
    header value which is not already cached is returned unchanged.
    """
    shared = _shared_headers
    result: list[tuple[str, str | None]] = []
    for header in headers:
        if header[0] not in SHARED_HEADERS:
            result.append(header)
        elif header in shared:
            result.append(shared[header])
        elif len(shared) < _MAX_SHARED_HEADERS:
            result.append(shared.setdefault(header, header))
        else:
            result.append(header)
    return result


class SlicedFile(BufferedIOBase):
    """
    A file like wrapper to handle seeking to the start byte of a range request
    and to return no further output once the end byte of a range request has
    been reached.
    """

    def __init__(self, fileobj: BufferedIOBase, start: int, end: int) -> None:
        self.fileobj = fileobj
        self.seeked = False
        self.start = start
        self.end = end
        self.remaining = end - start + 1

    def read(self, size: int = -1) -> bytes:  # pyright: ignore [reportIncompatibleMethodOverride]
        if not self.seeked:
            self.fileobj.seek(self.start)
            self.seeked = True
        if self.remaining <= 0:
            return b""
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = self.fileobj.read(size)
        self.remaining -= len(data)
        return data

    def close(self) -> None:
        super().close()
        self.fileobj.close()


class AsyncSlicedFile:
    """
    Variant of `SlicedFile` that works on async files.
    """

    def __init__(self, fileobj: AsyncFile, start: int, end: int) -> None:
        self.fileobj = fileobj
        self.seeked = False
        self.start = start
        self.end = end
        self.remaining = end - start + 1

    async def read(self, size: int = -1) -> bytes:
        if not self.seeked:
            await self.fileobj.seek(self.start)
            self.seeked = True
        if self.remaining <= 0:
            return b""
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = await self.fileobj.read(size)
        self.remaining -= len(data)
        return data

    async def close(self) -> None:
        await self.fileobj.close()

    async def __aenter__(self) -> AsyncSlicedFile:  # noqa: PYI034
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()


class StaticFile:
    __slots__ = ("alternatives", "etag", "last_modified", "not_modified_response")

    def __init__(
        self,
        path: str,
        headers: list[tuple[str, str]],
        encodings: Mapping[str, str] | None = None,
        stat_cache: Mapping[str, os.stat_result] | None = None,
    ) -> None:
        files = self.get_file_stats(path, encodings, stat_cache)
        headers_obj = self.get_headers(headers, files)
        self.last_modified = parsedate(headers_obj["Last-Modified"])
        self.etag = headers_obj["ETag"]
        self.not_modified_response = self.get_not_modified_response(headers_obj)
        self.alternatives = self.get_alternatives(headers_obj, files)

    def get_response(self, method: str, request_headers: Mapping[str, str]) -> Response:
        if method not in {"GET", "HEAD"}:
            return NOT_ALLOWED_RESPONSE
        if self.is_not_modified(request_headers):
            return self.not_modified_response
        path, headers = self.get_path_and_headers(request_headers)
        file_handle = open(path, "rb") if method != "HEAD" else None
        range_header = request_headers.get("HTTP_RANGE")
        if range_header and self.is_if_range_satisfied(request_headers):
            # If we can't interpret the Range request for any reason then
            # just ignore it and return the standard response (this
            # behaviour is allowed by the spec)
            with contextlib.suppress(ValueError):
                return self.get_range_response(range_header, headers, file_handle)
        return Response(HTTPStatus.OK, headers, file_handle)

    async def aget_response(
        self,
        method: str,
        request_headers: Mapping[str, str],
        *,
        pathsend: bool = False,
        zerocopysend: bool = False,
    ) -> Response:
        """Variant of `get_response` that works with async HTTP requests.
        To minimize code duplication, `request_headers` conforms to WSGI header spec.

        When `pathsend` is True, the caller has confirmed that the underlying ASGI
        server advertises the `http.response.pathsend` extension. In that case we
        skip opening an async file handle for a full-file send and instead populate
        `Response.path`, allowing the server to transmit the file by path.

        When `zerocopysend` is True, the caller has confirmed that the ASGI server
        advertises `http.response.zerocopysend`. This is the preferred offload path
        because, unlike `pathsend`, it supports slicing: a real (fd-backed) file
        handle is always opened and populated with the appropriate `offset`/`count`
        so the server can transmit the file (or a byte range) via `os.sendfile`.
        """
        if method not in {"GET", "HEAD"}:
            return NOT_ALLOWED_RESPONSE
        if self.is_not_modified(request_headers):
            return self.not_modified_response
        path, headers = self.get_path_and_headers(request_headers)
        range_header = request_headers.get("HTTP_RANGE")
        if range_header and self.is_if_range_satisfied(request_headers):
            # Range requests always require a real file handle. zerocopysend is the
            # only offload extension that supports slicing, so when it is advertised
            # we keep the raw (fd-backed) handle and annotate the response with the
            # slice offset/count for the server to transmit via os.sendfile.
            file_handle = self._open_for_send(path, method, zerocopysend)
            try:
                return await self.aget_range_response(range_header, headers, file_handle, zerocopysend=zerocopysend)
            except ValueError:
                # The Range header was uninterpretable; fall through to a full send.
                pass
            if method == "HEAD":
                return Response(HTTPStatus.OK, headers, None)
            if zerocopysend:
                return Response(HTTPStatus.OK, headers, file_handle, offset=0)
            if pathsend:
                # The server will transmit the whole file by path, so discard the
                # (always non-None for GET) handle we opened for range handling.
                await cast("AsyncFile", file_handle).close()
                return Response(HTTPStatus.OK, headers, None, path=path)
            # Otherwise keep the (open) handle so we can stream the full file.
            return Response(HTTPStatus.OK, headers, file_handle, path=path)
        if method == "HEAD":
            return Response(HTTPStatus.OK, headers, None)
        if zerocopysend:
            # zerocopysend is the preferred offload: it handles both full-file and
            # sliced sends. Open a real (fd-backed) handle and let the server
            # transmit the whole file via os.sendfile (offset=0, count omitted = EOF).
            return Response(HTTPStatus.OK, headers, self._open_for_send(path, method, zerocopysend), offset=0)
        if pathsend:
            # The server will stream the file by path, so we open no file handle
            # (and create no async file thread pool) on our side.
            return Response(HTTPStatus.OK, headers, None, path=path)
        # We do not await this async file handle to allow us the option of opening
        # it in a thread later.
        return Response(HTTPStatus.OK, headers, self._open_for_send(path, method, zerocopysend), path=path)

    @staticmethod
    def _open_for_send(
        path: str,
        method: str,
        zerocopysend: bool,
    ) -> BufferedIOBase | AsyncFile | None:
        """Open a file handle for the given method.

        For HEAD requests no body is sent, so no handle is opened. For zerocopysend
        we open a plain synchronous file object because the ASGI server needs its
        underlying OS file descriptor to perform the zero-copy sendfile; there is no
        benefit to async file IO since we never read through it in Python.
        """
        if method == "HEAD":
            return None
        if zerocopysend:
            return open(path, "rb")
        return AsyncFile(path, "rb")

    def get_range_response(
        self,
        range_header: str,
        base_headers: list[tuple[str, str | None]],
        file_handle: BufferedIOBase | None,
    ) -> Response:
        headers: list[tuple[str, str | None]] = []
        size: int | None = None
        for item in base_headers:
            if item[0] == "Content-Length":
                if item[1] is not None:
                    size = int(item[1])
            else:
                headers.append(item)
        if size is None:
            msg = "Content-Length header is required for range requests"
            raise ValueError(msg)
        start, end = self.get_byte_range(range_header, size)
        if start > end:
            return self.get_range_not_satisfiable_response(file_handle, size, headers)
        if file_handle is not None:
            file_handle = SlicedFile(file_handle, start, end)
        headers.extend((
            ("Content-Range", f"bytes {start}-{end}/{size}"),
            ("Content-Length", str(end - start + 1)),
        ))
        return Response(HTTPStatus.PARTIAL_CONTENT, headers, file_handle)

    async def aget_range_response(
        self,
        range_header: str,
        base_headers: list[tuple[str, str | None]],
        file_handle: BufferedIOBase | AsyncFile | None,
        *,
        zerocopysend: bool = False,
    ) -> Response:
        """Variant of `get_range_response` that works with async file objects."""
        headers: list[tuple[str, str | None]] = []
        size: int | None = None
        for item in base_headers:
            if item[0] == "Content-Length":
                if item[1] is not None:
                    size = int(item[1])
            else:
                headers.append(item)
        if size is None:
            msg = "Content-Length header is required for range requests"
            raise ValueError(msg)
        start, end = self.get_byte_range(range_header, size)
        if start > end:
            return await self.aget_range_not_satisfiable_response(file_handle, size, headers)
        if zerocopysend and file_handle is not None:
            # Keep the raw (fd-backed) handle and let the server transmit the
            # slice via sendfile using the byte range as offset/count.
            headers.extend((
                ("Content-Range", f"bytes {start}-{end}/{size}"),
                ("Content-Length", str(end - start + 1)),
            ))
            return Response(
                HTTPStatus.PARTIAL_CONTENT,
                headers,
                file_handle,
                offset=start,
                count=end - start + 1,
            )
        # Non-zerocopysend range sends always use an AsyncFile handle (opened via
        # `_open_for_send` with zerocopysend=False), so wrap it in an
        # AsyncSlicedFile to stream the requested byte range.
        sliced_file = AsyncSlicedFile(cast("AsyncFile", file_handle), start, end) if file_handle is not None else None
        headers.extend((
            ("Content-Range", f"bytes {start}-{end}/{size}"),
            ("Content-Length", str(end - start + 1)),
        ))
        return Response(HTTPStatus.PARTIAL_CONTENT, headers, sliced_file)

    def get_byte_range(self, range_header: str, size: int) -> tuple[int, int]:
        start, end = self.parse_byte_range(range_header)
        if start < 0:
            start = max(start + size, 0)
        end = size - 1 if end is None else min(end, size - 1)
        return start, end

    @staticmethod
    def parse_byte_range(range_header: str) -> tuple[int, int | None]:
        units, _, range_spec = range_header.strip().partition("=")
        if units != "bytes":
            raise ValueError
        # Only handle a single range spec. Multiple ranges will trigger a
        # ValueError below which will result in the Range header being ignored
        start_str, sep, end_str = range_spec.strip().partition("-")
        if not sep:
            raise ValueError
        if not start_str:
            start = -int(end_str)
            end = None
        else:
            start = int(start_str)
            end = int(end_str) if end_str else None
        return start, end

    @staticmethod
    def get_range_not_satisfiable_response(
        file_handle: BufferedIOBase | None,
        size: int,
        headers: list[tuple[str, str | None]] | None = None,
    ) -> Response:
        if file_handle is not None:
            file_handle.close()
        response_headers = [
            (key, value) for key, value in (headers or []) if key.lower() in RANGE_NOT_SATISFIABLE_HEADERS
        ]
        response_headers.append(("Content-Range", f"bytes */{size}"))
        return Response(
            HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
            response_headers,
            None,
        )

    @staticmethod
    async def aget_range_not_satisfiable_response(
        file_handle: BufferedIOBase | AsyncFile | None,
        size: int,
        headers: list[tuple[str, str | None]] | None = None,
    ) -> Response:
        """Variant of `get_range_not_satisfiable_response` that works with
        async file objects. Async file handles do not need to be closed, since they
        are only opened via context managers while being dispatched. A synchronous
        (zerocopysend) handle that was opened for a range request is closed here
        because the unsatisfiable response discards it."""
        if file_handle is not None and not isinstance(file_handle, AsyncFile):
            file_handle.close()
        response_headers = [
            (key, value) for key, value in (headers or []) if key.lower() in RANGE_NOT_SATISFIABLE_HEADERS
        ]
        response_headers.append(("Content-Range", f"bytes */{size}"))
        return Response(
            HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE,
            response_headers,
            None,
        )

    @staticmethod
    def get_file_stats(
        path: str,
        encodings: Mapping[str, str] | None,
        stat_cache: Mapping[str, os.stat_result] | None,
    ) -> dict[str | None, FileEntry]:
        # Primary file has an encoding of None
        files: dict[str | None, FileEntry] = {None: FileEntry(path, stat_cache)}
        if encodings:
            for encoding, alt_path in encodings.items():
                try:
                    files[encoding] = FileEntry(alt_path, stat_cache)
                except MissingFileError:
                    continue
        return files

    @staticmethod
    def get_headers(headers_list: list[tuple[str, str]], files: Mapping[str | None, FileEntry]) -> Headers:
        headers = Headers(headers_list)
        main_file = files[None]
        if len(files) > 1:
            headers["Vary"] = "Accept-Encoding"
        if "Last-Modified" not in headers:
            mtime = main_file.mtime
            # Not all filesystems report mtimes, and sometimes they report an
            # mtime of 0 which we know is incorrect
            if mtime:
                headers["Last-Modified"] = formatdate(mtime, usegmt=True)
        if "ETag" not in headers:
            last_modified = parsedate(headers["Last-Modified"])
            if last_modified:
                timestamp = timegm(last_modified)
                headers["ETag"] = f'"{timestamp:x}-{main_file.size:x}"'
        return headers

    @staticmethod
    def get_not_modified_response(headers: Headers) -> Response:
        not_modified_headers = [(key, headers[key]) for key in NOT_MODIFIED_HEADERS if key in headers]
        return Response(
            status=HTTPStatus.NOT_MODIFIED,
            headers=share_headers(not_modified_headers),
            file=None,
        )

    @staticmethod
    def get_alternatives(
        base_headers: Headers,
        files: Mapping[str | None, FileEntry],
    ) -> list[tuple[str | None, str, list[tuple[str, str | None]]]]:
        # Sort by size so that the smallest compressed alternative matches first
        alternatives = []
        files_by_size = sorted(files.items(), key=lambda i: i[1].size)
        for encoding, file_entry in files_by_size:
            headers = Headers(base_headers.items())
            headers["Content-Length"] = str(file_entry.size)
            if encoding:
                headers["Content-Encoding"] = encoding
            alternatives.append((encoding, file_entry.path, share_headers(headers.items())))
        return alternatives

    def is_not_modified(self, request_headers: Mapping[str, str]) -> bool:
        if_none_match = request_headers.get("HTTP_IF_NONE_MATCH")
        if if_none_match is not None:
            # RFC 9110 section 13.1.2: If-None-Match uses the weak comparison
            # function, so "W/" prefixes are ignored on both sides. The value
            # may be "*" or a comma-separated list of entity tags, and opaque
            # tags may contain commas. Unquoted tags are accepted for backwards
            # compatibility with custom ETag values.
            value = if_none_match[:_MAX_IF_NONE_MATCH_LENGTH].strip()
            if value == "*":
                return True
            if self.etag is None:
                return False
            etag = self.etag.removeprefix("W/")
            for match in _IF_NONE_MATCH_TAG_RE.finditer(value):
                if match.group().strip().removeprefix("W/") == etag:
                    return True
            return False
        if self.last_modified is None:
            return False
        try:
            last_requested = request_headers["HTTP_IF_MODIFIED_SINCE"]
        except KeyError:
            return False
        last_requested_ts = parsedate(last_requested)
        if last_requested_ts is not None:
            return last_requested_ts >= self.last_modified
        return False

    def is_if_range_satisfied(self, request_headers: Mapping[str, str]) -> bool:
        # https://www.rfc-editor.org/rfc/rfc9110#section-13.1.5
        if_range = request_headers.get("HTTP_IF_RANGE")
        if if_range is None:
            return True
        if_range = if_range.strip()
        if if_range.startswith("W/"):
            # Weak entity tags never match
            return False
        if if_range.startswith('"'):
            return if_range == self.etag
        if self.last_modified is None:
            return False
        return parsedate(if_range) == self.last_modified

    def get_path_and_headers(self, request_headers: Mapping[str, str]) -> tuple[str, list[tuple[str, str | None]]]:
        accepted = parse_accept_encoding(request_headers.get("HTTP_ACCEPT_ENCODING", ""))
        # These are sorted by size so ties go to the smallest
        best: tuple[str, list[tuple[str, str | None]]] | None = None
        best_quality = -1.0
        for encoding, path, headers in self.alternatives:
            if encoding is None:
                # Serve uncompressed as a last resort, even if refused, since
                # we cannot do better.
                quality = accepted.get("identity", 0.0)
            elif encoding in accepted:
                quality = accepted[encoding]
            else:
                continue
            if quality > best_quality:
                best = (path, headers)
                best_quality = quality
        if best is None:
            msg = "No matching file found from path."
            raise MissingFileError(msg)
        return best


class Redirect:
    __slots__ = ("headers", "location", "response")

    def __init__(self, location: str, headers: Mapping[str, str] | None = None) -> None:
        self.headers: list[tuple[str, str | None]] = list(headers.items()) if headers else []
        self.location = quote(location.encode("utf8"))
        self.response = Response(HTTPStatus.FOUND, [*self.headers, ("Location", self.location)], None)

    def get_response(self, method: str, request_headers: Mapping[str, str]) -> Response:
        query_string = request_headers.get("QUERY_STRING")
        if not query_string:
            return self.response
        return Response(
            HTTPStatus.FOUND,
            [*self.headers, ("Location", f"{self.location}?{query_string}")],
            None,
        )

    async def aget_response(
        self,
        method: str,
        request_headers: Mapping[str, str],
        *,
        pathsend: bool = False,
        zerocopysend: bool = False,
    ) -> Response:
        return self.get_response(method, request_headers)


class NotARegularFileError(Exception):
    pass


class MissingFileError(NotARegularFileError):
    pass


class IsDirectoryError(MissingFileError):
    pass


class FileEntry:
    __slots__ = ("mtime", "path", "size")

    def __init__(self, path: str, stat_cache: Mapping[str, os.stat_result] | None = None) -> None:
        self.path = path
        stat_function = os.stat if stat_cache is None else stat_cache.__getitem__
        stat_ = self.stat_regular_file(path, stat_function)
        self.size = stat_.st_size
        self.mtime = stat_.st_mtime

    @staticmethod
    def stat_regular_file(path: str, stat_function: Callable[[str], os.stat_result]) -> os.stat_result:
        """
        Wrap `stat_function` to raise appropriate errors if `path` is not a
        regular file
        """
        try:
            stat_result = stat_function(path)
        except KeyError as exc:
            raise MissingFileError(path) from exc
        except OSError as exc:
            if exc.errno in {errno.ENOENT, errno.ENAMETOOLONG, errno.ENOTDIR}:
                raise MissingFileError(path) from exc
            raise
        if not stat.S_ISREG(stat_result.st_mode):
            if stat.S_ISDIR(stat_result.st_mode):
                msg = f"Path is a directory: {path}"
                raise IsDirectoryError(msg)
            msg = f"Not a regular file: {path}"
            raise NotARegularFileError(msg)
        return stat_result
