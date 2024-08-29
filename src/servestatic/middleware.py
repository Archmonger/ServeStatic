from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
from posixpath import basename, normpath
from typing import AsyncIterable
from urllib.parse import urlparse
from urllib.request import url2pathname

import django
from aiofiles.base import AiofilesContextManager
from asgiref.sync import async_to_sync, iscoroutinefunction, markcoroutinefunction
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.http import FileResponse
from django.urls import get_script_prefix

from .asgi import BLOCK_SIZE
from .string_utils import ensure_leading_trailing_slash
from .wsgi import ServeStatic

__all__ = ["ServeStaticMiddleware"]


class ServeStaticFileResponse(FileResponse):
    """
    Wrap Django's FileResponse to prevent setting any default headers. For the
    most part these just duplicate work already done by ServeStatic but in some
    cases (e.g. the content-disposition header introduced in Django 3.0) they
    are actively harmful.
    """

    def set_headers(self, *args, **kwargs):
        pass


class AsyncServeStaticFileResponse(ServeStaticFileResponse):
    """
    Wrap Django's FileResponse with a few differences:
    - Prevent setting any default headers (headers are already generated by ServeStatic).
    - Only generates responses for async file handles.
    - Provides Django an async iterator for more efficient file streaming.
    - Opens the file handle within the iterator to avoid WSGI thread ownership issues.
    """

    def _set_streaming_content(self, value):
        if isinstance(value, AiofilesContextManager):
            value = AsyncFileIterator(value)

        # Django < 4.2 doesn't support async file responses, so convert to sync
        if django.VERSION < (4, 2) and hasattr(value, "__aiter__"):
            value = AsyncToSyncIterator(value)

        super()._set_streaming_content(value)

    if django.VERSION >= (4, 2):

        def __iter__(self):
            """The way that Django 4.2+ converts async to sync is inefficient, so
            we override it with a better implementation. Django only uses this method
            when running via WSGI."""
            try:
                return iter(self.streaming_content)
            except TypeError:
                return iter(AsyncToSyncIterator(self.streaming_content))


