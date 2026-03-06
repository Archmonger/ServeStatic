from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from servestatic.compress import Compressor
from servestatic.manifest_hash import ManifestHashGenerator


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Process static files: copy, optionally hash, and compress.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Perform all operations (equivalent to --hash --manifest --compress).",
    )
    parser.add_argument(
        "--hash",
        action="store_true",
        help="Generate hashed versions of files.",
    )
    parser.add_argument(
        "--manifest",
        action="store_true",
        help="Generate a manifest file (staticfiles.json).",
    )
    parser.add_argument(
        "--merge-manifest",
        action="store_true",
        help="Merge the new manifest with an existing manifest in the dest directory. Fails if the existing manifest is not found.",
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="Generate compressed versions (gzip/brotli) of files.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Empty the destination directory before processing.",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="Don't produce log output.")
    parser.add_argument(
        "--copy-original",
        action="store_true",
        help="Copy the original unhashed files into the dest directory alongside the hashed versions (only applies with --hash).",
    )
    # Compression specific flags
    parser.add_argument(
        "--no-gzip",
        action="store_false",
        dest="use_gzip",
        help="Don't produce gzip '.gz' files (only applies with --compress).",
    )
    parser.add_argument(
        "--no-brotli",
        action="store_false",
        dest="use_brotli",
        help="Don't produce brotli '.br' files (only applies with --compress).",
    )
    # Exclusion
    parser.add_argument(
        "-e",
        "--exclude",
        action="append",
        help="Glob pattern(s) to exclude from processing (compression/hashing). These files are still copied.",
    )
    parser.add_argument("src", help="Source directory containing static files.")
    parser.add_argument("dest", help="Destination directory for processed files.")

    args = parser.parse_args(argv)

    if args.merge_manifest:
        args.manifest = True

    if args.all:
        args.hash = True
        args.manifest = True
        args.compress = True

    if not (args.hash or args.manifest or args.compress):
        parser.error("At least one of --hash, --manifest, --compress, or --all must be provided. Use --help for usage.")

    src_path = Path(args.src).resolve()
    dest_path = Path(args.dest).resolve()

    if not src_path.exists():
        parser.error(f"Source directory '{src_path}' does not exist.")

    existing_manifest_data = {}
    existing_manifest_paths = {}
    manifest_path_file = dest_path / "staticfiles.json"
    if args.merge_manifest:
        if not manifest_path_file.exists():
            parser.error(f"Existing manifest not found at '{manifest_path_file}' for merging.")
        try:
            with open(manifest_path_file, encoding="utf-8") as f:
                existing_manifest_data = json.load(f)
                if not isinstance(existing_manifest_data, dict):
                    parser.error("Existing manifest must be a JSON object.")
                existing_manifest_paths = existing_manifest_data.get("paths", {})
                if not isinstance(existing_manifest_paths, dict):
                    parser.error("Existing manifest 'paths' must be a JSON object.")
        except Exception as e:
            parser.error(f"Failed to read existing manifest: {e}")

    log = (lambda _: None) if args.quiet else print

    if args.clear and dest_path.exists():
        if src_path == dest_path:
            parser.error("Source and destination directories cannot be the same when using --clear.")
        log(f"Clearing destination directory {dest_path}...")
        for item in dest_path.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    # 1. Copy src to dest (ensure dest exists)
    log(f"Copying files from {src_path} to {dest_path}...")
    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)

    # Gather files in dest to process
    files_to_process = []
    excluded_files = []
    # Using os.walk for efficiency
    for dirpath, _dirs, files in os.walk(dest_path):
        for filename in files:
            p = Path(dirpath) / filename
            # Skip manifest itself if it exists (though usually created later)
            if p.name == "staticfiles.json":
                continue

            # Check exclusions
            rel_path = p.relative_to(dest_path).as_posix()
            if args.exclude and any(
                fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern) for pattern in args.exclude
            ):
                excluded_files.append(p)
                continue

            files_to_process.append(p)

    # 2. Hashing and Manifest
    manifest_paths = {}
    if args.hash or args.manifest:
        # First, add all files to the manifest (even excluded ones, to map them to themselves)
        for p in files_to_process + excluded_files:
            rel_path = p.relative_to(dest_path).as_posix()
            manifest_paths[rel_path] = rel_path

    if args.hash:
        log("Hashing files...")
        generator = ManifestHashGenerator(
            root=dest_path,
            keep_original=args.copy_original,
            quiet=args.quiet,
            log=log,
        )

        # Then overwrite the mapped path with the hashed path for processed files
        with ThreadPoolExecutor() as executor:
            futures = {executor.submit(generator.process, p): p for p in files_to_process}
            for future in as_completed(futures):
                try:
                    rel_original, rel_hashed = future.result()
                    manifest_paths[rel_original] = rel_hashed
                except Exception as e:
                    log(f"Error hashing {futures[future]}: {e}")

    # Write manifest
    if args.manifest:
        log("Writing manifest...")
        manifest_data = {"paths": manifest_paths, "version": "1.0"}
        if args.merge_manifest:
            manifest_data = {
                **existing_manifest_data,
                "paths": {**existing_manifest_paths, **manifest_paths},
            }
            manifest_data.setdefault("version", "1.0")

        manifest_path = dest_path / "staticfiles.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)
        log(f"Manifest written to {manifest_path.name}")

        # Re-scanning dest seems safest to catch all generated artifacts before compression.

    # 3. Compression
    if args.compress:
        log("Compressing files...")
        # Re-scan in case hashing added files or removed them.
        files_to_compress = []
        for dirpath, _dirs, files in os.walk(dest_path):
            for filename in files:
                p = Path(dirpath) / filename
                if p.name == "staticfiles.json":
                    continue

                # Check exclusions - apply logic against the current file path
                rel_path = p.relative_to(dest_path).as_posix()
                if args.exclude and any(
                    fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern) for pattern in args.exclude
                ):
                    continue
                files_to_compress.append(p)

        compressor = Compressor(
            use_gzip=args.use_gzip,
            use_brotli=args.use_brotli,
            quiet=args.quiet,
            log=log,
            # We explicitly rely on the compressor class's default extension exclusion filter
        )

        with ThreadPoolExecutor() as executor:
            futures = []

            # Check if it's worth compressing based on extension (images, zip, etc)
            futures.extend(
                executor.submit(compressor.compress, str(p))
                for p in files_to_compress
                if compressor.should_compress(p.name)
            )
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    log(f"Error compressing: {e}")

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
