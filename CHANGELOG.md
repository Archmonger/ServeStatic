# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
Using the following categories, list your changes in this order:
[Added, Changed, Deprecated, Removed, Fixed, Security]
-->

## [Unreleased]

### Added

-   Support Python 3.13.
-   Django `settings.py:SERVESTATIC_PRESERVE_QUERY_STRING_ON_REDIRECT` will forward the request query string when issuing redirects.

## [2.0.1] - 2024-09-13

### Fixed

-   Fix crash when running `manage.py collectstatic` when Django's `settings.py:STATIC_ROOT` is a `Path` object.

## [2.0.0] - 2024-09-12

### Added

-   Django `settings.py:SERVESTATIC_USE_MANIFEST` will allow ServeStatic to use the Django manifest rather than scanning the filesystem.
    -   When also using ServeStatic's `CompressedManifestStaticFilesStorage` backend, ServeStatic will no longer need to call `os.stat`.

### Changed

-   Minimum python version is now 3.9.
-   Django `setings.py:SERVESTATIC_USE_FINDERS` will now discover files strictly using the [finders API](https://docs.djangoproject.com/en/stable/ref/contrib/staticfiles/#finders-module). Previously, ServeStatic would also scan `settings.py:STATIC_ROOT` for files not found by the finders API.
-   Async file reading is now done via threads rather than [`aiofiles`](https://github.com/Tinche/aiofiles) due [recent performance tests](https://github.com/mosquito/aiofile/issues/88#issuecomment-2314380621).
-   `BaseServeStatic` has been renamed to `ServeStaticBase`.
-   `AsgiFileServer` has been renamed to `FileServerASGI`.
-   Lots of internal refactoring to improve performance, code quality, and maintainability.

## [1.2.0] - 2024-08-30

### Added

-   Verbose Django `404` error page when `settings.py:DEBUG` is `True`

### Fixed

-   Fix Django compatibility with third-party sync middleware.
    -   ServeStatic Django middleware now only runs in async mode to avoid clashing with Django's internal usage of `asgiref.AsyncToSync`.
-   Respect Django `settings.py:FORCE_SCRIPT_NAME` configuration value.

## [1.1.0] - 2024-08-27

### Added

-   Files are now compressed within a thread pool to increase performance.

### Fixed

-   Fix Django `StreamingHttpResponse must consume synchronous iterators` warning.
-   Fix Django bug where file paths could fail to be followed on Windows.

## [1.0.0] - 2024-05-08

### Changed

-   Forked from [`whitenoise`](https://github.com/evansd/whitenoise) to add ASGI support.

[Unreleased]: https://github.com/Archmonger/ServeStatic/compare/2.0.1...HEAD
[2.0.1]: https://github.com/Archmonger/ServeStatic/compare/2.0.0...2.0.1
[2.0.0]: https://github.com/Archmonger/ServeStatic/compare/1.2.0...2.0.0
[1.2.0]: https://github.com/Archmonger/ServeStatic/compare/1.1.0...1.2.0
[1.1.0]: https://github.com/Archmonger/ServeStatic/compare/1.0.0...1.1.0
[1.0.0]: https://github.com/Archmonger/ServeStatic/releases/tag/1.0.0
