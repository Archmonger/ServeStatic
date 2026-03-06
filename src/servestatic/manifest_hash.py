from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


def generate_hash(content: bytes) -> str:
    """
    Return a hash of the content, mimicking Django's ManifestStaticFilesStorage hashes.
    """
    hasher = hashlib.md5(usedforsecurity=False)
    hasher.update(content)
    return hasher.hexdigest()[:12]


def hash_path(path: str | Path) -> str:
    """
    Return a hash of the file at the given path, mimicking Django's ManifestStaticFilesStorage hashes.
    """
    hasher = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]


def get_hashed_name(path: str | Path, content: bytes | None = None) -> str:
    """
    Return the hashed name of the file at the given path, mimicking Django's ManifestStaticFilesStorage hashes.
    If content is provided, use that instead of reading the file.
    """
    file_hash = generate_hash(content) if content is not None else hash_path(path)
    path_str = str(path)
    root, ext = os.path.splitext(path_str)
    return f"{root}.{file_hash}{ext}"


class ManifestHashGenerator:
    def __init__(self, root: str | Path, keep_original=True, log=print, quiet=False):
        self.root = Path(root).resolve()
        self.keep_original = keep_original
        self.log = (lambda _: None) if quiet else log
        self.manifest_path = self.root / "staticfiles.json"

    def process(self, path: Path) -> tuple[str, str]:
        """
        Process a single file: hash it, copy to hashed name.
        Returns tuple of (relative_original_path, relative_hashed_path).
        """
        rel_path = path.relative_to(self.root).as_posix()
        hashed_name_full = get_hashed_name(path)
        hashed_path = Path(hashed_name_full)
        rel_hashed_path = hashed_path.relative_to(self.root).as_posix()

        if path != hashed_path:
            shutil.copy2(path, hashed_path)
            self.log(f"Generated {hashed_path.name} from {path.name}")
            if not self.keep_original:
                path.unlink()

        return rel_path, rel_hashed_path
