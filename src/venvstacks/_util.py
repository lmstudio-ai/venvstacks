"""Common utilities for stack creation and venv publication."""

import os
import os.path
import re
import subprocess
import sys
import tarfile

from contextlib import contextmanager
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
from typing import Any, Generator, Iterable, Literal, Mapping, Sequence, overload

WINDOWS_BUILD = hasattr(os, "add_dll_directory")

StrPath = str | os.PathLike[str]

# Set to True (either in the source or at runtime) to dump
# the full environment being passed to subprocesses
_DEBUG_SUBPROCESS_ENVS = False


def as_normalized_path(path: StrPath, /) -> Path:
    """Normalize given path and make it absolute, *without* resolving symlinks.

    Expands user directory references, but *not* environment variable references.
    """
    # Ensure user directory references are handled as absolute paths
    expanded_path = os.path.expanduser(path)
    return Path(os.path.abspath(expanded_path))


@contextmanager
def default_tarfile_filter(filter: str) -> Generator[None, None, None]:
    """Temporarily set a global tarfile filter (useful for 3rd party API warnings)."""
    if sys.version_info < (3, 12):
        # Python 3.11 or earlier, can't set a default extraction filter
        yield
        return
    # Python 3.12 or later, set a scoped default tarfile filter
    if not filter.endswith("_filter"):
        # Allow users to omit the `_filter` suffix
        filter = f"{filter}_filter"
    default_filter = getattr(tarfile, filter)
    old_filter = tarfile.TarFile.extraction_filter
    try:
        tarfile.TarFile.extraction_filter = staticmethod(default_filter)
        yield
    finally:
        tarfile.TarFile.extraction_filter = old_filter


##############################################################################
# Running Python in built/deployed/exported layer environments
##############################################################################


def get_env_python(env_path: Path) -> Path:
    """Return the main Python binary in the given Python environment."""
    if WINDOWS_BUILD:
        env_python = env_path / "Scripts" / "python.exe"
        if not env_python.exists():
            # python-build-standalone puts the Windows Python CLI
            # at the base of the runtime folder
            env_python = env_path / "python.exe"
    else:
        env_python = env_path / "bin" / "python"
    if env_python.exists():
        return env_python
    raise FileNotFoundError(f"No Python runtime found in {env_path}")


_SUBPROCESS_PYTHON_CONFIG = {
    # Ensure any Python invocations don't pick up unwanted sys.path entries
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "PYTHONPATH": "",
    "PYTHONSTARTUP": "",
    # Ensure UTF-8 mode is used
    "PYTHONUTF8": "1",
    "PYTHONLEGACYWINDOWSFSENCODING": "",
    "PYTHONLEGACYWINDOWSSTDIO": "",
    # There are other dev settings that may cause problems, but are also unlikely to be set
    # See https://docs.python.org/3/using/cmdline.html#environment-variables
    # These settings were originally added to avoid the `pip-sync` issues noted
    # in https://github.com/jazzband/pip-tools/issues/2117, and then retained
    # even after the `pip-sync` dependency was removed
}


