"""Utilities for filtering source tree content."""

import os.path

from abc import abstractmethod
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol, Sequence, Type

from dulwich.repo import Repo as GitRepo
from dulwich.porcelain import check_ignore as check_gitignore


from ._util import WalkIterator, walk_path


class SourceTreeContentFilter(Protocol):
    # Making this a protocol rather than an ABC allows for both stateless
    # class based implementations and stateful instance based implementations

    @classmethod
    @abstractmethod
    def get_source_path(cls, included_path: Path) -> Path | None:
        """Containing path to use to instantiate this filter (None if not supported)."""
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def from_path(cls, source_path: Path) -> "SourceTreeContentFilter":
        """Returns a source tree content filter for the given source path."""
        raise NotImplementedError

    @abstractmethod
    def walk(self, top: Path) -> WalkIterator:
        """Path.walk replacement with source tree content filtering."""
        raise NotImplementedError

    @abstractmethod
    def ignore(self, src_dir: str, entries: Sequence[str]) -> Sequence[str]:
        """shutil.copytree 'ignore' callback with source tree content filtering."""
        raise NotImplementedError


class SourceTreeIgnorePycache(SourceTreeContentFilter):
    _IGNORED_NAMES = {
        "__pycache__",
    }

    @classmethod
    def get_source_path(cls, included_path: Path) -> Path | None:
        """Default content filter can be used with any source tree."""
        return included_path

    @classmethod
    def from_path(cls, source_path: Path) -> "SourceTreeContentFilter":
        """Default content filter is stateless."""
        return cls

    @classmethod
    def _included_names(cls, names: Iterable[str]) -> Iterator[str]:
        for name in names:
            if name not in cls._IGNORED_NAMES:
                yield name

    @classmethod
    def _ignored_names(cls, names: Iterable[str]) -> Iterator[str]:
        for name in names:
            if name in cls._IGNORED_NAMES:
                yield name

    @classmethod
    def walk(cls, top: Path) -> WalkIterator:
        """Walk source tree directory, ignoring __pycache__ folders."""
        for dir_path, subdirs, files in walk_path(top):
            if dir_path.name in cls._IGNORED_NAMES:
                continue
            # Modify in place so subdirectory walk is updated
            subdirs[:] = cls._included_names(subdirs)
            files[:] = cls._included_names(files)
            yield (dir_path, subdirs, files)

    @classmethod
    def ignore(cls, src_dir: str, entries: Sequence[str]) -> Sequence[str]:
        """shutil.copytree 'ignore' callback that ignores __pycache__ entries."""
        src_path = Path(src_dir)
        if any(part in cls._IGNORED_NAMES for part in src_path.parts):
            return entries
        # Not excluding entire directory, so also check individual entries
        return [*cls._ignored_names(entries)]


class SourceTreeGit(SourceTreeContentFilter):
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self._repo = GitRepo(repo_path.as_posix())

    @classmethod
    def get_source_path(cls, included_path: Path) -> Path | None:
        """Returning containing folder with .git metadata (None if not found)."""
        for source_path in (included_path, *included_path.parents):
            if (source_path / ".git").is_dir():
                return source_path
        return None

    @classmethod
    def from_path(cls, source_path: Path) -> "SourceTreeContentFilter":
        """Default content filter is stateless."""
        return cls(source_path)

    def _check_gitignore(self, dir_path: Path, entries: Sequence[str]) -> Iterator[str]:
        # Specify the full union to avoid a mutable arg typing complaint on check_gitignore
        # https://github.com/jelmer/dulwich/issues/1894
        paths_to_check: list[str | bytes | os.PathLike[Any]] = []
        for entry in entries:
            if entry.startswith(".git"):
                # Ignore any git metadata files
                yield entry
                continue
            paths_to_check.append((dir_path / entry).as_posix())
        # Forward compatibility with dulwich 0.22.9+
        # https://github.com/jelmer/dulwich/pull/1575
        quote_arg: dict[str, bool] = {}
        if "quote_path" in check_gitignore.__code__.co_varnames:
            quote_arg["quote_path"] = False
        ignored_paths = check_gitignore(self.repo_path, paths_to_check, **quote_arg)
        for ignored_path in ignored_paths:
            name = os.path.basename(ignored_path)
            yield name

    def walk(self, top: Path) -> WalkIterator:
        """Walk source tree directory, respecting .gitignore filters."""
        repo_path = self.repo_path
        src_path = Path.cwd() / top
        if not src_path.is_relative_to(repo_path):
            # Paths outside the tree are automatically ignored
            return
        # Skip entirely if the directory is excluded
        if [*self._check_gitignore(src_path.parent, [src_path.name])]:
            return
        # Check all directory entries against .gitignore
        for dir_path, subdirs, files in walk_path(src_path):
            ignored_subdirs = set(self._check_gitignore(dir_path, subdirs))
            ignored_files = set(self._check_gitignore(dir_path, files))
            # Modify in place so subdirectory walk is updated
            subdirs[:] = set(subdirs) - ignored_subdirs
            files[:] = set(files) - ignored_files
            yield (dir_path, subdirs, files)

    def ignore(self, src_dir: str, entries: Sequence[str]) -> Sequence[str]:
        """shutil.copytree 'ignore' callback that respects .gitignore filters."""
        repo_path = self.repo_path
        src_path = Path.cwd() / src_dir
        if not src_path.is_relative_to(repo_path):
            # Paths outside the tree are automatically ignored
            return entries
        # Paths inside the tree are ignored if .gitignore excludes them
        return [*self._check_gitignore(src_path, entries)]


_DEFINED_FILTERS: list[Type[SourceTreeContentFilter]] = [
    SourceTreeGit,
    SourceTreeIgnorePycache,
]


def get_default_source_filter(included_path: Path) -> SourceTreeContentFilter:
    for source_filter_cls in _DEFINED_FILTERS:
        source_path = source_filter_cls.get_source_path(included_path)
        if source_path is not None:
            return source_filter_cls.from_path(source_path)
    raise RuntimeError("Default source filter was not selected")
