# Changelog

All notable changes to this project will be documented in this file.

<!--attr-start-->

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--attr-end-->

<!--
Using the following categories, list your changes in this order:

### Added
-   for new features.

### Changed
-   for changes in existing functionality.

### Deprecated
-   for soon-to-be removed features.

### Removed
-   for removed features.

### Fixed
-   for bug fixes.

### Security
-   for vulnerability fixes.
 -->

<!--changelog-start-->

## [Unreleased](https://github.com/Archmonger/ServeStatic/compare/1.2.0...HEAD)

### Added

-   Utilize Django manifest rather than scanning the directories for files when using `SERVESTATIC_USE_MANIFEST`. (Derivative of [upstream PR](https://github.com/evansd/whitenoise/pull/275))

### Changed

-   Minimum python version is now 3.9.
-   Django `setings.py:SERVESTATIC_USE_FINDERS` will now strictly use Django finders to locate files. ServeStatic will no longer manually traverse the `STATIC_ROOT` directory to add additional files when this settings is enabled.

## [1.2.0](https://github.com/Archmonger/ServeStatic/compare/1.1.0...1.2.0) - 2024-08-30

### Added

-   Verbose Django `404` error page when `settings.py:DEBUG` is `True` (Derivative of [upstream PR](https://github.com/evansd/whitenoise/pull/366))

### Fixed

-   Fix Django compatibility with third-party sync middleware
    -   ServeStatic Django middleware now only runs in async mode to avoid clashing with Django's internal usage of `asgiref.AsyncToSync`
-   Respect Django `settings.py:FORCE_SCRIPT_NAME` configuration value (Derivative of [upstream PR](https://github.com/evansd/whitenoise/pull/486))

## [1.1.0](https://github.com/Archmonger/ServeStatic/compare/1.0.0...1.1.0) - 2024-08-27

### Added

-   Files are now compressed within a thread pool to increase performance (Derivative of [upstream PR](https://github.com/evansd/whitenoise/pull/484))

### Fixed

-   Fix Django `StreamingHttpResponse must consume synchronous iterators` warning
-   Fix Django bug where file paths could fail to be followed on Windows (Derivative of [upstream PR](https://github.com/evansd/whitenoise/pull/474))

## [1.0.0](https://github.com/Archmonger/ServeStatic/releases/tag/1.0.0) - 2024-05-08

### Changed

-   Forked from [`whitenoise`](https://github.com/evansd/whitenoise) to add ASGI support.
