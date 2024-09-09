from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
from typing import AsyncIterable

from aiofiles.base import AiofilesContextManager


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
        thread_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ServeStatic"
        )

        # Convert from async to sync by stepping through the async iterator and yielding
        # the result of each step.
        generator = self.iterator.__aiter__()
        with contextlib.suppress(GeneratorExit, StopAsyncIteration):
            while True:
                yield thread_executor.submit(
                    loop.run_until_complete, generator.__anext__()
                ).result()
        loop.close()
        thread_executor.shutdown(wait=False)


class EmptyAsyncIterator:
    """Placeholder async iterator for responses that have no content."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class AsyncFileIterator:
    def __init__(self, file_context: AiofilesContextManager):
        self.file_context = file_context

    async def __aiter__(self):
        """Async iterator compatible with Django Middleware. Yields chunks of data from
        the provided async file context manager."""
        from servestatic.asgi import BLOCK_SIZE

        async with self.file_context as async_file:
            while True:
                chunk = await async_file.read(BLOCK_SIZE)
                if not chunk:
                    break
                yield chunk
