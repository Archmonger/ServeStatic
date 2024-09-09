from __future__ import annotations

import contextlib
import os
import re
import warnings
from posixpath import normpath
from typing import Callable
from wsgiref.headers import Headers

from .media_types import MediaTypes
from .responders import IsDirectoryError, MissingFileError, Redirect, StaticFile
from .utils import ensure_leading_trailing_slash, scantree


class BaseServeStatic:
    # Ten years is what nginx sets a max age if you use 'expires max;'
    # so we'll follow its lead
    FOREVER = 10 * 365 * 24 * 60 * 60

    __call__: Callable
    """"Subclasses must implement `__call__`"""

    def __init__(
        self,
        application,
        root=None,
        prefix=None,
        *,
        # Re-check the filesystem on every request so that any changes are
        # automatically picked up. NOTE: For use in development only, not supported
        # in production
        autorefresh: bool = False,
        max_age: int | None = 60,  # seconds
        # Set 'Access-Control-Allow-Origin: *' header on all files.
        # As these are all public static files this is safe (See
        # https://www.w3.org/TR/cors/#security) and ensures that things (e.g
        # webfonts in Firefox) still work as expected when your static files are
        # served from a CDN, rather than your primary domain.
        allow_all_origins: bool = True,
        charset: str = "utf-8",
        mimetypes: dict[str, str] | None = None,
        add_headers_function: Callable[[Headers, str, str], None] | None = None,
        index_file: str | bool | None = None,
        immutable_file_test: Callable | str | None = None,
    ):
        self.autorefresh = autorefresh
        self.max_age = max_age
        self.allow_all_origins = allow_all_origins
        self.charset = charset
        self.add_headers_function = add_headers_function
        self._immutable_file_test = immutable_file_test
        self._immutable_file_test_regex: re.Pattern | None = None
        self.media_types = MediaTypes(extra_types=mimetypes)
        self.application = application
        self.files = {}
        self.directories = []

        if index_file is True:
            self.index_file: str | None = "index.html"
        elif isinstance(index_file, str):
            self.index_file = index_file
        else:
            self.index_file = None

        if isinstance(immutable_file_test, str):
            self.user_immutable_file_test = re.compile(immutable_file_test)
        else:
            self.user_immutable_file_test = immutable_file_test

        if root is not None:
            self.add_files(root, prefix)

    def add_files(self, root, prefix=None):
        root = os.path.abspath(root)
        root = root.rstrip(os.path.sep) + os.path.sep
        prefix = ensure_leading_trailing_slash(prefix)
        if self.autorefresh:
            # Later calls to `add_files` overwrite earlier ones, hence we need
            # to store the list of directories in reverse order so later ones
            # match first when they're checked in "autorefresh" mode
            self.directories.insert(0, (root, prefix))
        elif os.path.isdir(root):
            self.update_files_dictionary(root, prefix)
        else:
            warnings.warn(f"No directory at: {root}", stacklevel=3)

    def update_files_dictionary(self, root, prefix):
        # Build a mapping from paths to the results of `os.stat` calls
        # so we only have to touch the filesystem once
        stat_cache = dict(scantree(root))
        for path in stat_cache:
            relative_path = path[len(root) :]
            relative_url = relative_path.replace("\\", "/")
            url = prefix + relative_url
            self.add_file_to_dictionary(url, path, stat_cache=stat_cache)

    def add_file_to_dictionary(self, url, path, stat_cache=None):
        if self.is_compressed_variant(path, stat_cache=stat_cache):
            return
        if self.index_file is not None and url.endswith(f"/{self.index_file}"):
            index_url = url[: -len(self.index_file)]
            index_no_slash = index_url.rstrip("/")
            self.files[url] = self.redirect(url, index_url)
            self.files[index_no_slash] = self.redirect(index_no_slash, index_url)
            url = index_url
        static_file = self.get_static_file(path, url, stat_cache=stat_cache)
        self.files[url] = static_file

    def find_file(self, url):
        # Optimization: bail early if the URL can never match a file
        if self.index_file is None and url.endswith("/"):
            return
        if not self.url_is_canonical(url):
            return
        for path in self.candidate_paths_for_url(url):
            with contextlib.suppress(MissingFileError):
                return self.find_file_at_path(path, url)

    def candidate_paths_for_url(self, url):
        for root, prefix in self.directories:
            if url.startswith(prefix):
                path = os.path.join(root, url[len(prefix) :])
                if os.path.commonprefix((root, path)) == root:
                    yield path

    def find_file_at_path(self, path, url):
        if self.is_compressed_variant(path):
            raise MissingFileError(path)

        if self.index_file is not None:
            if url.endswith("/"):
                path = os.path.join(path, self.index_file)
                return self.get_static_file(path, url)
            elif url.endswith(f"/{self.index_file}"):
                if os.path.isfile(path):
                    return self.redirect(url, url[: -len(self.index_file)])
            else:
                try:
                    return self.get_static_file(path, url)
                except IsDirectoryError:
                    if os.path.isfile(os.path.join(path, self.index_file)):
                        return self.redirect(url, f"{url}/")
            raise MissingFileError(path)

        return self.get_static_file(path, url)

    @staticmethod
    def url_is_canonical(url):
        """
        Check that the URL path is in canonical format i.e. has normalised
        slashes and no path traversal elements
        """
        if "\\" in url:
            return False
        normalised = normpath(url)
        if url.endswith("/") and url != "/":
            normalised += "/"
        return normalised == url

    @staticmethod
    def is_compressed_variant(path, stat_cache=None):
        if path[-3:] in (".gz", ".br"):
            uncompressed_path = path[:-3]
            if stat_cache is None:
                return os.path.isfile(uncompressed_path)
            else:
                return uncompressed_path in stat_cache
        return False

    def get_static_file(self, path, url, stat_cache=None):
        # Optimization: bail early if file does not exist
        if stat_cache is None and not os.path.exists(path):
            raise MissingFileError(path)
        headers = Headers([])
        self.add_mime_headers(headers, path, url)
        self.add_cache_headers(headers, path, url)
        if self.allow_all_origins:
            headers["Access-Control-Allow-Origin"] = "*"
        if self.add_headers_function is not None:
            self.add_headers_function(headers, path, url)
        return StaticFile(
            path,
            headers.items(),
            stat_cache=stat_cache,
            encodings={"gzip": f"{path}.gz", "br": f"{path}.br"},
        )

    def add_mime_headers(self, headers, path, url):
        media_type = self.media_types.get_type(path)
        if media_type.startswith("text/"):
            params = {"charset": str(self.charset)}
        else:
            params = {}
        headers.add_header("Content-Type", str(media_type), **params)

    def add_cache_headers(self, headers, path, url):
        if self.immutable_file_test(path, url):
            headers["Cache-Control"] = f"max-age={self.FOREVER}, public, immutable"
        elif self.max_age is not None:
            headers["Cache-Control"] = f"max-age={self.max_age}, public"

    def immutable_file_test(self, path, url):
        """
        This should be implemented by sub-classes (see e.g. ServeStaticMiddleware)
        or by setting the `immutable_file_test` config option
        """
        if self.user_immutable_file_test is not None:
            if callable(self.user_immutable_file_test):
                return self.user_immutable_file_test(path, url)
            return bool(self.user_immutable_file_test.search(url))
        return False

    def redirect(self, from_url, to_url):
        """
        Return a relative 302 redirect

        We use relative redirects as we don't know the absolute URL the app is
        being hosted under
        """
        if to_url == f"{from_url}/":
            relative_url = from_url.split("/")[-1] + "/"
        elif from_url == to_url + self.index_file:
            relative_url = "./"
        else:
            raise ValueError(f"Cannot handle redirect: {from_url} > {to_url}")
        if self.max_age is not None:
            headers = {"Cache-Control": f"max-age={self.max_age}, public"}
        else:
            headers = {}
        return Redirect(relative_url, headers=headers)
