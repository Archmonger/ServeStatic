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

## [Unreleased](https://github.com/Archmonger/ServeStatic/compare/1.1.0...HEAD)

### Fixed

-   Fix compatibility with other sync-only middleware
    -   Disable Django sync middleware capability to avoid issues with Django's usage of `asgiref.AsyncToSync`

## [1.1.0](https://github.com/Archmonger/ServeStatic/compare/1.0.0...1.1.0) - 2024-08-27

### Added

-   Files are now compressed within a thread pool to increase performance ([Upstream PR](https://github.com/evansd/whitenoise/pull/484))

### Fixed

-   Fix Django `StreamingHttpResponse must consume synchronous iterators` warning
-   Fix Django bug where file paths could fail to be followed on Windows ([Upstream PR](https://github.com/evansd/whitenoise/pull/474))

## [1.0.0](https://github.com/Archmonger/ServeStatic/releases/tag/1.0.0) - 2024-05-08

### Changed

-   Forked from [`whitenoise`](https://github.com/evansd/whitenoise) to add ASGI support.