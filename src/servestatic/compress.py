from __future__ import annotations

import argparse
import gzip
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO

try:
    import brotli
except ImportError:  # pragma: no cover
    brotli = None

try:
    from compression import zstd
except ImportError:  # pragma: no cover
    zstd = None


class Compressor:
    # Extensions that it's not worth trying to compress
    SKIP_COMPRESS_EXTENSIONS = (
        # Images
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        # Compressed files
        "zip",
        "gz",
        "tgz",
        "bz2",
        "tbz",
        "xz",
        "br",
        "zstd",
        # Flash
        "swf",
        "flv",
        # Fonts
        "woff",
        "woff2",
        # Video
        "3gp",
        "3gpp",
        "asf",
        "avi",
        "m4v",
        "mov",
        "mp4",
        "mpeg",
        "mpg",
        "webm",
        "wmv",
    )

    def __init__(
        self,
        extensions=None,
        use_gzip=True,
        use_brotli=True,
        use_zstd=True,
        zstd_dict=None,
        zstd_dict_is_raw=False,
        zstd_level=None,
        log=print,
        quiet=False,
    ):
        if extensions is None:
            extensions = self.SKIP_COMPRESS_EXTENSIONS
        self.extension_re = self.get_extension_re(extensions)
        self.use_gzip = use_gzip
        self.use_brotli = use_brotli and (brotli is not None)
        if zstd_dict is not None and zstd is None:
            msg = "Zstandard dictionary support requires Python 3.14+ with compression.zstd available"
            raise RuntimeError(msg)
        self.use_zstd = use_zstd and (zstd is not None)
        self.zstd_level = zstd_level
        self.zstd_dict = self.load_zstd_dictionary(zstd_dict, is_raw=zstd_dict_is_raw)
        self.log = (lambda _: None) if quiet else log

    @staticmethod
    def load_zstd_dictionary(zstd_dict, *, is_raw=False):
        if zstd_dict is None:
            return None
        if zstd is None:
            msg = "Zstandard is not available"
            raise RuntimeError(msg)
        if isinstance(zstd_dict, (str, os.PathLike)):
            with open(zstd_dict, "rb") as f:
                zstd_dict = f.read()
        if isinstance(zstd_dict, (bytes, bytearray, memoryview)):
            return zstd.ZstdDict(bytes(zstd_dict), is_raw=is_raw)
        # Allow callers to provide a pre-built zstd dictionary object.
        return zstd_dict

    @staticmethod
    def get_extension_re(extensions):
        if not extensions:
            return re.compile(r"^$")
        return re.compile(rf"\.({'|'.join(map(re.escape, extensions))})$", re.IGNORECASE)

    def should_compress(self, filename):
        return not self.extension_re.search(filename)

    def compress(self, path):
        filenames = []
        with open(path, "rb") as f:
            stat_result = os.fstat(f.fileno())
            data = f.read()
        size = len(data)
        if self.use_zstd:
            compressed = self.compress_zstd(data, level=self.zstd_level, zstd_dict=self.zstd_dict)
            if self.is_compressed_effectively("Zstandard", path, size, compressed):
                filenames.append(self.write_data(path, compressed, ".zstd", stat_result))
        if self.use_brotli:
            compressed = self.compress_brotli(data)
            if self.is_compressed_effectively("Brotli", path, size, compressed):
                filenames.append(self.write_data(path, compressed, ".br", stat_result))
        if self.use_gzip:
            compressed = self.compress_gzip(data)
            if self.is_compressed_effectively("Gzip", path, size, compressed):
                filenames.append(self.write_data(path, compressed, ".gz", stat_result))
        return filenames

    @staticmethod
    def compress_gzip(data):
        output = BytesIO()
        # Explicitly set mtime to 0 so gzip content is fully determined
        # by file content (0 = "no timestamp" according to gzip spec)
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=0) as gz_file:
            gz_file.write(data)
        return output.getvalue()

    @staticmethod
    def compress_brotli(data):
        if brotli is None:
            msg = "Brotli is not installed"
            raise RuntimeError(msg)
        return brotli.compress(data)

    @staticmethod
    def compress_zstd(data, level=None, zstd_dict=None):
        if zstd is None:
            msg = "Zstandard is not available"
            raise RuntimeError(msg)
        kwargs = {}
        if level is not None:
            kwargs["level"] = level
        if zstd_dict is not None:
            kwargs["zstd_dict"] = zstd_dict
        return zstd.compress(data, **kwargs)

    def is_compressed_effectively(self, encoding_name, path, orig_size, data):
        compressed_size = len(data)
        if orig_size == 0:
            is_effective = False
        else:
            ratio = compressed_size / orig_size
            is_effective = ratio <= 0.95
        if is_effective:
            self.log(f"{encoding_name} compressed {path} ({orig_size // 1024}K -> {compressed_size // 1024}K)")
        else:
            self.log(f"Skipping {path} ({encoding_name} compression not effective)")
        return is_effective

    @staticmethod
    def write_data(path, data, suffix, stat_result):
        filename = path + suffix
        with open(filename, "wb") as f:
            f.write(data)
        os.utime(filename, (stat_result.st_atime, stat_result.st_mtime))
        return filename


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Search for all files inside <root> *not* matching "
        "<extensions> and produce compressed versions with "
        "'.gz', '.br', and '.zstd' suffixes (as long as this results in a "
        "smaller file)"
    )
    parser.add_argument("-q", "--quiet", help="Don't produce log output", action="store_true")
    parser.add_argument(
        "--no-gzip",
        help="Don't produce gzip '.gz' files",
        action="store_false",
        dest="use_gzip",
    )
    parser.add_argument(
        "--no-brotli",
        help="Don't produce brotli '.br' files",
        action="store_false",
        dest="use_brotli",
    )
    parser.add_argument(
        "--no-zstd",
        help="Don't produce zstd '.zstd' files",
        action="store_false",
        dest="use_zstd",
    )
    parser.add_argument(
        "--zstd-dict",
        help="Path to a zstd dictionary file.",
    )
    parser.add_argument(
        "--zstd-dict-raw",
        help="Treat the zstd dictionary as raw content.",
        action="store_true",
    )
    parser.add_argument(
        "--zstd-level",
        help="Compression level for zstd output.",
        type=int,
    )
    parser.add_argument("root", help="Path root from which to search for files")
    default_exclude = ", ".join(Compressor.SKIP_COMPRESS_EXTENSIONS)
    parser.add_argument(
        "extensions",
        nargs="*",
        help=f"File extensions to exclude from compression (default: {default_exclude})",
        default=Compressor.SKIP_COMPRESS_EXTENSIONS,
    )
    args = parser.parse_args(argv)

    compressor = Compressor(
        extensions=args.extensions,
        use_gzip=args.use_gzip,
        use_brotli=args.use_brotli,
        use_zstd=args.use_zstd,
        zstd_dict=args.zstd_dict,
        zstd_dict_is_raw=args.zstd_dict_raw,
        zstd_level=args.zstd_level,
        quiet=args.quiet,
    )

    futures = []
    with ThreadPoolExecutor() as executor:
        for dirpath, _dirs, files in os.walk(args.root):
            futures.extend(
                executor.submit(compressor.compress, os.path.join(dirpath, filename))
                for filename in files
                if compressor.should_compress(filename)
            )
        # Trigger any errors
        for future in as_completed(futures):
            future.result()

    return 0


if __name__ == "__main__":  # pragma: no cover
    from warnings import warn

    warn(
        "Calling this file directly is deprecated. Use the 'servestatic --compress' command instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    raise SystemExit(main())
