# CLI Reference

ServeStatic comes with a handy command line utility which can generate compressed versions of your static files and hash the file names (for cache busting, mimicking Django's `ManifestStaticFilesStorage`).

You can either run this during development and commit your generated/compressed files to your repository, or you can run this as part of your build and deploy processes.

!!! note

    This CLI is intended for non-Django deployments. For Django users, compression and hashing is handled completely automatically within Django's `collectstatic` command if you're using ServeStatic's `CompressedManifestStaticFilesStorage` storage backend.

## Usage

```console linenums="0"
$ servestatic --help
usage: servestatic [-h] [--all] [--hash] [--manifest] [--merge-manifest]
                   [--compress] [--clear] [-q] [--copy-original] [--no-gzip]
                   [--no-brotli] [--no-zstd] [--zstd-dict ZSTD_DICT]
                   [--zstd-dict-raw] [--zstd-level ZSTD_LEVEL]
                   [-e EXCLUDE]
                   src dest

Process static files: copy, optionally hash, and compress.

positional arguments:
  src                   Source directory containing static files.
  dest                  Destination directory for processed files.

options:
  -h, --help            show this help message and exit
  --all                 Perform all operations (equivalent to --hash
                        --manifest --compress). (default: False)
  --hash                Generate hashed versions of files. (default: False)
  --manifest            Generate a manifest file (staticfiles.json). (default:
                        False)
  --merge-manifest      Merge the new manifest with an existing manifest in the
                        dest directory. Fails if the existing manifest is not
                        found. (default: False)
  --compress            Generate compressed versions (gzip/zstd/brotli) of
                        files.
                        (default: False)
  --clear               Empty the destination directory before processing.
                        (default: False)
  -q, --quiet           Don't produce log output. (default: False)
  --copy-original       Copy the original unhashed files into the dest directory
                        alongside the hashed versions (only applies with
                        --hash). (default: False)
  --no-gzip             Don't produce gzip '.gz' files (only applies with
                        --compress). (default: True)
  --no-brotli           Don't produce brotli '.br' files (only applies with
                        --compress). (default: True)
  --no-zstd             Don't produce zstd '.zstd' files (only applies with
                        --compress). (default: True)
  --zstd-dict ZSTD_DICT
                        Path to a zstd dictionary file (only applies with
                        --compress). (default: None)
  --zstd-dict-raw       Treat the zstd dictionary as raw content (only applies
                        with --compress). (default: False)
  --zstd-level ZSTD_LEVEL
                        Compression level for zstd output (only applies with
                        --compress). (default: None)
  -e EXCLUDE, --exclude EXCLUDE
                        Glob pattern(s) to exclude from processing
                        (compression/hashing). These files are still copied.
                        (default: None)
```

## Compression Details

When ServeStatic builds its list of available files, it optionally checks for corresponding files with `.gz`, `.zstd`, and `.br` suffixes (e.g., `scripts/app.js`, `scripts/app.js.gz`, `scripts/app.js.zstd`, and `scripts/app.js.br`). If it finds them, it will serve those compressed versions when clients indicate support via `Accept-Encoding`.

On Python 3.14+, zstd support is built in via the standard library.

On older Python versions, Brotli support is available by installing the [Brotli](https://pypi.org/project/Brotli/) package.

You can also pass a custom zstd dictionary with `--zstd-dict` and optionally mark it raw with `--zstd-dict-raw`.

## Hash Details

This command will output a standard cache-busting static manifest configuration exactly mirroring Django's expected structures `ManifestStaticFilesStorage`.

Every file provided in your directory gets duplicate versions bearing a unique MD5 hash signature of the internal stream state appended inside its extension structure (e.g., `test.css` -> `test.296ab49302a4.css`).

It generates a directory-root lookup log file called `staticfiles.json` detailing out mapping paths, giving simple access for ASGI loaders that inject the resolved filename.

When using `--merge-manifest`, ServeStatic requires an existing `staticfiles.json` in `dest`. It merges the `paths` mapping and preserves custom top-level keys (for example, metadata keys you add manually).
