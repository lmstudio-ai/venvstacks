#!/usr/bin/env python3
"""Helper script to remove lock platform tags when updating to venvstacks 0.8.0."""

import fnmatch
import os

from argparse import ArgumentParser
from pathlib import Path
from typing import Sequence

# Releases up to and including 0.7.0 emitted platform specific requirements files for layer locks.
# Release 0.8.0 migrates to universal layer locks (retaining environment markers as needed).
# With this change, the emitted lock files no longer include the platform tag in their name.
# For clearer diffs between the locked requirements with and without environment markers,
# this script supports removing the platform tags from all files in a tree.

try:
    # Import the CLI module first to avoid the API stability warning
    import venvstacks.cli  # noqa
    from venvstacks.stacks import TargetPlatforms
except ImportError as exc:
    exc.add_note("Try 'pdm run remove-lock-platform-tags' if direct execution fails")
    raise

_KNOWN_PLATFORM_TAGS = sorted(named_tag.value for named_tag in TargetPlatforms)


# Omitting the reference platform entirely is permitted to allow completely platform
# specific stack specifications to be migrated without having to specify the platform
def remove_platform_tags(
    dir_to_scan: os.PathLike[str], reference_platform: str | None
) -> None:
    """Remove platform tag suffixes from files in the given directory tree.

    When multiple files that differ only by their platform tag exist,
    only the file with the reference platform tag is renamed, other files are just removed.
    """
    if (
        reference_platform is not None
        and reference_platform not in _KNOWN_PLATFORM_TAGS
    ):
        raise ValueError(f"{reference_platform} must be one of {_KNOWN_PLATFORM_TAGS}")
    # Python 3.11 compatibility: use os.walk instead of Path.walk
    for this_dir, _, files in os.walk(dir_to_scan):
        dir_path = Path(this_dir)
        print(f"Checking {dir_path}...")
        files_to_rename: dict[str, list[str]] = {}
        files_to_remove: list[str] = []
        for tag in _KNOWN_PLATFORM_TAGS:
            fname_tag_suffix = f"-{tag}"
            pattern = f"*{fname_tag_suffix}.*"
            for fname in fnmatch.filter(files, pattern):
                untagged_fname = fname.replace(fname_tag_suffix, "")
                if reference_platform is None or tag == reference_platform:
                    tagged_fnames = files_to_rename.setdefault(untagged_fname, [])
                else:
                    tagged_fnames = files_to_remove
                tagged_fnames.append(fname)
        for untagged_fname, tagged_fnames in files_to_rename.items():
            if len(tagged_fnames) > 1:
                print(f"  Skipping ambiguous rename to {untagged_fname}")
                continue
            tagged_fname = tagged_fnames[0]
            print(f"  Renaming {tagged_fname} -> {untagged_fname}")
            tagged_path = dir_path / tagged_fname
            if tagged_path.suffix == ".txt":
                # Ensure requirements files use POSIX line endings
                file_text = tagged_path.read_text("utf-8")
                tagged_path.write_text(file_text, "utf-8", newline="\n")
            tagged_path.rename(dir_path / untagged_fname)
        for tagged_fname in files_to_remove:
            print(f"  Removing {tagged_fname}")
            tagged_path = dir_path / tagged_fname
            tagged_path.unlink()


def _make_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("dir_to_scan")
    parser.add_argument("-p", "--reference-platform", choices=_KNOWN_PLATFORM_TAGS)
    return parser


def _main(args: Sequence[str] | None = None) -> None:
    parser = _make_parser()
    parsed_args = parser.parse_args(args)
    remove_platform_tags(parsed_args.dir_to_scan, parsed_args.reference_platform)


if __name__ == "__main__":
    _main()