class ServeStaticMiddleware(ServeStatic):
    """
    Wrap ServeStatic to allow it to function as Django middleware, rather
    than ASGI/WSGI middleware.
    """

    async_capable = True
    sync_capable = True

    def __init__(self, get_response, settings=settings):
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

        try:
            autorefresh: bool = settings.SERVESTATIC_AUTOREFRESH
        except AttributeError:
            autorefresh = settings.DEBUG
        try:
            max_age = settings.SERVESTATIC_MAX_AGE
        except AttributeError:
            if settings.DEBUG:
                max_age = 0
            else:
                max_age = 60
        try:
            allow_all_origins = settings.SERVESTATIC_ALLOW_ALL_ORIGINS
        except AttributeError:
            allow_all_origins = True
        try:
            charset = settings.SERVESTATIC_CHARSET
        except AttributeError:
            charset = "utf-8"
        try:
            mimetypes = settings.SERVESTATIC_MIMETYPES
        except AttributeError:
            mimetypes = None
        try:
            add_headers_function = settings.SERVESTATIC_ADD_HEADERS_FUNCTION
        except AttributeError:
            add_headers_function = None
        try:
            index_file = settings.SERVESTATIC_INDEX_FILE
        except AttributeError:
            index_file = None
        try:
            immutable_file_test = settings.SERVESTATIC_IMMUTABLE_FILE_TEST
        except AttributeError:
            immutable_file_test = None

        super().__init__(
            application=None,
            autorefresh=autorefresh,
            max_age=max_age,
            allow_all_origins=allow_all_origins,
            charset=charset,
            mimetypes=mimetypes,
            add_headers_function=add_headers_function,
            index_file=index_file,
            immutable_file_test=immutable_file_test,
        )

        try:
            self.use_finders = settings.SERVESTATIC_USE_FINDERS
        except AttributeError:
            self.use_finders = settings.DEBUG

        try:
            self.static_prefix = settings.SERVESTATIC_STATIC_PREFIX
        except AttributeError:
            self.static_prefix = urlparse(settings.STATIC_URL or "").path
            script_prefix = get_script_prefix().rstrip("/")
            if script_prefix:
                if self.static_prefix.startswith(script_prefix):
                    self.static_prefix = self.static_prefix[len(script_prefix) :]
        self.static_prefix = ensure_leading_trailing_slash(self.static_prefix)

        self.static_root = settings.STATIC_ROOT
        if self.static_root:
            self.add_files(self.static_root, prefix=self.static_prefix)

        try:
            root = settings.SERVESTATIC_ROOT
        except AttributeError:
            root = None
        if root:
            self.add_files(root)

        if self.use_finders and not self.autorefresh:
            self.add_files_from_finders()

    def __call__(self, request):
        if iscoroutinefunction(self.get_response):
            return self.acall(request)

        # Allow Django >= 3.2 to use async file responses when running via ASGI, even
        # if Django forces this middleware to run synchronously
        if django.VERSION >= (3, 2):
            return async_to_sync(self.acall)(request)

        # Django version has no async uspport
        return self.call(request)

    def call(self, request):
        """If the URL contains a static file, serve it. Otherwise, continue to the next
        middleware."""
        if self.autorefresh:
            static_file = self.find_file(request.path_info)
        else:
            static_file = self.files.get(request.path_info)
        if static_file is not None:
            return self.serve(static_file, request)

        # Run the next middleware in the stack
        return self.get_response(request)

    async def acall(self, request):
        """If the URL contains a static file, serve it. Otherwise, continue to the next
        middleware."""
        if self.autorefresh and hasattr(asyncio, "to_thread"):
            # Use a thread while searching disk for files on Python 3.9+
            static_file = await asyncio.to_thread(self.find_file, request.path_info)
        elif self.autorefresh:
            static_file = self.find_file(request.path_info)
        else:
            static_file = self.files.get(request.path_info)
        if static_file is not None:
            return await self.aserve(static_file, request)

        # Run the next middleware in the stack. Note that get_response can sometimes be sync if
        # middleware was run in mixed sync-async mode
        # https://docs.djangoproject.com/en/stable/topics/http/middleware/#asynchronous-support
        if iscoroutinefunction(self.get_response):
            return await self.get_response(request)
        return self.get_response(request)

    @staticmethod
    def serve(static_file, request):
        response = static_file.get_response(request.method, request.META)
        status = int(response.status)
        http_response = ServeStaticFileResponse(
            response.file or (),
            status=status,
        )
        # Remove default content-type
        del http_response["content-type"]
        for key, value in response.headers:
            http_response[key] = value
        return http_response

    @staticmethod
    async def aserve(static_file, request):
        response = await static_file.aget_response(request.method, request.META)
        status = int(response.status)
        http_response = AsyncServeStaticFileResponse(
            response.file or EmptyAsyncIterator(),
            status=status,
        )
        # Remove default content-type
        del http_response["content-type"]
        for key, value in response.headers:
            http_response[key] = value
        return http_response

    def add_files_from_finders(self):
        files = {}
        for finder in finders.get_finders():
            for path, storage in finder.list(None):
                prefix = (getattr(storage, "prefix", None) or "").strip("/")
                url = "".join(
                    (
                        self.static_prefix,
                        prefix,
                        "/" if prefix else "",
                        path.replace("\\", "/"),
                    )
                )
                # Use setdefault as only first matching file should be used
                files.setdefault(url, storage.path(path))
        stat_cache = {path: os.stat(path) for path in files.values()}
        for url, path in files.items():
            self.add_file_to_dictionary(url, path, stat_cache=stat_cache)

    def candidate_paths_for_url(self, url):
        if self.use_finders and url.startswith(self.static_prefix):
            relative_url = url[len(self.static_prefix) :]
            path = url2pathname(relative_url)
            normalized_path = normpath(path).lstrip("/")
            path = finders.find(normalized_path)
            if path:
                yield path
        paths = super().candidate_paths_for_url(url)
        for path in paths:
            yield path

    def immutable_file_test(self, path, url):
        """
        Determine whether given URL represents an immutable file (i.e. a
        file with a hash of its contents as part of its name) which can
        therefore be cached forever
        """
        if not url.startswith(self.static_prefix):
            return False
        name = url[len(self.static_prefix) :]
        name_without_hash = self.get_name_without_hash(name)
        if name == name_without_hash:
            return False
        static_url = self.get_static_url(name_without_hash)
        # If the static_url function maps the name without hash
        # back to the original name, then we know we've got a
        # versioned filename
        if static_url and basename(static_url) == basename(url):
            return True
        return False

    def get_name_without_hash(self, filename):
        """
        Removes the version hash from a filename e.g, transforms
        'css/application.f3ea4bcc2.css' into 'css/application.css'

        Note: this is specific to the naming scheme used by Django's
        CachedStaticFilesStorage. You may have to override this if
        you are using a different static files versioning system
        """
        name_with_hash, ext = os.path.splitext(filename)
        name = os.path.splitext(name_with_hash)[0]
        return name + ext

    def get_static_url(self, name):
        try:
            return staticfiles_storage.url(name)
        except ValueError:
            return None


class AsyncFileIterator:
    def __init__(self, file_context: AiofilesContextManager):
        self.file_context = file_context

    async def __aiter__(self):
        """Async iterator compatible with Django Middleware. Yields chunks of data from
        the provided async file context manager."""
        async with self.file_context as async_file:
            while True:
                chunk = await async_file.read(BLOCK_SIZE)
                if not chunk:
                    break
                yield chunk


class EmptyAsyncIterator:
    """Async iterator for responses that have no content. Prevents Django 4.2+ from
    showing "StreamingHttpResponse must consume synchronous iterators" warnings."""

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class AsyncToSyncIterator:
    """Converts any async iterator to sync as efficiently as possible while retaining
    full compatibility with any environment.

    This converter must create a temporary event loop in a thread for two reasons:
    1) Allows us to stream the iterator instead of buffering all contents in memory.
    2) Allows the iterator to be used in environments where an event loop may not exist,
    or may be closed unexpectedly.

    Currently used to add async file compatibility to Django WSGI and Django versions
    that do not support __aiter__.
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
        thread_executor.shutdown()
