"""Utilities for filtering source tree content."""

import os.path

from abc import abstractmethod
from pathlib import Path
from typing import Protocol, Sequence

from ._util import WalkIterator, walk_path


class SourceTreeContentFilter(Protocol):
    # Making this a protocol rather than an ABC allows for both stateless
    # class based implementations and stateful instance based implementations

    @abstractmethod
    def walk(self, top: Path) -> WalkIterator:
        """Path.walk replacement with source tree content filtering."""
        raise NotImplementedError

    @abstractmethod
    def ignore(self, src_dir: str, entries: Sequence[str]) -> Sequence[str]:
        """shutil.copytree 'ignore' callback with source tree content filtering."""
        raise NotImplementedError


class SourceTreeIgnorePycache(SourceTreeContentFilter):
    _IGNORED_DIRS = {
        "__pycache__",
    }

    @classmethod
    def walk(cls, top: Path) -> WalkIterator:
        """Walk source tree directory, ignoring __pycache__ folders."""
        for dir_path, subdirs, files in walk_path(top):
            if dir_path.name in cls._IGNORED_DIRS:
                continue
            yield dir_path, subdirs, files

    @classmethod
    def ignore(cls, src_dir: str, entries: Sequence[str]) -> Sequence[str]:
        """shutil.copytree 'ignore' callback that ignores __pycache__ entries."""
        if os.path.basename(src_dir) in cls._IGNORED_DIRS:
            return entries
        return ()