@overload
def run_python_command_unchecked(
    command: list[str],
    *,
    env: Mapping[str, str] | None = ...,
    text: Literal[True] | None = ...,
    **kwds: Any,
) -> subprocess.CompletedProcess[str]: ...
@overload
def run_python_command_unchecked(
    command: list[str],
    *,
    env: Mapping[str, str] | None = ...,
    text: Literal[False] = ...,
    **kwds: Any,
) -> subprocess.CompletedProcess[bytes]: ...
def run_python_command_unchecked(
    command: list[str],
    *,
    env: Mapping[str, str] | None = None,
    text: bool | None = True,
    **kwds: Any,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    # Ensure required env vars are passed down on Windows,
    # and run Python in isolated mode with UTF-8 as the text encoding
    run_env = os.environ.copy()
    # Let the target Python runtime infer whether it's part of a venv or not
    run_env.pop("VIRTUAL_ENV", None)
    if env is not None:
        run_env.update(env)
    run_env.update(_SUBPROCESS_PYTHON_CONFIG)
    if _DEBUG_SUBPROCESS_ENVS:
        import json

        print(json.dumps(run_env, indent=2, sort_keys=True))
    # Default to running in text mode,
    # but allow it to be explicitly switched off
    text = text if text else False
    encoding = "utf-8" if text else None
    result: subprocess.CompletedProcess[str] = subprocess.run(
        command, env=run_env, text=text, encoding=encoding, **kwds
    )
    return result


def run_python_command(
    # Narrow list type spec here due to the way `subprocess.run` params are typed
    command: list[str],
    **kwds: Any,
) -> subprocess.CompletedProcess[str]:
    result = run_python_command_unchecked(command, text=True, **kwds)
    result.check_returncode()
    return result


def capture_python_output(command: list[str]) -> subprocess.CompletedProcess[str]:
    return run_python_command(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


##############################################################################
#  Finding shared libraries to link to a common location in each environment
##############################################################################


# Python 3.11/3.12 compatibility: copy implementation of fnmatch._translate
# This function is thus under the Python Software Foundation License
# rather than the license used for the rest of the package
def _translate_fnmatch(pat: str, STAR: str, QUESTION_MARK: str) -> list[str]:
    res: list[str] = []
    add = res.append
    i, n = 0, len(pat)
    while i < n:
        c = pat[i]
        i = i + 1
        if c == "*":
            # compress consecutive `*` into one
            if (not res) or res[-1] is not STAR:
                add(STAR)
        elif c == "?":
            add(QUESTION_MARK)
        elif c == "[":
            j = i
            if j < n and pat[j] == "!":
                j = j + 1
            if j < n and pat[j] == "]":
                j = j + 1
            while j < n and pat[j] != "]":
                j = j + 1
            if j >= n:
                add("\\[")
            else:
                stuff = pat[i:j]
                if "-" not in stuff:
                    stuff = stuff.replace("\\", r"\\")
                else:
                    chunks = []
                    k = i + 2 if pat[i] == "!" else i + 1
                    while True:
                        k = pat.find("-", k, j)
                        if k < 0:
                            break
                        chunks.append(pat[i:k])
                        i = k + 1
                        k = k + 3
                    chunk = pat[i:j]
                    if chunk:
                        chunks.append(chunk)
                    else:
                        chunks[-1] += "-"
                    # Remove empty ranges -- invalid in RE.
                    for k in range(len(chunks) - 1, 0, -1):
                        if chunks[k - 1][-1] > chunks[k][0]:
                            chunks[k - 1] = chunks[k - 1][:-1] + chunks[k][1:]
                            del chunks[k]
                    # Escape backslashes and hyphens for set difference (--).
                    # Hyphens that create ranges shouldn't be escaped.
                    stuff = "-".join(
                        s.replace("\\", r"\\").replace("-", r"\-") for s in chunks
                    )
                # Escape set operations (&&, ~~ and ||).
                stuff = re.sub(r"([&~|])", r"\\\1", stuff)
                i = j + 1
                if not stuff:
                    # Empty range: never match.
                    add("(?!)")
                elif stuff == "!":
                    # Negated empty range: match any character.
                    add(".")
                else:
                    if stuff[0] == "!":
                        stuff = "^" + stuff[1:]
                    elif stuff[0] in ("^", "["):
                        stuff = "\\" + stuff
                    add(f"[{stuff}]")
        else:
            add(re.escape(c))
    assert i == n
    return res


# Python 3.11/3.12 compatibility: copy implementation of glob.translate
# This function is thus under the Python Software Foundation License
# rather than the license used for the rest of the package
def _translate_glob(
    pat: str,
    *,
    recursive: bool = False,
    include_hidden: bool = False,
    seps: Sequence[str] | None = None,
) -> str:
    """Translate a pathname with shell wildcards to a regular expression.

    If `recursive` is true, the pattern segment '**' will match any number of
    path segments.

    If `include_hidden` is true, wildcards can match path segments beginning
    with a dot ('.').

    If a sequence of separator characters is given to `seps`, they will be
    used to split the pattern into segments and match path separators. If not
    given, os.path.sep and os.path.altsep (where available) are used.
    """
    if not seps:
        if os.path.altsep:
            seps = (os.path.sep, os.path.altsep)
        else:
            seps = os.path.sep
    escaped_seps = "".join(map(re.escape, seps))
    any_sep = f"[{escaped_seps}]" if len(seps) > 1 else escaped_seps
    not_sep = f"[^{escaped_seps}]"
    if include_hidden:
        one_last_segment = f"{not_sep}+"
        one_segment = f"{one_last_segment}{any_sep}"
        any_segments = f"(?:.+{any_sep})?"
        any_last_segments = ".*"
    else:
        one_last_segment = f"[^{escaped_seps}.]{not_sep}*"
        one_segment = f"{one_last_segment}{any_sep}"
        any_segments = f"(?:{one_segment})*"
        any_last_segments = f"{any_segments}(?:{one_last_segment})?"

    results = []
    parts = re.split(any_sep, pat)
    last_part_idx = len(parts) - 1
    for idx, part in enumerate(parts):
        if part == "*":
            results.append(one_segment if idx < last_part_idx else one_last_segment)
        elif recursive and part == "**":
            if idx < last_part_idx:
                if parts[idx + 1] != "**":
                    results.append(any_segments)
            else:
                results.append(any_last_segments)
        else:
            if part:
                if not include_hidden and part[0] in "*?":
                    results.append(r"(?!\.)")
                results.extend(_translate_fnmatch(part, f"{not_sep}*", not_sep))
            if idx < last_part_idx:
                results.append(any_sep)
    res = "".join(results)
    return rf"(?s:{res})\Z"


def _ext_to_suffixes(extension: str) -> tuple["str", ...]:
    suffix_parts = extension.split(".")
    return tuple(f".{part}" for part in suffix_parts if part)


_PYLIB_SUFFIX = ".so"  # .dylib is never importable as a Python module, even on macOS
_LIB_SUFFIXES = frozenset((_PYLIB_SUFFIX, ".dylib"))

# Skip libraries with extensions that are explicitly for importable Python extension modules
_IGNORED_SUFFIXES = frozenset(
    _ext_to_suffixes(ext) for ext in EXTENSION_SUFFIXES if ext != _PYLIB_SUFFIX
)


def find_shared_libraries(
    py_version: tuple[str, str], base_path: Path, *, excluded: Iterable[str] = ()
) -> Generator[Path, None, None]:
    """Find non-extension-module shared libraries in specified directory."""
    exclusion_patterns = [
        re.compile(_translate_glob(f"/{trailing}", recursive=True))
        for trailing in excluded
    ]
    py_version_nodot = "".join(py_version)
    running_py_version_nodot = "".join(map(str, sys.version_info[:2]))
    if py_version_nodot == running_py_version_nodot:
        ignored_suffixes = _IGNORED_SUFFIXES
    else:
        ignored_suffixes = frozenset(
            _ext_to_suffixes(ext.replace(running_py_version_nodot, py_version_nodot))
            for ext in EXTENSION_SUFFIXES
            if ext != _PYLIB_SUFFIX
        )

    # Python 3.11 compatibility: use os.walk instead of Path.walk
    for this_dir, _, files in os.walk(base_path):
        dir_path = Path(this_dir)
        for fname in files:
            file_path = dir_path / fname
            if file_path.suffix not in _LIB_SUFFIXES:
                continue
            if tuple(file_path.suffixes) in ignored_suffixes:
                continue
            if any(p.search(str(file_path)) for p in exclusion_patterns):
                continue
            yield file_path


def map_symlink_targets(
    symlink_dir_path: Path, target_paths: Iterable[Path]
) -> tuple[dict[Path, Path], dict[Path, set[Path]]]:
    targets_to_link: dict[Path, Path] = {}
    ambiguous_link_targets: dict[Path, set[Path]] = {}
    for target_path in target_paths:
        symlink_path = symlink_dir_path / target_path.name
        if symlink_path in ambiguous_link_targets:
            # Already ambiguous, record another potential target
            ambiguous_link_targets[symlink_path].add(target_path)
            continue
        existing_path = targets_to_link.get(symlink_path, None)
        if existing_path is not None:
            # This name already has a target
            if existing_path == target_path:
                continue
            # Mark the link as ambiguous
            existing_path = targets_to_link.pop(symlink_path)
            ambiguous_link_targets[symlink_path] = {existing_path, target_path}
            continue
        targets_to_link[symlink_path] = target_path
    return targets_to_link, ambiguous_link_targets
