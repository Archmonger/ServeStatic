from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Concatenate, ParamSpec, TypeVar, cast

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Iterable, Iterator
    from io import IOBase
    from os import PathLike

    from servestatic.responders import AsyncSlicedFile

P = ParamSpec("P")
T = TypeVar("T")

# This is the same size as wsgiref.FileWrapper
ASGI_BLOCK_SIZE = 8192


def get_block_size() -> int:
    return ASGI_BLOCK_SIZE


# Follow Django in treating URLs as UTF-8 encoded (which requires undoing the
# implicit ISO-8859-1 decoding applied in Python 3). Strictly speaking, URLs
# should only be ASCII anyway, but UTF-8 can be found in the wild.
def decode_path_info(path_info: str) -> str:
    return path_info.encode("iso-8859-1", "replace").decode("utf-8", "replace")


def ensure_leading_trailing_slash(path: str | None) -> str:
    path = (path or "").strip("/")
    return f"/{path}/" if path else "/"


def parse_accept_encoding(header: str) -> set[str]:
    """
    Return the set of content codings the client is willing to accept.

    The header is parsed as described in RFC 9110 section 12.5.3 rather than
    matched as a substring, so that a coding the client has refused with
    ``q=0`` is not offered to it, and a coding name is only recognised when it
    appears as a whole token.
    """
    accepted: set[str] = set()
    for entry in header.split(","):
        coding, _, params = entry.partition(";")
        coding = coding.strip().lower()
        if not coding:
            continue
        quality = 1.0
        for param in params.split(";"):
            name, sep, value = param.partition("=")
            if name.strip().lower() != "q":
                continue
            if not sep:
                break
            try:
                quality = float(value.strip())
            except ValueError:
                # An unparseable qvalue makes the whole entry invalid; treat
                # the coding as unacceptable rather than guess.
                quality = 0.0
            else:
                # Per RFC 9110 a qvalue must be a number in the range 0.000 to
                # 1.000; any other finite value (e.g. ``inf``) is invalid.
                if not math.isfinite(quality) or not 0.0 <= quality <= 1.0:
                    quality = 0.0
            break
        if quality > 0:
            accepted.add(coding)
    return accepted


def scantree(root: str | PathLike[str]) -> Iterator[tuple[str, os.stat_result]]:
    """
    Recurse the given directory yielding (pathname, os.stat(pathname)) pairs
    """
    for entry in os.scandir(root):
        if entry.is_dir():
            yield from scantree(entry.path)
        else:
            yield entry.path, entry.stat()


def stat_files(paths: Iterable[str]) -> dict[str, os.stat_result]:
    """Stat a list of file paths via threads."""

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {abs_path: executor.submit(os.stat, abs_path) for abs_path in paths}
        return {abs_path: future.result() for abs_path, future in futures.items()}


class AsyncToSyncIterator:
    """Converts any async iterator to sync as efficiently as possible while retaining
    full compatibility with any environment.

    This converter must create a temporary event loop in a thread for two reasons:
    1. Allows us to stream the iterator instead of buffering all contents in memory.
    2. Allows the iterator to be used in environments where an event loop may not exist,
    or may be closed unexpectedly.
    """

    def __init__(self, iterator: AsyncIterable[bytes]) -> None:
        self.iterator = iterator

    def __iter__(self) -> Iterator[bytes]:
        # Create a dedicated event loop to run the async iterator on.
        loop = asyncio.new_event_loop()
        thread_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ServeStatic-AsyncFile-Runtime"
        )
        try:
            # Convert from async to sync by stepping through the async iterator and yielding
            # the result of each step.
            generator = self.iterator.__aiter__()
            with contextlib.suppress(GeneratorExit, StopAsyncIteration):
                while True:
                    yield thread_executor.submit(loop.run_until_complete, generator.__anext__()).result()
        finally:
            loop.close()
            thread_executor.shutdown(wait=True)


def open_lazy(
    f: Callable[Concatenate[AsyncFile, P], Awaitable[T]],
) -> Callable[Concatenate[AsyncFile, P], Awaitable[T]]:
    """Decorator that ensures the file is open before calling a function.
    This can be turned into a @staticmethod on `AsyncFile` once we drop Python 3.9 compatibility.
    """

    @functools.wraps(f)
    async def wrapper(self: AsyncFile, *args: P.args, **kwargs: P.kwargs) -> T:
        if self.closed:
            msg = "I/O operation on closed file."
            raise ValueError(msg)
        if self.file_obj is None:
            self.file_obj = await self._execute(open, *self.open_args)
        return await f(self, *args, **kwargs)

    return wrapper


class AsyncFile:
    """An async clone of the Python `open` function that utilizes threads for async file IO.

    This currently only covers the file operations needed by ServeStatic, but could be expanded
    in the future."""

    def __init__(
        self,
        file_path: str | PathLike[str],
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[[str, int], int] | None = None,
    ) -> None:
        self.open_args: tuple[object, ...] = (
            file_path,
            mode,
            buffering,
            encoding,
            errors,
            newline,
            closefd,
            opener,
        )
        self.loop: asyncio.AbstractEventLoop | None = None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ServeStatic-AsyncFile")
        self.file_obj: IOBase | None = cast("IOBase | None", None)
        self.closed = False
        self._executor_shutdown = False

    def _shutdown_executor(self) -> None:
        if self._executor_shutdown:
            return
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            return
        self._executor_shutdown = True

    async def _execute(self, func: Callable[..., T], *args: object) -> T:
        """Run a function in a dedicated thread (specific to each AsyncFile instance)."""
        if self.loop is None:
            self.loop = asyncio.get_running_loop()
        return await self.loop.run_in_executor(self.executor, func, *args)

    async def close(self) -> None:
        self.closed = True
        if self.file_obj is not None:
            await self._execute(self.file_obj.close)
        self._shutdown_executor()

    @open_lazy
    async def read(self, size: int = -1) -> bytes:
        if self.file_obj is None:
            msg = "File object was not opened"
            raise RuntimeError(msg)
        return await self._execute(self.file_obj.read, size)

    @open_lazy
    async def seek(self, offset: int, whence: int = 0) -> int:
        if self.file_obj is None:
            msg = "File object was not opened"
            raise RuntimeError(msg)
        return await self._execute(self.file_obj.seek, offset, whence)

    @open_lazy
    async def __aenter__(self) -> AsyncFile:  # noqa: PYI034
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    def __del__(self) -> None:
        self._shutdown_executor()


class EmptyAsyncIterator:
    """Placeholder async iterator for responses that have no content."""

    def __aiter__(self) -> EmptyAsyncIterator:
        return self

    async def __anext__(self) -> bytes:
        raise StopAsyncIteration


class AsyncFileIterator:
    """Async iterator that yields chunks of data from the provided async file."""

    def __init__(self, async_file: AsyncFile | AsyncSlicedFile) -> None:
        self.async_file = async_file
        self.block_size = get_block_size()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async with self.async_file as file:
            while True:
                chunk = await file.read(self.block_size)
                if not chunk:
                    break
                yield chunk
