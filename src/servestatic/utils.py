from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from io import IOBase
from typing import TYPE_CHECKING, Callable, cast

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import AsyncIterable, Iterable

    from servestatic.responders import AsyncSlicedFile

# This is the same size as wsgiref.FileWrapper
ASGI_BLOCK_SIZE = 8192


def get_block_size():
    return ASGI_BLOCK_SIZE


# Follow Django in treating URLs as UTF-8 encoded (which requires undoing the
# implicit ISO-8859-1 decoding applied in Python 3). Strictly speaking, URLs
# should only be ASCII anyway, but UTF-8 can be found in the wild.
def decode_path_info(path_info):
    return path_info.encode("iso-8859-1", "replace").decode("utf-8", "replace")


def ensure_leading_trailing_slash(path):
    path = (path or "").strip("/")
    return f"/{path}/" if path else "/"


def scantree(root):
    """
    Recurse the given directory yielding (pathname, os.stat(pathname)) pairs
    """
    for entry in os.scandir(root):
        if entry.is_dir():
            yield from scantree(entry.path)
        else:
            yield entry.path, entry.stat()


def stat_files(paths: Iterable[str]) -> dict:
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

    def __init__(self, iterator: AsyncIterable):
        self.iterator = iterator

    def __iter__(self):
        # Create a dedicated event loop to run the async iterator on.
        loop = asyncio.new_event_loop()
        thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ServeStatic")

        # Convert from async to sync by stepping through the async iterator and yielding
        # the result of each step.
        generator = self.iterator.__aiter__()
        with contextlib.suppress(GeneratorExit, StopAsyncIteration):
            while True:
                yield thread_executor.submit(loop.run_until_complete, generator.__anext__()).result()
        loop.close()
        thread_executor.shutdown(wait=True)


def open_lazy(f):
    """Decorator that ensures the file is open before calling a function.
    This can be turned into a @staticmethod on `AsyncFile` once we drop Python 3.9 compatibility.
    """

    @functools.wraps(f)
    async def wrapper(self: AsyncFile, *args, **kwargs):
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
        file_path,
        mode: str = "r",
        buffering: int = -1,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
        closefd: bool = True,
        opener: Callable[[str, int], int] | None = None,
    ):
        self.open_args = (
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
        self.lock = threading.Lock()
        self.file_obj: IOBase = cast(IOBase, None)
        self.closed = False

    async def _execute(self, func, *args):
        """Run a function in a dedicated thread (specific to each AsyncFile instance)."""
        if self.loop is None:
            self.loop = asyncio.get_event_loop()
        with self.lock:
            return await self.loop.run_in_executor(self.executor, func, *args)

    def open_raw(self):
        """Open the file without using the executor."""
        self.executor.shutdown(wait=True)
        return open(*self.open_args)  # pylint: disable=unspecified-encoding

    async def close(self):
        self.closed = True
        if self.file_obj:
            await self._execute(self.file_obj.close)

    @open_lazy
    async def read(self, size=-1):
        return await self._execute(self.file_obj.read, size)

    @open_lazy
    async def seek(self, offset, whence=0):
        return await self._execute(self.file_obj.seek, offset, whence)

    @open_lazy
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        self.executor.shutdown(wait=True)


class EmptyAsyncIterator:
    """Placeholder async iterator for responses that have no content."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class AsyncFileIterator:
    """Async iterator that yields chunks of data from the provided async file."""

    def __init__(self, async_file: AsyncFile | AsyncSlicedFile):
        self.async_file = async_file
        self.block_size = get_block_size()

    async def __aiter__(self):
        async with self.async_file as file:
            while True:
                chunk = await file.read(self.block_size)
                if not chunk:
                    break
                yield chunk
