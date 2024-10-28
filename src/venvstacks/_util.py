"""Common utilities for stack creation and venv publication"""

import os
import os.path
import subprocess
import sys
import tarfile

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Literal, Mapping, overload

WINDOWS_BUILD = hasattr(os, "add_dll_directory")

StrPath = str | os.PathLike[str]


def as_normalized_path(path: StrPath, /) -> Path:
    """Normalize given path and make it absolute, *without* resolving symlinks

    Expands user directory references, but *not* environment variable references.
    """
    # Ensure user directory references are handled as absolute paths
    expanded_path = os.path.expanduser(path)
    return Path(os.path.abspath(expanded_path))


@contextmanager
def default_tarfile_filter(filter: str) -> Generator[None, None, None]:
    """Temporarily set a global tarfile filter (useful for 3rd party API warnings)"""
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


def get_env_python(env_path: Path) -> Path:
    """Return the main Python binary in the given Python environment"""
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
    if env is not None:
        run_env.update(env)
    run_env.update(_SUBPROCESS_PYTHON_CONFIG)
    # Default to running in text mode,
    # but allow it to be explicitly switched off
    text = text if text else False
    encoding = "utf-8" if text else None
    result: subprocess.CompletedProcess[str] = subprocess.run(
        command, env=env, text=text, encoding=encoding, **kwds
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
