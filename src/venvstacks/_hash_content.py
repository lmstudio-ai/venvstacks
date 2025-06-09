"""Utilities for content and metadata hashing."""

import hashlib

from pathlib import Path
from typing import Iterable

from ._util import WalkCallable, walk_path


def hash_strings(
    items: Iterable[str], algorithm: str = "sha256", *, omit_prefix: bool = False
) -> str:
    incremental_hash = hashlib.new(algorithm)
    for item in items:
        incremental_hash.update(item.encode())
    strings_hash = incremental_hash.hexdigest()
    if omit_prefix:
        return strings_hash
    return f"{algorithm}:{strings_hash}"


def hash_file_contents(
    path: Path, algorithm: str = "sha256", *, omit_prefix: bool = False
) -> str:
    if not path.exists():
        return ""
    with path.open("rb", buffering=0) as f:
        file_hash = hashlib.file_digest(f, algorithm).hexdigest()
    if omit_prefix:
        return file_hash
    return f"{algorithm}:{file_hash}"


def hash_file_name_and_contents(
    path: Path, algorithm: str = "sha256", *, omit_prefix: bool = False
) -> str:
    if not path.exists():
        return ""
    incremental_hash = hashlib.new(algorithm)
    incremental_hash.update(path.name.encode())
    file_hash = hash_file_contents(path, algorithm)
    incremental_hash.update(file_hash.encode())
    file_and_name_hash = incremental_hash.hexdigest()
    if omit_prefix:
        return file_and_name_hash
    return f"{algorithm}:{file_and_name_hash}"


def hash_directory(
    path: Path,
    algorithm: str = "sha256",
    *,
    omit_prefix: bool = False,
    walk_iter: WalkCallable | None = None,
) -> str:
    if walk_iter is None:
        walk_iter = walk_path
    incremental_hash = hashlib.new(algorithm)
    # Python 3.11 compatibility: use os.walk instead of Path.walk
    for this_dir, subdirs, files in walk_iter(path):
        if not files:
            continue
        dir_path = Path(this_dir)
        incremental_hash.update(dir_path.name.encode())
        # Ensure directory tree iteration order is deterministic
        subdirs.sort()
        for file in sorted(files):
            file_path = dir_path / file
            incremental_hash.update(file_path.name.encode())
            file_hash = hash_file_contents(file_path, algorithm)
            incremental_hash.update(file_hash.encode())
    dir_hash = incremental_hash.hexdigest()
    if omit_prefix:
        return dir_hash
    return f"{algorithm}/{dir_hash}"


def hash_module(path: Path, walk_iter: WalkCallable | None = None) -> str:
    # Always use the default algorithm + algorithm prefix for module hashes
    if path.is_file():
        module_hash = hash_file_name_and_contents(path)
    else:
        module_hash = hash_directory(path, walk_iter=walk_iter)
    return module_hash
