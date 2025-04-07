#!/usr/bin/env python3
"""Proof of concept for finding non-Python-module shared modules."""

# Concept demonstrator for the cross-environment shared library loading support
# described in https://github.com/lmstudio-ai/venvstacks/issues/38

import os
import sys

from pathlib import Path
from importlib.machinery import EXTENSION_SUFFIXES


def _ext_to_suffixes(extension: str) -> tuple["str", ...]:
    suffix_parts = extension.split(".")
    return tuple(f".{part}" for part in suffix_parts if part)


_PYLIB_SUFFIX = ".so"  # .dylib is never importable as a Python module, even on macOS
_LIB_SUFFIXES = frozenset((_PYLIB_SUFFIX, ".dylib"))

# Skip libraries with extensions that are explicitly for importable Python extension modules
_IGNORED_SUFFIXES = frozenset(
    _ext_to_suffixes(ext) for ext in EXTENSION_SUFFIXES if ext != _PYLIB_SUFFIX
)


def main() -> None:
    """Find non-extension-module shared libraries in specified folder."""
    _dir_to_search = sys.argv[1]
    _paths_to_link = []
    for this_dir, _, files in os.walk(_dir_to_search):
        dir_path = Path(this_dir)
        for fname in files:
            file_path = dir_path / fname
            if file_path.suffix not in _LIB_SUFFIXES:
                continue
            if tuple(file_path.suffixes) in _IGNORED_SUFFIXES:
                continue
            _paths_to_link.append(file_path)

    for file_path in _paths_to_link:
        print(file_path)


if __name__ == "__main__":
    main()
