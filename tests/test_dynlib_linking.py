"""Test cases for dynamic library discovery and symlinking."""

import sys

import pytest

from pathlib import Path
from importlib.machinery import EXTENSION_SUFFIXES
from typing import cast

from venvstacks._util import (
    find_shared_libraries,
    map_symlink_targets,
)


@pytest.mark.skipif(
    sys.platform == "win32", reason="No scan for dynamic libraries on Windows"
)
def test_find_shared_libraries(temp_dir_path: Path) -> None:
    # Scanning for shared libraries is entirely name based
    base_names = (
        "libpng",
        "libcodec",
        "libother",
    )
    linked_extensions = (".so", ".dylib")
    all_extensions = {*EXTENSION_SUFFIXES, *linked_extensions}
    expected_names = [name + ext for name in base_names for ext in linked_extensions]
    all_names = [name + ext for name in base_names for ext in all_extensions]
    subdir_paths = (
        temp_dir_path / "project1",
        temp_dir_path / "project2/libs",
        temp_dir_path / "project3/_files/libs",
    )
    expected_paths = {p / name for p in subdir_paths for name in expected_names}
    dynlib_paths = [p / name for p in subdir_paths for name in all_names]
    for p in dynlib_paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()

    py_version_info = cast(tuple[str, str], tuple(map(str, sys.version_info[:2])))
    paths_without_exclusions = {*find_shared_libraries(py_version_info, temp_dir_path)}
    assert paths_without_exclusions == expected_paths

    exclusions = [
        "project1/**/libpng.*",
        "project2/**/libcodec.*",
        "project3/**/libother.*",
    ]
    paths_with_exclusions = {
        *find_shared_libraries(py_version_info, temp_dir_path, excluded=exclusions)
    }

    def _exclude_path(p: Path) -> bool:
        return (
            (p.stem == "libpng" and "project1" in p.parts)
            or (p.stem == "libcodec" and "project2" in p.parts)
            or (p.stem == "libother" and "project3" in p.parts)
        )

    expected_paths_with_exclusions = {p for p in expected_paths if not _exclude_path(p)}
    assert paths_with_exclusions == expected_paths_with_exclusions


def test_map_symlink_targets() -> None:
    # Symlink target mapping doesn't check if the paths exist
    # (that's handled when creating the list of inputs)
    symlink_dir_path = Path()
    # No input -> no output
    assert map_symlink_targets(symlink_dir_path, []) == ({}, {})

    # No ambiguity
    targets_dir_path = symlink_dir_path / "targets"
    target_paths = [targets_dir_path / f"target{n}" for n in range(5)]
    symlink_paths = [symlink_dir_path / p.name for p in target_paths]
    expected_mapping = dict(zip(symlink_paths, target_paths))
    assert map_symlink_targets(symlink_dir_path, target_paths) == (expected_mapping, {})

    # Ambiguity
    conflicting_path = targets_dir_path / "conflict" / target_paths[0].name
    ambiguous_paths = [*target_paths, *target_paths, conflicting_path]
    expected_valid_mapping = dict(zip(symlink_paths[1:], target_paths[1:]))
    expected_ambiguity = {symlink_paths[0]: {target_paths[0], conflicting_path}}
    assert map_symlink_targets(symlink_dir_path, ambiguous_paths) == (
        expected_valid_mapping,
        expected_ambiguity,
    )
