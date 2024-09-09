from __future__ import annotations

import asyncio
import os
from posixpath import basename, normpath
from urllib.parse import urlparse
from urllib.request import url2pathname

import django
from aiofiles.base import AiofilesContextManager
from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.conf import settings as django_settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import (
    ManifestStaticFilesStorage,
    staticfiles_storage,
)
from django.http import FileResponse

from servestatic.responders import MissingFileError
from servestatic.utils import (
    AsyncFileIterator,
    AsyncToSyncIterator,
    EmptyAsyncIterator,
    ensure_leading_trailing_slash,
)
from servestatic.wsgi import ServeStatic

__all__ = ["ServeStaticMiddleware"]


class ServeStaticMiddleware(ServeStatic):
    """
    Wrap ServeStatic to allow it to function as Django middleware, rather
    than ASGI/WSGI middleware.
    """

    async_capable = True
    sync_capable = False

    def __init__(self, get_response=None, settings=django_settings):
        if not iscoroutinefunction(get_response):
            raise ValueError(
                "ServeStaticMiddleware requires an async compatible version of Django."
            )
        markcoroutinefunction(self)

        self.get_response = get_response
        debug = getattr(settings, "DEBUG")
        autorefresh = getattr(settings, "SERVESTATIC_AUTOREFRESH", debug)
        max_age = getattr(settings, "SERVESTATIC_MAX_AGE", 0 if debug else 60)
        allow_all_origins = getattr(settings, "SERVESTATIC_ALLOW_ALL_ORIGINS", True)
        charset = getattr(settings, "SERVESTATIC_CHARSET", "utf-8")
        mimetypes = getattr(settings, "SERVESTATIC_MIMETYPES", None)
        add_headers_function = getattr(
            settings, "SERVESTATIC_ADD_HEADERS_FUNCTION", None
        )
        self.index_file = getattr(settings, "SERVESTATIC_INDEX_FILE", None)
        immutable_file_test = getattr(settings, "SERVESTATIC_IMMUTABLE_FILE_TEST", None)
        self.use_finders = getattr(settings, "SERVESTATIC_USE_FINDERS", debug)
        self.use_manifest = getattr(
            settings,
            "SERVESTATIC_USE_MANIFEST",
            not debug and isinstance(staticfiles_storage, ManifestStaticFilesStorage),
        )
        self.static_prefix = getattr(settings, "SERVESTATIC_STATIC_PREFIX", None)
        self.static_root = getattr(settings, "STATIC_ROOT", None)
        self.keep_only_hashed_files = getattr(
            django_settings, "SERVESTATIC_KEEP_ONLY_HASHED_FILES", False
        )
        root = getattr(settings, "SERVESTATIC_ROOT", None)

        super().__init__(
            application=None,
            autorefresh=autorefresh,
            max_age=max_age,
            allow_all_origins=allow_all_origins,
            charset=charset,
            mimetypes=mimetypes,
            add_headers_function=add_headers_function,
            index_file=self.index_file,
            immutable_file_test=immutable_file_test,
        )

        if self.static_prefix is None:
            self.static_prefix = urlparse(settings.STATIC_URL or "").path
            if settings.FORCE_SCRIPT_NAME:
                script_name = settings.FORCE_SCRIPT_NAME.rstrip("/")
                if self.static_prefix.startswith(script_name):
                    self.static_prefix = self.static_prefix[len(script_name) :]
        self.static_prefix = ensure_leading_trailing_slash(self.static_prefix)

        if self.static_root and not self.use_manifest:
            self.add_files(self.static_root, prefix=self.static_prefix)

        if self.use_manifest:
            self.add_files_from_manifest()

        if self.use_finders and not self.autorefresh:
            self.add_files_from_finders()

        if root:
            self.add_files(root)

    async def __call__(self, request):
        """If the URL contains a static file, serve it. Otherwise, continue to the next
        middleware."""
        if self.autorefresh:
            static_file = await asyncio.to_thread(self.find_file, request.path_info)
        else:
            static_file = self.files.get(request.path_info)
        if static_file is not None:
            return await self.aserve(static_file, request)

        if django_settings.DEBUG and request.path.startswith(
            django_settings.STATIC_URL
        ):
            current_finders = finders.get_finders()
            app_dirs = [
                storage.location
                for finder in current_finders
                for storage in finder.storages.values()
            ]
            app_dirs = "\n• ".join(sorted(app_dirs))
            raise MissingFileError(
                f"ServeStatic did not find the file '{request.path.lstrip(django_settings.STATIC_URL)}' within the following paths:\n• {app_dirs}"
            )

        return await self.get_response(request)

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
        for url, path in files.items():
            self.add_file_to_dictionary(url, path)

    def add_files_from_manifest(self):
        if not isinstance(staticfiles_storage, ManifestStaticFilesStorage):
            raise ValueError(
                "SERVESTATIC_USE_MANIFEST is set to True but "
                "staticfiles storage is not using a manifest."
            )
        staticfiles: dict = staticfiles_storage.hashed_files

        for unhashed_name, hashed_name in staticfiles.items():
            file_path = staticfiles_storage.path(unhashed_name)

            if not self.keep_only_hashed_files:
                self.add_file_to_dictionary(
                    f"{self.static_prefix}{unhashed_name}", file_path
                )
            self.add_file_to_dictionary(f"{self.static_prefix}{hashed_name}", file_path)

        if staticfiles_storage.location:
            # Later calls to `add_files` overwrite earlier ones, hence we need
            # to store the list of directories in reverse order so later ones
            # match first when they're checked in "autorefresh" mode
            self.directories.insert(
                0, (staticfiles_storage.location, self.static_prefix)
            )

    def candidate_paths_for_url(self, url):
        if self.use_finders and url.startswith(self.static_prefix):
            relative_url = url[len(self.static_prefix) :]
            path = url2pathname(relative_url)
            normalized_path = normpath(path).lstrip("/")
            path = finders.find(normalized_path)
            if path:
                yield path
        yield from super().candidate_paths_for_url(url)

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
        return bool(static_url and basename(static_url) == basename(url))

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


class AsyncServeStaticFileResponse(FileResponse):
    """
    Wrap Django's FileResponse with a few differences:
    - Prevent setting any default headers (headers are already generated by ServeStatic).
    - Enables async compatibility.
    """

    def set_headers(self, *args, **kwargs):
        pass

    def _set_streaming_content(self, value):
        if isinstance(value, AiofilesContextManager):
            value = AsyncFileIterator(value)

        # Django < 4.2 doesn't support async file responses, so we convert to sync
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
