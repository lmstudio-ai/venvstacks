#!/bin/python3
"""Portable Python environment stacks.

Creates Python runtime, framework, and app environments based on ``venvstacks.toml``
"""

import csv
import dataclasses
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import warnings

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace as dc_replace
from datetime import datetime, timezone
from enum import StrEnum
from fnmatch import fnmatch
from functools import total_ordering
from itertools import chain
from pathlib import Path
from typing import (
    cast,
    overload,
    Any,
    Callable,
    ClassVar,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    MutableMapping,
    NamedTuple,
    NewType,
    NoReturn,
    NotRequired,
    Self,
    Sequence,
    Set,
    TypeVar,
    TypedDict,
)
from urllib.parse import urlparse

import tomlkit

from installer.records import parse_record_file
from packaging.utils import NormalizedName, canonicalize_name
from packaging.version import Version

from . import pack_venv
from ._hash_content import hash_file_contents, hash_module, hash_strings
from ._injected import postinstall
from ._source_tree import SourceTreeContentFilter, get_default_source_filter
from ._ui import termui
from ._util import (
    as_normalized_path,
    capture_python_output,
    default_tarfile_filter,
    find_shared_libraries,
    map_symlink_targets,
    run_python_command,
    walk_path,
    StrPath,
    WINDOWS_BUILD as _WINDOWS_BUILD,
)

_API_STABILITY_WARNING = f"""\
The {__package__} API is NOT YET STABLE and is expected to change in future releases.
"""
# If the CLI submodule has been loaded first, assume it is the main application
# This avoids the CLI needing to explicitly suppress this warning
if f"{__package__}.cli" not in sys.modules:
    warnings.warn(_API_STABILITY_WARNING, FutureWarning)


class EnvStackError(Exception):
    """Common base class for all errors specific to managing environment stacks."""


class LayerSpecError(ValueError, EnvStackError):
    """Raised when an internal inconsistency is found in a layer specification."""


class BuildEnvError(RuntimeError, EnvStackError):
    """Raised when a build environment doesn't comply with process restrictions."""


class LayerLockError(RuntimeError, EnvStackError):
    """Raised when locking a layer fails."""


class LayerInstallationError(RuntimeError, EnvStackError):
    """Raised when installing packages into a layer fails."""


######################################################
# Console output
######################################################
_UI = termui.UI()
_LOG = logging.getLogger(__name__)

# General logging levels:
# Per-environment notices -> INFO
# Per-file (or other steps within environment) -> DEBUG

######################################################
# Filesystem and git helpers
######################################################

try:
    _fs_sync = os.sync  # type: ignore[attr-defined,unused-ignore]
except AttributeError:
    # No os.sync on Windows
    def _fs_sync() -> None:
        pass


def _get_path_mtime(fspath: StrPath) -> datetime | None:
    path = Path(fspath)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.lstat().st_mtime).astimezone()


def _format_as_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _format_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def _write_json(target_path: Path, data: Any) -> None:
    formatted_data = _format_json(data)
    with target_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(formatted_data + "\n")


def _resolve_lexical_path(path: StrPath, base_path: Path, /) -> Path:
    # Ensure `~/...` paths are treated as absolute
    resolved_path = Path(path).expanduser()
    if not resolved_path.is_absolute():
        # Resolve paths relative to the given base path
        resolved_path = base_path / resolved_path
    # Avoid resolving symlinks (so they're respected when calculating relative paths)
    # but remove any `/../` segments
    return as_normalized_path(resolved_path)


######################################################
# Specifying package index access settings
######################################################


class _IndexDetails(TypedDict):
    name: NotRequired[str]
    url: str
    format: NotRequired[str]
    explicit: NotRequired[bool]


@dataclass
class PackageIndexConfig:
    """Python package index access configuration."""

    query_default_index: bool = True
    local_wheel_dirs: tuple[StrPath, ...] | None = field(repr=False, default=None)
    local_wheel_paths: list[Path] = field(init=False)

    # Tool specific config is implicitly queried and cached when loading a specification file
    _common_config_uv: dict[str, Any] = field(
        init=False, repr=False, default_factory=dict
    )
    _indexes: list[_IndexDetails] = field(init=False, repr=False, default_factory=list)
    _common_indexes: list[_IndexDetails] = field(
        init=False, repr=False, default_factory=list
    )
    _named_indexes: dict[str, _IndexDetails] = field(
        init=False, repr=False, default_factory=dict
    )
    _common_package_indexes: dict[NormalizedName, str] = field(
        init=False, repr=False, default_factory=dict
    )
    _uv_exclude_newer: datetime | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        local_wheel_dirs = self.local_wheel_dirs
        if isinstance(local_wheel_dirs, (str, Path)):
            # Strings and paths are iterable, so explicitly reject them instead of iterating
            err_msg = f"local_wheel_dirs must be a sequence of paths (got {local_wheel_dirs!r})"
            raise TypeError(err_msg)
        # Ensure local wheel dirs field can be safely copied (even if an iterator is passed in)
        if local_wheel_dirs:
            self.local_wheel_dirs = local_wheel_dirs = tuple(local_wheel_dirs)
            self.local_wheel_paths = [Path(wheel_dir) for wheel_dir in local_wheel_dirs]
        else:
            self.local_wheel_dirs = ()
            self.local_wheel_paths = []

    def copy(self) -> Self:
        """Create a copy of the index config with all internal caches cleared."""
        # dataclasses.replace resets `init=False` fields to their post-init values
        # This is desired here, as those fields cache usage dependent results
        return dc_replace(self)

    @classmethod
    def disabled(cls) -> Self:
        """Package index configuration that disallows package installation."""
        return cls(
            query_default_index=False,
            local_wheel_dirs=None,
        )

    def _get_uv_export_args(self, build_path: Path) -> list[str]:
        # Currently no config-dependent export-specific CLI args
        return []

    def _get_uv_lock_args(self, build_path: Path) -> list[str]:
        # Currently no config-dependent lock-specific CLI args
        return []

    def _get_uv_pip_install_args(self, build_path: Path) -> list[str]:
        # Currently no config-dependent installation-specific CLI args
        return []

    @staticmethod
    def _get_uv_input_config_path(spec_path: Path) -> Path:
        return spec_path.parent / "venvstacks.uv.toml"

    @staticmethod
    def _get_uv_config_path(build_path: Path) -> Path:
        return build_path / "uv.toml"

    def _resolve_lexical_paths(self, base_path: StrPath) -> None:
        """Lexically resolve paths in config relative to the given base path."""
        base_path = Path(base_path).absolute()
        self.local_wheel_paths[:] = [
            _resolve_lexical_path(path, base_path) for path in self.local_wheel_paths
        ]

    def _is_known_package_index(self, index_name: str) -> bool:
        if not self._common_config_uv:
            raise RuntimeError(
                "Tool config must be loaded before checking package index validity"
            )
        return index_name in self._named_indexes

    @staticmethod
    def _get_named_indexes(
        indexes: Iterable[_IndexDetails],
    ) -> dict[str, _IndexDetails]:
        named_indexes: dict[str, _IndexDetails] = {}
        for index_details in indexes:
            index_name = index_details.get("name")
            if not index_name:
                continue
            named_indexes[index_name] = index_details
        return named_indexes

    def _parse_raw_sources(
        self, raw_sources: dict[str, Any]
    ) -> dict[NormalizedName, str]:
        package_indexes: dict[NormalizedName, str] = {}
        for raw_dist_name, source_ref in raw_sources.items():
            index_name = source_ref.get("index", None)
            if index_name is None:
                msg = (
                    f"Common uv source config for {raw_dist_name} "
                    f"must be an index config, not {source_ref!r} "
                )
                raise LayerSpecError(msg)
            if not self._is_known_package_index(index_name):
                msg = (
                    f"Common uv source config for {raw_dist_name} "
                    f"references an unknown package index {index_name!r}"
                )
                raise LayerSpecError(msg)
            dist_name = canonicalize_name(raw_dist_name)
            if dist_name in package_indexes:
                msg = (
                    f"Common uv source config specifies multiple sources for {dist_name} "
                    f"after name normalization ({raw_dist_name} is the second entry)"
                )
                raise LayerSpecError(msg)
            package_indexes[dist_name] = index_name
        return package_indexes

    def _define_local_wheel_locations(self) -> Iterator[str]:
        return map(os.fspath, self.local_wheel_paths)

    def _load_common_tool_config(self, spec_path: Path) -> dict[str, Any]:
        # Loading the tool config couples this config instance to the given stack specification
        # (copying the config first allows a single index config to be used across multiple stacks)
        if self._common_config_uv:
            raise RuntimeError(
                "Attempted to reuse path index config with new spec path"
            )
        # Ensure paths are absolute. Relative input paths are left alone for config copying.
        self._resolve_lexical_paths(spec_path.parent)
        # Load the common uv config settings (including the package index priority and details)
        baseline_config_uv: dict[Any, Any] | None = None
        spec_config = tomlkit.parse(spec_path.read_text("utf-8"))
        inline_tool_config = spec_config.get("tool", None)
        if isinstance(inline_tool_config, dict):
            inline_uv_config = inline_tool_config.get("uv")
            if inline_uv_config is not None:
                # Unwrap to ensure all nested keys have the tool.uv prefix removed
                baseline_config_uv = inline_uv_config.unwrap()
        if baseline_config_uv is None:
            baseline_config_input_path = self._get_uv_input_config_path(spec_path)
            if baseline_config_input_path.exists():
                # Ensure the given baseline config file is valid TOML
                baseline_content = baseline_config_input_path.read_text("utf-8")
                baseline_config_uv = tomlkit.parse(baseline_content).unwrap()
            else:
                baseline_config_uv = {}
        raw_common_sources: dict[str, str] = baseline_config_uv.pop("sources", {})
        common_config_uv: dict[str, Any] = self._common_config_uv
        common_config_uv.update(baseline_config_uv)
        del baseline_config_uv
        if not self.query_default_index:
            common_config_uv["no-index"] = True
        # Local wheel builds must be created in advance for any source-only dependencies
        common_config_uv["no-build"] = True
        if self.local_wheel_paths:
            local_wheels_config_uv = common_config_uv.setdefault("find-links", [])
            local_wheels_config_uv.extend(self._define_local_wheel_locations())
        self._indexes = all_indexes = common_config_uv.pop("index", [])
        self._common_indexes = [
            x for x in all_indexes if x.get("default") or not x.get("explicit")
        ]
        self._named_indexes = self._get_named_indexes(all_indexes)
        self._common_package_indexes = self._parse_raw_sources(raw_common_sources)
        _exclude_newer_text = common_config_uv.get("exclude-newer", None)
        if _exclude_newer_text is not None:
            self._uv_exclude_newer = datetime.fromisoformat(_exclude_newer_text)
        self._common_config_uv = common_config_uv
        return common_config_uv

    def _write_common_tool_config_files(self, build_path: Path) -> None:
        common_config_uv = self._common_config_uv
        assert common_config_uv is not None
        # While the common uv config settings are passed in each layer's pyproject.toml,
        # they're also written out to a dedicated file for build debugging purposes
        uv_config_path = self._get_uv_config_path(build_path)
        with uv_config_path.open("w") as f:
            tomlkit.dump(common_config_uv, f)

    def _get_uv_exclude_newer(self) -> datetime | None:
        if not self._common_config_uv:
            raise RuntimeError(
                "Tool config must be loaded before reading exclude-newer"
            )
        # Check for `UV_EXCLUDE_NEWER` (as that takes precedence)
        exclude_newer_text = os.getenv("UV_EXCLUDE_NEWER")
        if exclude_newer_text:
            return datetime.fromisoformat(exclude_newer_text)
        # Check for `exclude-newer` config setting
        return self._uv_exclude_newer


######################################################
# Specifying layered environments
######################################################

# Define dedicated nominal types to help reduce risk of confusing
# layer base names (no prefix), layer build environment names
# (potentially with a kind prefix), and deployed layer environment
# names (potentially with a version suffix)
LayerBaseName = NewType("LayerBaseName", str)
EnvNameBuild = NewType("EnvNameBuild", str)
EnvNameDeploy = NewType("EnvNameDeploy", str)


def _filter_flat_reqs(potential_reqs: Iterable[str]) -> Iterable[str]:
    # Parse potential dependency lines from a flat requirements file
    # - omit trailing backslash line escapes
    # - ignore comments and blank lines
    # - ignore artifact hash declarations
    for line in potential_reqs:
        req_line = line.rstrip("\\").strip()
        req, _sep, _comment = req_line.strip().partition("#")
        req = req.strip()
        if req and "--hash" not in req:
            yield req


def _clean_flat_reqs(potential_reqs: Iterable[str]) -> Sequence[str]:
    return sorted(_filter_flat_reqs(potential_reqs))


def _read_flat_reqs(requirements_path: Path) -> Sequence[str] | None:
    if not requirements_path.exists():
        return None
    return _clean_flat_reqs(requirements_path.read_text("utf-8").splitlines())


def _hash_flat_reqs(potential_reqs: Iterable[str]) -> str:
    return hash_strings(_clean_flat_reqs(potential_reqs))


def _hash_flat_reqs_file(requirements_path: Path) -> str | None:
    reqs = _read_flat_reqs(requirements_path)
    if reqs is None:
        return None
    return hash_strings(reqs)


def _extract_wheel_details(
    locked_wheel: Mapping[str, Any],
) -> tuple[str | None, Path | None]:
    # Wheel name can be reported in one of three ways
    name: str | None = locked_wheel.get("name", None)
    raw_local_path: str | None = locked_wheel.get("path", None)
    local_path: Path | None = None
    if raw_local_path is not None:
        local_path = Path(raw_local_path)
        if name is None:
            name = local_path.name
        return name, local_path
    raw_url: str = locked_wheel.get("url", None)
    if raw_url is not None:
        parsed_url = urlparse(raw_url)
        url_path = parsed_url.path
        name = url_path.rpartition("/")[2]
        if parsed_url.scheme == "file":
            local_path = Path(url_path)
    return name, local_path


@dataclass
class LockedWheel:
    """Details of a locked distribution package (extracted from pylock.toml)."""

    name: str
    hashes: dict[str, str]
    local_path: Path | None = None

    @classmethod
    def from_dict(cls, wheel_entry: Mapping[str, Any]) -> Self:
        """Parse a wheel entry extracted from a pylock.toml file."""
        name, local_path = _extract_wheel_details(wheel_entry)
        whl = {"name": name, "hashes": wheel_entry["hashes"], "local_path": local_path}
        return cls(**whl)


@total_ordering
@dataclass
class LockedPackage:
    """Details of a locked distribution package (extracted from pylock.toml)."""

    name: str
    version: Version
    marker: str
    index: str
    wheels: list[LockedWheel]

    def __str__(self) -> str:
        marker = self.marker
        marker_suffix = f" ; {marker}" if marker else ""
        return f"{self.name}=={self.version}{marker_suffix}"

    def __hash__(self) -> int:
        return hash((self.name, self.version, self.marker))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, LockedPackage):
            return NotImplemented
        return bool(
            self.name == other.name
            and self.version == other.version
            and self.marker == other.marker
        )

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, LockedPackage):
            return NotImplemented
        return bool(
            self.name < other.name
            and self.version < other.version
            and self.marker < other.marker
        )

    @classmethod
    def from_dict(cls, pkg_entry: Mapping[str, Any]) -> Self:
        """Parse a package entry extracted from a pylock.toml file."""
        # version isn't technically required, but all locked layer versions should be pinned
        # environment markers are genuinely optional for unconditionally installed packages
        wheels = [LockedWheel.from_dict(whl) for whl in pkg_entry.get("wheels", ())]
        pkg = {
            "name": pkg_entry["name"],
            "version": Version(pkg_entry["version"]),
            "marker": pkg_entry.get("marker", ""),
            "index": pkg_entry.get("index", "unspecified index"),
            "wheels": wheels,
        }
        return cls(**pkg)


def _iter_pylock_packages(
    pylock_text: str,
    text_origin: str = "unspecified pylock.toml",
    *,
    exclude_shared: bool = False,
) -> Iterable[LockedPackage]:
    # Parse the package entries from the contents of a pylock.toml file
    # TODO: Nicer errors if the path isn't pointing at a valid pylock.toml file
    # That can wait until after https://github.com/pypa/packaging/pull/900 is released,
    # allowing this to switch to using packaging.Pylock instead of ad hoc TOML parsing
    pylock_dict = tomlkit.parse(pylock_text)
    pkg_list = pylock_dict.get("packages", [])
    if not isinstance(pkg_list, list):
        raise BuildEnvError(f"Invalid packages list in {text_origin}")
    for raw_pkg in pkg_list:
        if not isinstance(raw_pkg, dict):
            raise BuildEnvError(f"Invalid packages entry in {text_origin}")
        pkg = LockedPackage.from_dict(raw_pkg)
        if exclude_shared and _SHARED_PKG_MARKER in pkg.marker:
            continue
        yield pkg


_SHARED_PKG_MARKER = "from_lower_layer"


def _iter_pylock_packages_from_file(
    pylock_path: Path, *, exclude_shared: bool = False
) -> Iterable[LockedPackage]:
    # Read package details from a pylock.toml file
    pylock_text = pylock_path.read_text("utf-8")
    return _iter_pylock_packages(
        pylock_text, str(pylock_path), exclude_shared=exclude_shared
    )


def _iter_pylock_hash_inputs(
    pylock_text: str, text_origin: str = "unspecified pylock.toml"
) -> Iterable[str]:
    for pkg in _iter_pylock_packages(pylock_text, text_origin):
        pkg_req = str(pkg)
        yield f"{pkg_req} from {pkg.index}"
        for whl in pkg.wheels:
            whl_name = whl.name
            if not whl_name:
                raise BuildEnvError(f"Missing wheel name in {text_origin}")
            for algorithm, whl_hash in whl.hashes.items():
                yield f"{whl_name}:{algorithm}:{whl_hash}"


def _hash_pylock_file(requirements_path: Path) -> str | None:
    if not requirements_path.exists():
        return None
    hash_inputs = _iter_pylock_hash_inputs(requirements_path.read_text("utf-8"))
    return hash_strings(sorted(hash_inputs))


class EnvironmentLockMetadata(TypedDict):
    """Details of the last time this environment was locked."""

    # fmt: off
    requirements_hash: str    # Uses "algorithm:hexdigest" format
    lock_input_hash: str      # Uses "algorithm:hexdigest" format
    other_inputs_hash: str    # Uses "algorithm:hexdigest" format
    version_inputs_hash: str  # Uses "algorithm:hexdigest" format
    lock_version: int         # Auto-incremented from previous lock metadata
    locked_at: str            # ISO formatted date/time value
    # fmt: on


_T = TypeVar("_T")


@dataclass
class EnvironmentLock:
    """Layered environment dependency locking management."""

    locked_requirements_path: Path
    declared_requirements: tuple[str, ...]
    other_inputs: tuple[str, ...]
    version_inputs: tuple[str, ...]
    versioned: bool = False
    _lock_input_path: Path = field(init=False, repr=False)
    _lock_input_hash: str = field(init=False, repr=False)
    _requirements_hash: str | None = field(init=False, repr=False)
    _other_inputs_hash: str = field(init=False, repr=False)
    _version_inputs_hash: str = field(init=False, repr=False)
    _lock_metadata_path: Path = field(init=False, repr=False)
    _last_locked: datetime | None = field(init=False, repr=False)
    _lock_version: int | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        req_path = self.locked_requirements_path
        pylock_match = re.match(r"^pylock\.([^.]+)\.toml$", req_path.name)
        if pylock_match is None:
            msg = (
                f"{req_path.name} must match the pattern 'pylock.*.toml' "
                "(with no additional periods)"
            )
            raise BuildEnvError(msg)
        env_name = pylock_match.group(1)
        self._lock_input_path = req_path.with_name(f"requirements-{env_name}.in")
        self._lock_metadata_path = req_path.with_suffix(".meta.json")
        self._update_hashes()
        self._last_locked = None
        self._lock_version = None
        self._update_from_valid_lock_info()

    def _update_from_valid_lock_info(self) -> None:
        self._last_locked = last_locked = self._get_last_locked_time()
        if last_locked:
            self._lock_version = self._get_last_locked_version()

    def invalidate_lock(self) -> None:
        """Mark the lock as invalid, even if it appears locally consistent.

        Typically used when layer depends on another layer with an invalid lock.
        """
        # The lock file is left on disk (a lock *reset* will clear it completely)
        self._requirements_hash = None
        self._last_locked = None
        self._lock_version = None

    def get_deployed_name(
        self, env_name: EnvNameBuild, *, placeholder: str | None = None
    ) -> EnvNameDeploy:
        """Report layer name with lock version (if any) appended.

        Deployed name matches the build name if automatic lock versioning is disabled.
        """
        if self.versioned:
            version_text: str
            if self.has_valid_lock:
                version_text = str(self.lock_version)
            elif placeholder is None:
                msg = "Must specify placeholder to query deployed name of unlocked versioned layer"
                self._fail_lock_metadata_query(msg)
            else:
                version_text = placeholder
            return EnvNameDeploy(f"{env_name}@{version_text}")
        return EnvNameDeploy(env_name)

    def append_other_input(self, other_input: str) -> None:
        """Supply an additional "other input" to use when determining lock validity."""
        self.other_inputs = (*self.other_inputs, other_input)
        self._update_other_inputs_hash()
        self._update_from_valid_lock_info()

    def append_version_input(self, version_input: str) -> None:
        """Supply an additional "version input" to use when determining lock version validity."""
        self.version_inputs = (*self.version_inputs, version_input)
        self._update_version_inputs_hash()
        self._update_from_valid_lock_info()

    def extend_other_inputs(self, other_inputs: Sequence[str]) -> None:
        """Supply additional "other inputs" to use when determining lock validity."""
        self.other_inputs = (*self.other_inputs, *other_inputs)
        self._update_other_inputs_hash()
        self._update_from_valid_lock_info()

    def _fail_lock_metadata_query(self, message: str) -> NoReturn:
        req_path = self.locked_requirements_path
        if req_path.exists():
            reason = "has changed since layer was last locked"
        else:
            reason = "does not exist"
        msg = f"{message} ({req_path.name!r} {reason})"
        raise BuildEnvError(msg)

    def _raise_if_none(self, value: _T | None) -> _T:
        if value is None:
            self._fail_lock_metadata_query("Environment has not been locked")
        return value

    @property
    def requirements_hash(self) -> str:
        """Hash of the last locked set of layer requirements."""
        return self._raise_if_none(self._requirements_hash)

    @property
    def last_locked(self) -> datetime:
        """Date and time when the layer requirements were last locked."""
        return self._raise_if_none(self._last_locked)

    @property
    def lock_version(self) -> int:
        """Last recorded version of the layer requirements.

        Always reports ``1`` if automatic lock versioning is disabled.
        """
        if not self.versioned:
            # Unversioned specs are always considered version 1
            return 1
        return self._raise_if_none(self._lock_version)

    @property
    def has_valid_lock(self) -> bool:
        """``True`` if layer has been locked and lock metadata is consistent."""
        # For versioned layers, this also indicates the version metadata is up to date
        return self._last_locked is not None and self.load_valid_metadata() is not None

    @property
    def needs_full_lock(self) -> bool:
        """``True`` if layer has not been locked or transitive lock metadata is inconsistent."""
        # For versioned layers, skips checking whether the version metadata is up to date
        return (
            self._last_locked is None
            or self.load_valid_metadata(ignore_version=True) is None
        )

    @property
    def locked_at(self) -> str:
        """ISO-formatted UTC string reporting the last locked date/time."""
        return _format_as_utc(self.last_locked)

    def _update_other_inputs_hash(self) -> None:
        self._other_inputs_hash = hash_strings(self.other_inputs)

    def _update_version_inputs_hash(self) -> None:
        self._version_inputs_hash = hash_strings(self.version_inputs)

    def _update_hashes(self) -> None:
        self._update_other_inputs_hash()
        self._update_version_inputs_hash()
        self._lock_input_hash = input_hash = _hash_flat_reqs(self.declared_requirements)
        req_hash = None
        last_metadata = self._load_saved_metadata()
        if last_metadata is not None:
            # TODO: Introduce a cleaner (less ad hoc) migration mechanism for lock metadata
            # 0.8.0 adopted cross platform locks, so the migration for older locks was dropped
            # (all lock files from older versions are invalid, as they use a different format)
            if "_legacy_requirements_hash" not in last_metadata:
                last_lock_input_hash = last_metadata.get("lock_input_hash", None)
                if input_hash == last_lock_input_hash:
                    # Declared reqs hash is consistent, so also check the locked output hash
                    req_hash = _hash_pylock_file(self.locked_requirements_path)
        self._requirements_hash = req_hash

    @staticmethod
    def _write_declared_requirements(
        declared_reqs_path: Path, declared_requirements: Sequence[str]
    ) -> None:
        declared_reqs_path.parent.mkdir(parents=True, exist_ok=True)
        with declared_reqs_path.open("w", encoding="utf-8", newline="\n") as f:
            lines = [
                "# DO NOT EDIT. Automatically generated by venvstacks.",
                "#              Relock layer dependencies to update.",
                *declared_requirements,
                "",
            ]
            f.write("\n".join(lines))

    def prepare_lock_inputs(self) -> Path:
        """Write declared requirements to disk as a locking process input."""
        declared_reqs_path = self._lock_input_path
        self._write_declared_requirements(
            declared_reqs_path, self.declared_requirements
        )
        return declared_reqs_path

    def _load_saved_metadata(self) -> EnvironmentLockMetadata | None:
        """Loads last locked metadata from disk (if it exists)."""
        lock_metadata_path = self._lock_metadata_path
        if not lock_metadata_path.exists():
            return None
        with lock_metadata_path.open("r", encoding="utf-8") as f:
            # mypy is right to complain that the JSON hasn't been validated to conform to
            # the EnvironmentLockMetadata interface, but we're OK with letting the runtime
            # errors happen in that scenario. Longer term, explicit JSON schemas should be
            # defined and used for validation when reading the metadata files.
            return cast(EnvironmentLockMetadata, json.load(f))

    def load_valid_metadata(
        self, ignore_version: bool = False
    ) -> EnvironmentLockMetadata | None:
        """Loads last locked metadata only if the requirements hash matches."""
        # No requirements declaration file -> metadata is not valid
        lock_input_hash = self._lock_input_hash
        if lock_input_hash is None:
            return None
        # No locked requirements file (or an input hash mismatch) -> metadata is not valid
        req_hash = self._requirements_hash
        if req_hash is None:
            return None
        # Metadata is valid only if the recorded hashes match the files on disk
        lock_metadata = self._load_saved_metadata()
        if lock_metadata is None:
            return None
        last_req_hash = lock_metadata.get("requirements_hash", None)
        check_version = not ignore_version and self.versioned
        have_valid_lock = (
            req_hash == last_req_hash
            and lock_input_hash == lock_metadata.get("lock_input_hash", None)
            and (
                self._other_inputs_hash == lock_metadata.get("other_inputs_hash", None)
            )
            and (
                not check_version
                or (
                    self._version_inputs_hash
                    == lock_metadata.get("version_inputs_hash", None)
                )
            )
        )
        if not have_valid_lock:
            return None
        return lock_metadata

    def _get_last_locked_metadata(self) -> datetime | None:
        lock_metadata = self.load_valid_metadata()
        if lock_metadata is not None:
            return datetime.fromisoformat(lock_metadata["locked_at"])
        return None

    def _get_path_mtime(self) -> datetime | None:
        return _get_path_mtime(self.locked_requirements_path)

    def _get_last_locked_time(self) -> datetime | None:
        # Retrieve the lock timestamp from an adjacent (still valid) lock metadata file
        last_locked = self._get_last_locked_metadata()
        if last_locked is not None:
            return last_locked
        # Otherwise wait until the lock metadata is updated after the layer is locked
        return None

    def _get_last_locked_version(self) -> int | None:
        lock_metadata = self.load_valid_metadata()
        if lock_metadata is not None:
            # Unversioned specs are always considered version 1
            return lock_metadata.get("lock_version", 1)
        return None

    def _clear_lock_input_cache(self) -> bool:
        # Lock input path should serve as a pure cache of info from the TOML stack spec
        # Allow the test suite to ensure nothing depends on the input file existing
        path_to_remove = self._lock_input_path
        if path_to_remove.exists():
            path_to_remove.unlink()
            return True
        return False

    def _purge_lock(self) -> bool:
        # Currently a test suite helper, but may become a public API if it proves
        # useful when implementing https://github.com/lmstudio-ai/venvstacks/issues/10
        # However, a public version may need to preserve the lock version info by default
        files_removed = self._clear_lock_input_cache()
        for path_to_remove in (self.locked_requirements_path, self._lock_metadata_path):
            if path_to_remove.exists():
                path_to_remove.unlink()
                files_removed = True
        return files_removed

    def _write_lock_metadata(self) -> None:
        lock_input_hash = self._lock_input_hash
        req_hash = self._requirements_hash
        if lock_input_hash is None or req_hash is None:
            self._fail_lock_metadata_query(
                "Environment must be locked before writing lock metadata"
            )
        last_metadata = self._load_saved_metadata() if self.versioned else None
        if last_metadata is not None:
            # Bump the recorded lock version
            last_version = last_metadata.get("lock_version", 0)
            lock_version = last_version + 1
        else:
            # Defining a new lock or layer is not versioned
            lock_version = 1
        self._lock_version = lock_version
        lock_metadata = EnvironmentLockMetadata(
            requirements_hash=req_hash,
            lock_input_hash=lock_input_hash,
            other_inputs_hash=self._other_inputs_hash,
            version_inputs_hash=self._version_inputs_hash,
            lock_version=lock_version,
            locked_at=self.locked_at,
        )
        _write_json(self._lock_metadata_path, lock_metadata)

    def _sync_cached_lock_metadata(
        self, lock_metadata: EnvironmentLockMetadata
    ) -> None:
        # If lock was previously invalidated, update any affected fields
        self._last_locked = datetime.fromisoformat(lock_metadata["locked_at"])
        self._lock_version = lock_metadata.get("lock_version", 1)

    @staticmethod
    def _hash_input_reqs_file(requirements_path: Path) -> str | None:
        return _hash_flat_reqs_file(requirements_path)

    @staticmethod
    def _hash_locked_reqs_file(requirements_path: Path) -> str | None:
        return _hash_pylock_file(requirements_path)

    def update_lock_metadata(self, clamp_lock_time: datetime | None = None) -> bool:
        """Update the recorded lock metadata for this environment lock."""
        # Calculate current requirements hashes
        lock_input_hash = self._hash_input_reqs_file(self._lock_input_path)
        req_hash = self._hash_locked_reqs_file(self.locked_requirements_path)
        if lock_input_hash != self._lock_input_hash or req_hash is None:
            self._fail_lock_metadata_query(
                "Environment must be locked before updating lock metadata"
            )
        self._requirements_hash = req_hash
        # Only update and save the last locked time if
        # the lockfile contents have changed,
        # the lock metadata file doesn't exist yet, or
        # the recorded lock time is too recent
        lock_metadata = self.load_valid_metadata()
        lock_time: datetime | None = None
        if lock_metadata is not None and clamp_lock_time is not None:
            recorded_lock_time = datetime.fromisoformat(lock_metadata["locked_at"])
            if recorded_lock_time > clamp_lock_time:
                # Force writing the clamped lock time to the metadata file
                lock_metadata = None
                lock_time = clamp_lock_time
        if lock_metadata is None:
            # Metadata file didn't exist, the hashes didn't match,
            # or the recorded lock time needs clamping
            if lock_time is None:
                lock_time = self._get_path_mtime()
                assert lock_time is not None, (
                    "Failed to read lock time for locked environment"
                )
            self._last_locked = lock_time
            self._write_lock_metadata()
            return True
        else:
            self._sync_cached_lock_metadata(lock_metadata)
        return False

    def get_diagnostics(self) -> Mapping[str, Any]:
        """Retrieve internal lock details for diagnostic purposes."""
        last_metadata = self._load_saved_metadata()
        locked_at = (
            _format_as_utc(self._last_locked) if self._last_locked is not None else None
        )
        lock_metadata = {
            "lock_input_hash": self._lock_input_hash,
            "requirements_hash": self._requirements_hash,
            "other_inputs_hash": self._other_inputs_hash,
            "version_inputs_hash": self._version_inputs_hash,
            "locked_at": locked_at,
            "lock_version": self._lock_version,
        }
        changed_fields = set(lock_metadata)
        if last_metadata is not None:
            for k, v in lock_metadata.items():
                if last_metadata.get(k, None) == v:
                    changed_fields.remove(k)
        diagnostics: dict[str, Any] = {
            "last_metadata": last_metadata,
            "lock_metadata": lock_metadata,
            "changed_fields": sorted(changed_fields),
        }

        return diagnostics


# Identify target platforms using strings based on
# https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/#basic-platform-tags
# macOS target system API version info is omitted (as that will be set universally for macOS builds)
class TargetPlatforms(StrEnum):
    """Enum for support target deployment platforms."""

    WINDOWS = "win_amd64"
    WINDOWS_ARM64 = "win_arm64"
    LINUX = "linux_x86_64"
    LINUX_AARCH64 = "linux_aarch64"
    MACOS_APPLE = "macosx_arm64"
    MACOS_INTEL = "macosx_x86_64"  # Note: not currently tested in CI!

    @classmethod
    def get_all_target_platforms(cls) -> list[Self]:
        """Sorted list of all defined target platforms."""
        return sorted(set(cls.__members__.values()))

    @classmethod
    def ensure_platform_list(cls, metadata: MutableMapping[str, Any]) -> None:
        """Ensure given metadata mapping includes a ``"platforms`` field.

        If the field is not already present, it is set to all defined platforms.
        """
        platform_list = metadata.get("platforms")
        if platform_list is not None:
            platform_list = [cls(target) for target in platform_list]
        else:
            platform_list = cls.get_all_target_platforms()
        metadata["platforms"] = platform_list


TargetPlatform = (
    TargetPlatforms  # Use singular name when creating instances from values
)


class LayerVariants(StrEnum):
    """Enum for defined layer variants."""

    RUNTIME = "runtime"
    FRAMEWORK = "framework"
    APPLICATION = "application"


class LayerCategories(StrEnum):
    """Enum for defined layer categories (collections of each variant)."""

    RUNTIMES = "runtimes"
    FRAMEWORKS = "frameworks"
    APPLICATIONS = "applications"


def ensure_optional_env_spec_fields(env_metadata: MutableMapping[str, Any]) -> None:
    """Populate missing environment spec fields that are optional in the TOML file."""
    TargetPlatforms.ensure_platform_list(env_metadata)
    env_metadata.setdefault("versioned", False)
    env_metadata.setdefault("package_indexes", {})
    env_metadata.setdefault("priority_indexes", [])
    env_metadata.setdefault("dynlib_exclude", [])


@dataclass(kw_only=True)
class LayerSpecBase(ABC):
    """Common base class for layer environment specifications."""

    # Optionally overridden in concrete subclasses
    ENV_PREFIX = ""

    # Specified in concrete subclasses
    kind: ClassVar[LayerVariants]
    category: ClassVar[LayerCategories]

    # Specified on creation (typically based on TOML layer spec fields)
    name: LayerBaseName
    versioned: bool
    requirements: list[str] = field(repr=False)
    platforms: list[TargetPlatforms] = field(repr=False)
    package_indexes: dict[NormalizedName, str] = field(repr=False)
    priority_indexes: list[str] = field(repr=False)
    dynlib_exclude: list[str] = field(repr=False)

    # Optionally specified on creation
    _index_config: PackageIndexConfig = field(
        repr=False, default_factory=PackageIndexConfig
    )

    def __post_init__(self) -> None:
        # When instantiating specs that don't have a prefix,
        # they're not allowed to use prefixes that *are* defined
        layer_name = self.name
        if not self.ENV_PREFIX:
            for spec_type in LayerSpecBase.__subclasses__():
                reserved_prefix = spec_type.ENV_PREFIX
                if not reserved_prefix:
                    continue
                if layer_name.startswith(reserved_prefix + "-"):
                    err = (
                        f"{layer_name} starts with reserved prefix {reserved_prefix!r}"
                    )
                    raise LayerSpecError(err)
        index_config = self._index_config
        # Ensure any package index overrides reference known package index names
        raw_package_indexes = self.package_indexes
        package_indexes: dict[NormalizedName, str] = {}
        for raw_dist_name, index_name in raw_package_indexes.items():
            if not index_config._is_known_package_index(index_name):
                msg = (
                    f"{layer_name} references an unknown package index "
                    f"{index_name!r} for {raw_dist_name!r}"
                )
                raise LayerSpecError(msg)
            dist_name = canonicalize_name(raw_dist_name)
            if dist_name in package_indexes:
                msg = (
                    f"{layer_name} specifies multiple sources for {dist_name} "
                    f"after name normalization ({raw_dist_name} is the second entry)"
                )
                raise LayerSpecError(msg)
            package_indexes[dist_name] = index_name
        self.package_indexes = package_indexes
        # Ensure any index priority overrides reference known package index names
        priority_indexes = self.priority_indexes
        for index_name in priority_indexes:
            if not index_config._is_known_package_index(index_name):
                msg = (
                    f"{layer_name} priority index list references an unknown package index "
                    f"({index_name})"
                )
                raise LayerSpecError(msg)

    @property
    def env_name(self) -> EnvNameBuild:
        """Build environment name for this layer specification."""
        prefix = self.ENV_PREFIX
        if prefix:
            return EnvNameBuild(f"{prefix}-{self.name}")
        return EnvNameBuild(self.name)

    def get_requirements_fname(self, platform: str) -> str:
        """Locked requirements file name for this layer specification."""
        # '.' is disallowed in the name portion of named pylock.toml files
        return f"pylock.{self.env_name.replace('.', '_')}.toml"

    def get_requirements_path(self, platform: str, requirements_dir: StrPath) -> Path:
        """Full path of locked requirements file for this layer specification."""
        requirements_fname = self.get_requirements_fname(platform)
        return Path(requirements_dir) / self.env_name / requirements_fname

    def targets_platform(self, target_platform: str | TargetPlatform) -> bool:
        """Returns `True` if the layer will be built for the given target platform."""
        return target_platform in self.platforms

    def to_dict(self) -> Mapping[str, Any]:
        """Convert spec details to a JSON-compatible dict."""
        # Omit any private fields from the metadata dictionary
        result = dataclasses.asdict(self)
        for k in list(result):
            if k.startswith("_"):
                del result[k]
        # Remove nesting and ensure values round-trip through JSON files
        for k, v in result.items():
            match v:
                case {"name": layer_name}:
                    result[k] = layer_name
                case [{"name": _}, *_] as layer_seq:
                    result[k] = [layer["name"] for layer in layer_seq]
                case Path() as path_value:
                    result[k] = path_value.as_posix()
                case [Path(), *_] as path_seq:
                    result[k] = [p.as_posix() for p in path_seq]
                case StrEnum():
                    result[k] = str(v)
                case [StrEnum(), *_]:
                    result[k] = [str(s) for s in v]
                case []:
                    result[k] = []
        return result


@dataclass
class RuntimeSpec(LayerSpecBase):
    """Base runtime layer specification."""

    kind = LayerVariants.RUNTIME
    category = LayerCategories.RUNTIMES
    python_implementation: str = field(repr=False)

    @property
    def py_version(self) -> str:
        """Extract just the Python version string from the base runtime identifier."""
        # python_implementation should be of the form "implementation@X.Y.Z"
        # (this may need adjusting if runtimes other than CPython are ever used...)
        return self.python_implementation.partition("@")[2]


@dataclass
class LayeredSpecBase(LayerSpecBase):
    """Common base class for framework and application layer specifications."""

    # Intermediate class for covariant property typing (never instantiated)
    runtime: RuntimeSpec = field(repr=False)
    frameworks: list["FrameworkSpec"] = field(repr=False)


@dataclass
class FrameworkSpec(LayeredSpecBase):
    """Framework layer specification."""

    ENV_PREFIX = "framework"
    kind = LayerVariants.FRAMEWORK
    category = LayerCategories.FRAMEWORKS


@dataclass
class ApplicationSpec(LayeredSpecBase):
    """Application layer specification."""

    ENV_PREFIX = "app"
    kind = LayerVariants.APPLICATION
    category = LayerCategories.APPLICATIONS
    launch_module_path: Path = field(repr=False)
    support_module_paths: list[Path] = field(repr=False)


class SupportModuleMetadata(TypedDict):
    """Details of an unpackaged application support module."""

    name: NotRequired[str]
    hash: NotRequired[str]


class LayerSpecMetadata(TypedDict):
    """Details of a defined environment layer."""

    # fmt: off
    # Common fields defined for all layers, whether archived or exported
    layer_name: EnvNameBuild       # Prefixed layer name without lock version info
    install_target: EnvNameDeploy  # Target installation folder when unpacked
    requirements_hash: str         # Uses "algorithm:hexdigest" format
    lock_version: int              # Monotonically increasing version identifier
    locked_at: str                 # ISO formatted date/time value

    # Fields that are populated after the layer metadata has initially been defined
    # "runtime_layer" is set to the underlying runtime's deployed environment name
    # "python_implementation" is set to the underlying runtime's implementation name
    # "bound_to_implementation" means that the layered environment includes
    # copies of some files from the runtime implementation, and hence will
    # need updating even for runtime maintenance releases
    runtime_layer: NotRequired[str]
    python_implementation: NotRequired[str]
    bound_to_implementation: NotRequired[bool]

    # Extra fields only defined for framework and application environments
    required_layers: NotRequired[Sequence[EnvNameDeploy]]

    # Extra fields only defined for application environments
    app_launch_module: NotRequired[str]
    app_launch_module_hash: NotRequired[str]
    app_support_modules: NotRequired[Sequence[SupportModuleMetadata]]
    # fmt: on

    # Note: hashes of layered environment dependencies are intentionally NOT incorporated
    # into the published metadata. This allows an "only if needed" approach to
    # rebuilding app and framework layers when the layers they depend on are
    # updated (app layers will usually only depend on some of the components in the
    # underlying environment, and such dependencies are picked up as version changes
    # when regenerating the transitive dependency specifications for each environment)


######################################################
# Defining and describing published artifacts
######################################################


class ArchiveHashes(TypedDict):
    """Hash details of a built archive."""

    sha256: str
    # Only SHA256 hashes for now. Mark both old and new hash fields with `typing.NotRequired`
    # to migrate to a different hashing function in the future.


class ArchiveBuildMetadata(LayerSpecMetadata):
    """Inputs to an archive build request for a single environment."""

    # fmt: off
    archive_build: int    # Auto-incremented from previous build metadata
    archive_name: str     # Adds archive file extension to layer name
    target_platform: str  # Target platform identifier
    # fmt: on


class ArchiveMetadata(ArchiveBuildMetadata):
    """Archive details for a single environment (includes build request details)."""

    archive_size: int
    archive_hashes: ArchiveHashes


@dataclass
class ArchiveBuildRequest:
    """Structured request to build a named output archive."""

    env_name: EnvNameBuild
    env_lock: EnvironmentLock
    env_path: Path
    archive_base_path: Path
    build_metadata: ArchiveBuildMetadata = field(repr=False)
    needs_build: bool = field(repr=False)
    # Previously built metadata when a new build is not needed
    archive_metadata: ArchiveMetadata | None = None
    _prepare_deployed_env: Callable[[Path], None] | None = field(
        repr=False, default=None
    )

    @staticmethod
    def _needs_archive_build(
        archive_path: Path,
        metadata: ArchiveBuildMetadata,
        previous_metadata: ArchiveMetadata | None,
    ) -> bool:
        if not previous_metadata or not archive_path.exists():
            return True
        if archive_path.name != previous_metadata.get("archive_name"):
            # Previous build produced a different archive name, force a rebuild
            return True
        # Check for any other changes to build input metadata
        for key, value in metadata.items():
            if value != previous_metadata.get(key):
                # Input metadata for the archive build has changed, force a rebuild
                return True
        # Only check the metadata so archive builds can be skipped just by downloading
        # the metadata for previously built versions (rather than the entire archives)
        return False

    @classmethod
    def define_build(
        cls,
        env_name: EnvNameBuild,
        env_lock: EnvironmentLock,
        source_path: Path,
        output_path: Path,
        target_platform: str,
        tag_output: bool = False,
        previous_metadata: ArchiveMetadata | None = None,
        force: bool = False,
        prepare_deployed_env: Callable[[Path], None] | None = None,
    ) -> Self:
        """Define a new archive build request for the given environment."""
        # Bump or set the archive build version
        lock_version = env_lock.lock_version
        if previous_metadata is None:
            last_build_iteration = 0
        else:
            last_lock_version = previous_metadata.get("lock_version", 0)
            if lock_version != last_lock_version:
                # New lock version, reset the build iteration number
                last_build_iteration = 0
            else:
                # Rebuild with a change that isn't reflected in the lock version
                last_build_iteration = previous_metadata.get("archive_build", 0)
        # Work out the basic details of the build request (assuming no rebuild is needed)
        deployed_name = env_lock.get_deployed_name(env_name)
        build_iteration = last_build_iteration

        def update_archive_name() -> tuple[Path, Path]:
            if tag_output:
                base_name = f"{deployed_name}-{target_platform}-{build_iteration}"
            else:
                base_name = deployed_name
            archive_base_path = output_path / base_name
            built_archive_path = pack_venv.get_archive_path(archive_base_path)
            return archive_base_path, built_archive_path

        archive_base_path, built_archive_path = update_archive_name()
        build_metadata = ArchiveBuildMetadata(
            archive_build=last_build_iteration,
            archive_name=built_archive_path.name,
            install_target=deployed_name,
            layer_name=env_name,
            lock_version=lock_version,
            locked_at=env_lock.locked_at,
            requirements_hash=env_lock.requirements_hash,
            target_platform=str(target_platform),  # Convert enums to plain strings
        )
        needs_build = force or cls._needs_archive_build(
            built_archive_path, build_metadata, previous_metadata
        )
        if needs_build:
            # Forced build or input hashes have changed,
            # so this will be a new version of the archive
            build_iteration += 1
            archive_base_path, built_archive_path = update_archive_name()
            build_metadata["archive_build"] = build_iteration
            build_metadata["archive_name"] = built_archive_path.name
            archive_metadata = None
        else:
            # The build input metadata hasn't changed,
            # so the expected output metadata is also unchanged
            archive_metadata = previous_metadata
        env_path = source_path / env_name
        return cls(
            env_name,
            env_lock,
            env_path,
            archive_base_path,
            build_metadata,
            needs_build,
            archive_metadata,
            prepare_deployed_env,
        )

    @staticmethod
    def _hash_archive(archive_path: Path) -> ArchiveHashes:
        hashes: dict[str, str] = {}
        for algorithm in ArchiveHashes.__required_keys__:
            hashes[algorithm] = hash_file_contents(
                archive_path, algorithm, omit_prefix=True
            )
        # The required keys have been set, but mypy can't prove that,
        # so use an explicit cast to allow it to make that assumption
        return cast(ArchiveHashes, hashes)

    def create_archive(
        self,
        work_path: Path | None = None,
    ) -> tuple[ArchiveMetadata, Path]:
        """Create the layer archive specified in this build request."""
        env_path = self.env_path
        if not env_path.exists():
            raise BuildEnvError(
                "Must create environment before attempting to archive it"
            )
        build_metadata = self.build_metadata
        archive_base_path = self.archive_base_path
        built_archive_path = archive_base_path.parent / build_metadata["archive_name"]
        if not self.needs_build:
            # Already built archive looks OK, so just return the same metadata as last build
            _LOG.info(f"Using previously built archive at {str(built_archive_path)!r}")
            previous_metadata = self.archive_metadata
            assert previous_metadata is not None
            return previous_metadata, built_archive_path
        if built_archive_path.exists():
            _LOG.info(f"Removing outdated archive at {str(built_archive_path)!r}")
            built_archive_path.unlink()
        _LOG.info(f"Creating archive for {str(env_path)!r}")
        last_locked = self.env_lock.last_locked
        if work_path is None:
            # /tmp is likely too small for ML/AI environments
            work_path = self.env_path.parent
        archive_path = pack_venv.create_archive(
            env_path,
            archive_base_path,
            clamp_mtime=last_locked,
            work_dir=work_path,
            install_target=build_metadata["install_target"],
            prepare_deployed_env=self._prepare_deployed_env,
        )
        assert built_archive_path == archive_path  # pack_venv ensures this is true
        _LOG.info(f"Created {str(archive_path)!r} from {str(env_path)!r}")

        metadata = ArchiveMetadata(
            archive_size=archive_path.stat().st_size,
            archive_hashes=self._hash_archive(archive_path),
            **build_metadata,
        )
        return metadata, archive_path


class StackPublishingRequest(TypedDict):
    """Inputs to an archive build request for a full stack specification."""

    layers: Mapping[LayerCategories, Sequence[ArchiveBuildMetadata]]


LayeredArchiveMetadata = Mapping[LayerCategories, Sequence[ArchiveMetadata]]


class StackPublishingResult(TypedDict):
    """Archive details for built stack specification (includes build request details)."""

    layers: LayeredArchiveMetadata


class PublishedArchivePaths(NamedTuple):
    """Locations of published metadata and archive files."""

    metadata_path: Path
    snippet_paths: list[Path]
    archive_paths: list[Path]


##########################################################
# Defining and describing locally exported environments
##########################################################


class ExportMetadata(LayerSpecMetadata):
    """Metadata for a locally exported environment."""

    # Exports currently include only the common metadata


@dataclass
class LayerExportRequest:
    """Structured request to locally export an environment."""

    env_name: EnvNameBuild
    env_lock: EnvironmentLock
    env_path: Path
    export_path: Path
    export_metadata: ExportMetadata = field(repr=False)
    needs_export: bool = field(repr=False)
    _prepare_deployed_env: Callable[[Path], None] | None = field(
        repr=False, default=None
    )

    @staticmethod
    def _needs_new_export(
        export_path: Path,
        metadata: ExportMetadata,
        previous_metadata: ExportMetadata | None,
    ) -> bool:
        if not previous_metadata or not export_path.exists():
            return True
        if export_path.name != previous_metadata.get("layer_name"):
            # Previous export produced a different env name, force a new export
            return True
        # Check for any other changes to build input metadata
        for key, value in metadata.items():
            if value != previous_metadata.get(key):
                # Input metadata for the archive build has changed, force a rebuild
                return True
        # Previous export used the same build inputs, so probably doesn't need updating
        return False

    @classmethod
    def define_export(
        cls,
        env_name: EnvNameBuild,
        env_lock: EnvironmentLock,
        source_path: Path,
        output_path: Path,
        previous_metadata: ExportMetadata | None = None,
        force: bool = False,
        prepare_deployed_env: Callable[[Path], None] | None = None,
    ) -> Self:
        """Define a new layer export request for the given environment."""
        # Work out the details of the export request
        deployed_name = env_lock.get_deployed_name(env_name)
        export_path = output_path / deployed_name
        export_metadata = ExportMetadata(
            install_target=deployed_name,
            layer_name=env_name,
            lock_version=env_lock.lock_version,
            locked_at=env_lock.locked_at,
            requirements_hash=env_lock.requirements_hash,
        )
        needs_export = force or cls._needs_new_export(
            export_path, export_metadata, previous_metadata
        )
        env_path = source_path / env_name
        return cls(
            env_name,
            env_lock,
            env_path,
            export_path,
            export_metadata,
            needs_export,
            prepare_deployed_env,
        )

    @staticmethod
    def _run_postinstall(postinstall_path: Path) -> None:
        # Post-installation scripts are required to work even when they're
        # executed with an entirely unrelated Python installation
        command = [sys.executable, "-X", "utf8", "-I", str(postinstall_path)]
        capture_python_output(command)

    def export_environment(self) -> tuple[ExportMetadata, Path]:
        """Locally export the layer environment specified in this export request."""
        env_path = self.env_path
        if not env_path.exists():
            raise BuildEnvError(
                "Must create environment before attempting to export it"
            )
        export_metadata = self.export_metadata
        export_path = self.export_path
        if not self.needs_export:
            # Previous export looks OK, so just return the same metadata as last time
            _LOG.info(f"Using previously exported environment at {str(export_path)!r}")
            return self.export_metadata, export_path
        if export_path.exists():
            _LOG.info(f"Removing outdated environment at {str(export_path)!r}")
            shutil.rmtree(export_path)
        _LOG.info(f"Exporting {str(env_path)!r} to {str(export_path)!r}")

        def _run_postinstall(_export_path: Path, postinstall_path: Path) -> None:
            self._run_postinstall(postinstall_path)

        exported_path = pack_venv.export_venv(
            env_path,
            export_path,
            prepare_deployed_env=self._prepare_deployed_env,
            run_postinstall=_run_postinstall,
        )
        assert self.export_path == exported_path  # pack_venv ensures this is true
        _LOG.info(f"Created {str(export_path)!r} from {str(env_path)!r}")
        return export_metadata, export_path


LayeredExportMetadata = Mapping[LayerCategories, Sequence[ExportMetadata]]


class StackExportRequest(TypedDict):
    """Inputs to an environment export request for a full stack specification."""

    layers: LayeredExportMetadata


class ExportedEnvironmentPaths(NamedTuple):
    """Locations of exported metadata files and deployed environments."""

    metadata_path: Path
    snippet_paths: list[Path]
    env_paths: list[Path]


######################################################
# Building layered environments from specifications
######################################################


class LayerStatus(TypedDict):
    """Summary of a layer environment's current status."""

    name: EnvNameBuild
    install_target: EnvNameDeploy
    has_valid_lock: bool
    selected_operations: list[str] | None
    dependencies: NotRequired[list["LayerStatus"]]


class StackStatus(TypedDict):
    """Summary of a stack build environment's current status."""

    spec_name: str
    runtimes: list[LayerStatus]
    frameworks: list[LayerStatus]
    applications: list[LayerStatus]


def format_env_status(status: LayerStatus) -> str:
    """Format given status as a string."""
    # Valid lock: "env_name [reset-lock lock build publish]"
    # Outdated lock: "*env_name [reset-lock lock build publish]"
    # Standalone function because env status is just a regular dict at runtime
    lock_status = "" if status["has_valid_lock"] else "*"
    env_name = status["name"]
    deployed_name = status["install_target"]
    if cast(str, env_name) != cast(str, deployed_name):
        env_summary = f"{env_name} -> {deployed_name}"
    else:
        env_summary = env_name
    selected_ops = status.get("selected_operations", None)
    op_summary = f" ({', '.join(selected_ops)})" if selected_ops else ""
    return f"{lock_status}{env_summary}{op_summary}"


def _pdm_python_install(target_path: Path, request: str) -> Path | None:
    # from https://github.com/pdm-project/pdm/blob/ce60c223bbf8b5ab2bdb94bf8fa6409b9b16c409/src/pdm/cli/commands/python.py#L122
    # to work around https://github.com/Textualize/rich/issues/3437
    from pdm.core import Core
    from pdm.environments import BareEnvironment
    from pbs_installer import download, get_download_link, install_file
    from pbs_installer._install import THIS_ARCH

    implementation, _, version = request.rpartition("@")
    implementation = implementation.lower() or "cpython"
    version, _, arch = version.partition("-")
    arch = "x86" if arch == "32" else (arch or THIS_ARCH)

    # Weird structure here is to work around https://github.com/python/mypy/issues/12535
    # and https://github.com/frostming/pbs-installer/issues/6
    checked_impl: Literal["cpython", "pypy"] = "cpython"
    if implementation == "pypy":
        checked_impl = "pypy"
    elif implementation != "cpython":
        raise ValueError(f"Unknown interpreter implementation: {implementation}")
    ver, python_file = get_download_link(
        version, implementation=checked_impl, arch=arch, build_dir=False
    )
    destination = target_path / str(ver)
    interpreter = (
        destination / "bin" / "python3"
        if not _WINDOWS_BUILD
        else destination / "python.exe"
    )
    project = Core().create_project()
    env = BareEnvironment(project)
    if not destination.exists() or not interpreter.exists():
        shutil.rmtree(destination, ignore_errors=True)
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile() as tf:
            tf.close()
            with env.session:
                original_filename = download(python_file, tf.name, env.session)
            # Use "tar_filter" if stdlib tar extraction filters are available
            # (they were only added in Python 3.12, so no filtering on 3.11)
            with default_tarfile_filter("tar_filter"):
                install_file(tf.name, destination, original_filename)
    if interpreter.exists():
        # Installation successful, return the path to the installation folder
        return destination
    # Failed to install the interpreter
    return None


def _get_py_scheme_path(category: str, base_path: StrPath, py_version: str) -> Path:
    py_version_short = py_version.rpartition(".")[0]
    scheme_vars = {
        "base": str(base_path),
        "py_version": py_version,
        "py_version_nodot": "".join(py_version_short.split(".")),
        "py_version_short": py_version_short,
    }
    return Path(sysconfig.get_path(category, "venv", vars=scheme_vars))


def _binary_with_extension(name: str) -> str:
    binary_suffix = Path(sys.executable).suffix
    return f"{name}{binary_suffix}"


def get_build_platform() -> TargetPlatform:
    """Report target platform that matches the currently running system."""
    # Currently no need for cross-build support, so always query the running system
    # Examples: win_amd64, linux_x86_64, macosx-10_12-x86_64, macosx-10_12-arm64
    platform_name = sysconfig.get_platform().lower()
    if platform_name.startswith("macosx"):
        platform_os_name, *__, platform_arch = platform_name.split("-")
        if platform_arch.startswith("universal"):
            # Want to handle x86_64 and arm64 separately
            if sys.platform == "win32":
                assert False  # Ensure mypy knows `uname` won't be used on Windows
            platform_arch = os.uname().machine
        platform_name = f"{platform_os_name}_{platform_arch}"
    normalized_name = platform_name.replace("-", "_")
    return TargetPlatform(normalized_name)  # Let ValueError escape


@dataclass
class LayerEnvBase(ABC):
    """Common base class for layer build environment implementations."""

    # Python environment used to run tools like `uv` and `pip`
    tools_python_path: ClassVar[Path] = Path(sys.executable)

    # Specified in concrete subclasses
    kind: ClassVar[LayerVariants]
    category: ClassVar[LayerCategories]

    # Specified on creation
    _env_spec: LayerSpecBase = field(repr=False)
    build_path: Path = field(repr=False)
    requirements_path: Path = field(repr=False)
    source_filter: SourceTreeContentFilter = field(repr=False)
    build_platform: TargetPlatform = field(
        repr=False, default_factory=get_build_platform
    )

    # Derived from build path and spec in __post_init__
    env_path: Path = field(init=False)
    pylib_path: Path = field(init=False, repr=False)
    dynlib_path: Path | None = field(init=False, repr=False)
    executables_path: Path = field(init=False, repr=False)
    python_path: Path = field(init=False, repr=False)
    env_lock: EnvironmentLock = field(init=False, repr=False)
    _build_metadata_path: Path = field(init=False, repr=False)
    _pyproject_path: Path = field(init=False, repr=False)

    # Derived from subclass py_version in __post_init__
    _py_version_info: tuple[str, str] = field(init=False, repr=False)

    # Derived from layer spec in subclass __post_init__
    py_version: str = field(init=False, repr=False)

    # Set in subclass __post_init__, or when build environments are created
    base_python_path: Path | None = field(init=False, repr=False)

    # Operation flags allow for requested commands to be applied only to selected layers
    # Notes:
    #   - the "build if needed" (want_build=None) option is fairly ineffective, since
    #     there are some operations that are always considered "needed" (at least for now)
    #   - there is no "if needed" (want_publish=None) option for archive publication
    want_lock: bool | None = field(
        default=None, init=False, repr=False
    )  # Default: if needed
    want_lock_reset: bool = field(
        default=False, init=False, repr=False
    )  # Default: no reset
    want_build: bool | None = field(
        default=True, init=False, repr=False
    )  # Default: build
    want_publish: bool = field(default=True, init=False, repr=False)  # Default: publish
    # Allow layers to be excluded completely (even from the stack status summary)
    # Excluding a layer also clears the other operation flags
    excluded: bool = field(default=False, init=False, repr=False)

    # State flags used to selectively execute some cleanup operations
    was_created: bool = field(default=False, init=False, repr=False)
    was_locked: bool = field(default=False, init=False, repr=False)
    was_built: bool = field(default=False, init=False, repr=False)

    def _get_py_scheme_path(self, category: str) -> Path:
        return _get_py_scheme_path(category, self.env_path, self.py_version)

    def _get_python_dir_path(self) -> Path:
        # Dedicated method so subclasses can adjust this if needed
        return self._get_py_scheme_path("scripts")

    def __str__(self) -> str:
        return format_env_status(self.get_env_status())

    @staticmethod
    def _op_state_to_str(op_name: str, op_status: bool | None) -> str | None:
        if op_status:
            return op_name
        if op_status is None:
            return f"{op_name}-if-needed"
        return None

    def _get_selected_ops(self) -> list[str]:
        op_states = (
            ("reset-lock", self.want_lock_reset),
            ("lock", self.want_lock),
            ("build", self.want_build),
            ("publish", self.want_publish),
        )
        op_text = [
            self._op_state_to_str(op_name, op_state) for op_name, op_state in op_states
        ]
        return [op for op in op_text if op]

    def get_env_status(self, *, report_ops: bool = True) -> LayerStatus:
        """Get JSON-compatible summary of the environment status and selected operations."""
        # Valid lock: "env_name [reset-lock lock build publish]"
        # Outdated lock: "*env_name [reset-lock lock build publish]"
        env_name = self.env_name
        deployed_name = self.env_lock.get_deployed_name(env_name, placeholder="???")
        selected_ops = self._get_selected_ops() if report_ops else None
        return LayerStatus(
            name=env_name,
            install_target=deployed_name,
            has_valid_lock=self.env_lock.has_valid_lock,
            selected_operations=selected_ops,
        )

    @property
    def env_name(self) -> EnvNameBuild:
        """The name of this environment in the build folder."""
        return self.env_spec.env_name

    @property
    def install_target(self) -> EnvNameDeploy:
        """The environment name used for this layer when deployed."""
        return self.env_lock.get_deployed_name(self.env_spec.env_name)

    @property
    def index_config(self) -> PackageIndexConfig:
        """The package index configuration used to lock and build this layer."""
        return self._env_spec._index_config

    def __post_init__(self) -> None:
        # Concrete subclasses must set the version before finishing the base initialisation
        # Assert its existence here to make failures to do so easier to diagnose
        assert self.py_version is not None, "Subclass failed to set 'py_version'"
        self._py_version_info = cast(
            tuple[str, str], tuple(self.py_version.split(".")[:2])
        )
        build_path = self.build_path
        self.env_path = env_path = build_path / self.env_name
        # Per-environment config and metadata files are stored *adjacent* to the build environments
        # This allows the environment creation to distinguish fresh builds from in-place updates
        # (this would not be possible if tool config files were stored in the build environments)
        self._build_metadata_path = env_path.with_name(
            f"{env_path.name}.last-build.json"
        )
        self._pyproject_path = env_path.with_name(f"{env_path.name}_resolve")

        # Note: purelib and platlib are the same location in virtual environments
        # (even when they have different names, platlib is a symlink to purelib)
        self.pylib_path = self._get_py_scheme_path("purelib")
        self.executables_path = self._get_py_scheme_path("scripts")
        env_python_dir_path = self._get_python_dir_path()
        assert env_python_dir_path.is_absolute()
        env_python_path = env_python_dir_path / _binary_with_extension("python")
        # Symlinked environments may technically vary in whether the link setup is:
        #   python -> ./pythonX -> ./pythonX.Y -> base runtime Python
        # or:
        #   python -> base runtime Python
        #   pythonX -> base runtime Python
        #   pythonX.Y -> base runtime Python
        # or:
        #   python -> ./pythonX.Y
        #   pythonX -> ./pythonX.Y
        #   pythonX.Y -> base runtime Python
        # or:
        #   python -> base runtime Python
        #   pythonX -> ./python
        #   pythonX.Y -> ./python
        #
        # The stdlib venv does the latter for new environments, but this detail isn't
        # formally standardised, so venvstacks ensures it when creating the venvs
        # (this also ensures there is a single intercept point for a script wrapper)
        self.python_path = env_python_path
        if _WINDOWS_BUILD:
            # Windows DLL loading is typically handled via os.add_dll_directory()
            # Intel install some DLLs in a weird spot that needs extra config to handle
            self.dynlib_path = self.env_path / "Library" / "bin"
        else:
            # Allow POSIX extension modules to load shared libraries from lower layers
            self.dynlib_path = self.env_path / "share" / "venv" / "dynlib"
        self.env_lock = EnvironmentLock(
            self.requirements_path,
            (*self.env_spec.requirements,),
            self._get_other_lock_inputs(),
            self._get_lock_version_inputs(),
            self.env_spec.versioned,
        )
        # Ensure symlinks in the environment paths aren't inadvertently resolved
        assert self.pylib_path.relative_to(self.env_path)
        assert self.executables_path.relative_to(self.env_path)
        assert self.dynlib_path.relative_to(self.env_path)
        # Adjust op selections based on the target platform
        targets_platform = self.targets_platform()
        self.want_build = self.want_build and targets_platform
        self.want_publish = self.want_publish and targets_platform

    def _get_other_lock_inputs(self) -> tuple[str, ...]:
        # TODO: consider incorporating the uv config settings into the implicit layer versioning
        return (f"py_version={'.'.join(self._py_version_info)}",)

    def _get_lock_version_inputs(self) -> tuple[str, ...]:
        return (
            f"env_name={self.env_name}",
            f"is_versioned_layer={self.env_spec.versioned}",
        )

    @property
    def env_spec(self) -> LayerSpecBase:
        """Layer specification for this environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        return self._env_spec

    @abstractmethod
    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        raise NotImplementedError

    def get_relative_build_path(self, build_env_path: Path) -> Path:
        """Get relative build location for a build path (includes layer's build name)."""
        return build_env_path.relative_to(self.build_path)

    def get_deployed_path(self, build_env_path: Path) -> Path:
        """Get relative deployment location for a build path (includes layer's deployed name)."""
        env_deployed_path = Path(self.install_target)
        relative_path = build_env_path.relative_to(self.env_path)
        return env_deployed_path / relative_path

    def _relative_to_env(self, relative_build_path: Path) -> Path:
        # Input path is relative to the base of the build directory
        # Output path is relative to the base of the environment
        # Note: we avoid `walk_up=True` here, firstly to maintain
        #       Python 3.11 compatibility, but also to limit the
        #       the relative paths to *peer* environments, rather
        #       than all potentially valid relative path calculations
        if relative_build_path.is_absolute():
            self._fail_build(f"{relative_build_path} is not a relative path")
        if relative_build_path.parts[0] == self.env_name:
            # Emit internally relative path
            return Path(*relative_build_path.parts[1:])
        # Emit relative reference to peer environment
        return Path("..", *relative_build_path.parts)

    def _relative_internal_path(self, absolute_build_path: Path) -> Path:
        # Input path is an absolute path inside the environment
        # Output path is relative to the base of the environment
        assert absolute_build_path.is_absolute()
        return absolute_build_path.relative_to(self.env_path)

    def _get_relative_deployed_base_python(self) -> Path | None:
        raise NotImplementedError

    def _get_deployed_config(
        self,
        pylib_dirs: Iterable[str],
        dynlib_dirs: Iterable[str],
    ) -> postinstall.LayerConfig:
        # Helper for subclass get_deployed_config implementations
        base_python_path = self._get_relative_deployed_base_python()
        if base_python_path is None:
            self._fail_build("Cannot get deployment config for unlinked layer")

        return postinstall.LayerConfig(
            python=str(self._relative_internal_path(self.python_path)),
            py_version=self.py_version,
            base_python=str(base_python_path),
            site_dir=str(self._relative_internal_path(self.pylib_path)),
            pylib_dirs=[str(self._relative_to_env(Path(d))) for d in pylib_dirs],
            dynlib_dirs=[str(self._relative_to_env(Path(d))) for d in dynlib_dirs],
        )

    def _write_deployed_config(self) -> None:
        # This is written as part of creating/updating the build environments
        config_path = self.env_path / postinstall.DEPLOYED_LAYER_CONFIG
        _LOG.debug(f"Generating {str(config_path)!r}...")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(config_path, self.get_deployed_config())

    def _fail_build(self, message: str, exc: Exception | None = None) -> NoReturn:
        attributed_message = f"Layer {self.env_name}: {message}"
        build_exc = BuildEnvError(attributed_message)
        if exc is not None:
            raise build_exc from exc
        raise build_exc

    def targets_platform(
        self, target_platform: str | TargetPlatform | None = None
    ) -> bool:
        """Returns `True` if the layer will be built for the given target platform.

        If no target platform is given, the current build platform is assumed.
        """
        if target_platform is None:
            target_platform = self.build_platform
        return self.env_spec.targets_platform(target_platform)

    def select_operations(
        self,
        lock: bool | None = False,
        build: bool | None = True,
        publish: bool = True,
        *,
        reset_lock: bool = False,
    ) -> None:
        """Enable the selected operations for this environment."""
        targets_platform = self.targets_platform()
        self.excluded = False
        # Locking is cross-platform
        self.want_lock = lock
        self.want_lock_reset = reset_lock
        # Building & publishing artifacts is platform specific
        self.want_build = build and targets_platform
        self.want_publish = publish and targets_platform
        # Also reset operation state tracking
        self.was_created = False
        self.was_built = False

    def exclude_layer(self) -> None:
        """Exclude the layer from all operations (including stack status reporting)."""
        self.select_operations(False, False, False)
        self.excluded = True

    def _write_pyproject_file(
        self, requirements_input_path: Path
    ) -> Sequence[LockedPackage]:
        # Layer config to be passed in:
        # - declared requirements -> dependencies
        # - lower layer constraints -> tool.uv.constraint-dependencies
        # - package index overrides -> tool.uv.sources
        # - index definitions & priority overrides -> tool.uv.index
        # Common config is also included here as attempting to pass it in via
        # `--config-file` means `uv` won't reliably read the `[tool.uv]` table
        # Returns the list of pinned constraints derived from lower layers
        dependencies = _read_flat_reqs(requirements_input_path)
        constraint_paths = self.get_constraint_paths()
        unique_constraints = set[LockedPackage]()
        for constraint_path in constraint_paths:
            unique_constraints.update(
                _iter_pylock_packages_from_file(constraint_path, exclude_shared=True)
            )
        pinned_constraints = sorted(unique_constraints)
        env_spec = self.env_spec
        index_config = env_spec._index_config
        common_indexes = index_config._common_indexes
        named_indexes = index_config._named_indexes
        priority_names = env_spec.priority_indexes
        # Index names are checked against the known index names at spec definition time,
        # so there's no specific error handling for failed lookups below
        if not priority_names:
            priority_indexes = []
        else:
            priority_indexes = [named_indexes[name].copy() for name in priority_names]
            for p in priority_indexes:
                p["explicit"] = False
        other_index_names = set(env_spec.package_indexes.values())
        other_index_names.difference_update(priority_names)
        referenced_indexes = [named_indexes[name] for name in other_index_names]
        explicit_indexes = [x for x in referenced_indexes if x.get("explicit")]
        other_indexes = [
            x for x in common_indexes if x.get("name") not in priority_names
        ]
        layer_indexes = [*priority_indexes, *explicit_indexes, *other_indexes]
        package_indexes = index_config._common_package_indexes.copy()
        package_indexes.update(env_spec.package_indexes)
        package_sources = {pkg: {"index": idx} for pkg, idx in package_indexes.items()}
        uv_tool_config = index_config._common_config_uv.copy()
        uv_constraints = [str(pkg) for pkg in pinned_constraints]
        uv_tool_config["constraint-dependencies"] = uv_constraints
        if layer_indexes:
            uv_tool_config["index"] = layer_indexes
        if package_sources:
            uv_tool_config["sources"] = package_sources
        layer_project_name = re.sub("[^a-zA-Z0-9._-]", "-", self.env_name)
        py_version_short = self.py_version.rpartition(".")[0]
        pyproject_config = {
            "project": {
                "name": canonicalize_name(layer_project_name),
                "version": "0",
                "dependencies": dependencies,
                "requires-python": f"=={py_version_short}.*",
            },
            "tool": {"uv": uv_tool_config},
        }
        pyproject_path = self._pyproject_path
        pyproject_path.mkdir(exist_ok=True)
        pyproject_toml_path = pyproject_path / "pyproject.toml"
        with pyproject_toml_path.open("w") as f:
            tomlkit.dump(pyproject_config, f)
        return pinned_constraints

    def _create_environment(
        self, *, clean: bool = False, lock_only: bool = False
    ) -> None:
        env_path = self.env_path
        env_updated = False
        create_env = True
        if not env_path.exists():
            _LOG.info(f"{str(env_path)!r} does not exist, creating...")
        elif clean:
            _LOG.info(f"{str(env_path)!r} exists, replacing...")
        else:
            if self.want_build or self.was_created or self.needs_build():
                # Run the update if requested, if the env was created earlier in the build,
                # or if the build env is otherwise outdated
                _LOG.info(f"{str(env_path)!r} exists, updating...")
                self._update_existing_environment(lock_only=lock_only)
                env_updated = True
            else:
                _LOG.info(f"{str(env_path)!r} exists, reusing without updating...")
            create_env = False
        if create_env:
            self._create_new_environment(lock_only=lock_only)
        env_lock = self.env_lock
        if not env_lock.versioned or env_lock.has_valid_lock:
            # Unversioned deployed config can be written regardless of the lock status
            # Versioned layers need an up to date version to write the deployed config
            self._write_deployed_config()
        self.was_created = create_env
        self.was_built = was_built = not lock_only and (create_env or env_updated)
        if was_built:
            self._write_last_build_metadata()

    def create_environment(self, clean: bool = False) -> None:
        """Create or update specified environment. Returns True if env is new or updated."""
        self._create_environment(clean=clean)
        self._ensure_portability()

    def report_python_site_details(self) -> subprocess.CompletedProcess[str]:
        """Print the results of running ``python -m site`` in this environment."""
        # TODO: adjust how the Python command is executed based on UI verbosity settings
        _UI.echo(f"Reporting environment details for {str(self.env_path)!r}")
        command = [
            str(self.python_path),
            "-X",
            "utf8",
            "-Im",
            "site",
        ]
        return run_python_command(command)

    def _run_uv(
        self, cmd: str, cmd_args: list[str], **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        # Always run `uv` via `python -Im` so it gets a valid default interpreter to use
        command = [
            str(self.tools_python_path),
            "-X",
            "utf8",
            "-Im",
            "uv",
            cmd,
            *cmd_args,
            "--no-managed-python",
        ]
        return run_python_command(command, **kwds)

    def _run_uv_pip(
        self, cmd_args: list[str], **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        return self._run_uv("pip", cmd_args, **kwds)

    def _run_uv_lock(
        self,
        pyproject_path: StrPath,
    ) -> subprocess.CompletedProcess[str]:
        uv_lock_args = [
            "--project",
            str(pyproject_path),
            "--python",
            str(self.base_python_path),
            *self.index_config._get_uv_lock_args(self.build_path),
            "--upgrade",  # ignore any uv.lock contents from a previous local lock run
            "--quiet",
            "--no-color",
        ]
        _LOG.debug((Path(pyproject_path) / "pyproject.toml").read_text("utf-8"))
        try:
            return self._run_uv("lock", uv_lock_args)
        except subprocess.CalledProcessError as exc:
            raise LayerLockError(f"Failed to lock layer {self.env_name!r}") from exc

    def _run_uv_export_requirements(
        self,
        requirements_path: StrPath,
        pyproject_path: StrPath,
    ) -> subprocess.CompletedProcess[str]:
        uv_export_args = [
            "-o",
            os.fspath(requirements_path),
            "--project",
            str(pyproject_path),
            "--locked",
            "--format",
            "pylock.toml",
            "--no-header",
            "--no-emit-project",
            "--python",
            str(self.base_python_path),
            *self.index_config._get_uv_export_args(self.build_path),
            "--quiet",
            "--no-color",
            "--no-annotate",  # Annotations include file paths, creating portability problems
        ]
        try:
            return self._run_uv("export", uv_export_args)
        except subprocess.CalledProcessError as exc:
            raise LayerLockError(
                f"Failed to generate pylock.toml for layer {self.env_name!r}"
            ) from exc

    def _run_uv_pip_install(
        self,
        requirements_path: StrPath,
    ) -> subprocess.CompletedProcess[str]:
        # No need to pass in the layer project config,
        # as everything is captured in the pylock.toml file
        uv_pip_args = [
            "install",
            "--python",
            str(self.python_path),
            *self.index_config._get_uv_pip_install_args(self.build_path),
            "--quiet",
            "--no-color",
        ]
        uv_pip_args.extend(("-r", os.fspath(requirements_path)))
        try:
            return self._run_uv_pip(uv_pip_args)
        except subprocess.CalledProcessError as exc:
            raise LayerInstallationError(
                f"Failed to install into layer {self.env_name!r}"
            ) from exc

    def get_constraint_paths(self) -> list[Path]:
        """Get the lower level layer constraints imposed on this environment."""
        # No constraints files by default, subclasses override as necessary
        return []

    def needs_lock(self, lock_time: datetime | None = None) -> bool:
        """Returns true if this environment needs to be locked."""
        if self.want_lock is False:
            # Locking step has been explicitly disabled, so override the check
            # Later process steps will fail if the lock file is needed but missing
            # TODO?: emit a runtime warning about possible inconsistencies
            return False
        if self.want_lock_reset and not self.was_locked:
            # If the lock is still to be reset, then locking is needed unless
            # the lock operation has been explicitly disabled
            return True
        env_lock = self.env_lock
        if not env_lock.has_valid_lock:
            # No valid metadata -> locking is needed
            return True
        # Otherwise, locking is only needed if a specific lock time has been
        # requested and the recorded lock time doesn't match
        if lock_time is None:
            return False
        return lock_time != env_lock.locked_at

    def _get_build_metadata(self) -> Mapping[str, Any]:
        env_name = self.env_name
        env_lock = self.env_lock
        layer_details = LayerSpecMetadata(
            layer_name=env_name,
            install_target=env_lock.get_deployed_name(env_name),
            requirements_hash=env_lock.requirements_hash,
            lock_version=env_lock.lock_version,
            locked_at=env_lock.locked_at,
        )
        self._update_output_metadata(layer_details)
        return {
            "layer_spec": self.env_spec.to_dict(),
            "layer_details": layer_details,
        }

    def _load_last_build_metadata(self) -> Any:
        build_metadata_path = self._build_metadata_path
        if not build_metadata_path.exists():
            return None
        return json.loads(build_metadata_path.read_text(encoding="utf-8"))

    def _write_last_build_metadata(self) -> None:
        _write_json(self._build_metadata_path, self._get_build_metadata())

    def needs_build(self) -> bool:
        """Returns true if the build environment needs to be created or updated."""
        if self.want_build is False:
            # Building step has been explicitly disabled, so override the check
            # Later process steps will fail if the environment is needed but missing
            # TODO?: emit a runtime warning about possible inconsistencies
            return False
        if not self.env_path.exists():
            # Build env is necessarily outdated if it doesn't exist yet
            return True
        last_build_metadata = self._load_last_build_metadata()
        if last_build_metadata is None:
            # Build env is outdated if there is no recorded build metadata
            return True
        # Build env is outdated if the metadata has changed since the last build
        return bool(self._get_build_metadata() != last_build_metadata)

    def _write_package_summary(self) -> None:
        # The requirements are read from disk rather than passed in so existing lock files
        # can be summarised, and to ensure no extra info is being injected into the summaries
        requirements_path = self.requirements_path
        all_required_packages = sorted(
            _iter_pylock_packages_from_file(requirements_path)
        )
        required_packages: list[str] = []
        shared_packages: list[str] = []
        # Omit the shared requirements from the list of required packages
        # The components from lower layers are marked as shared if they're either
        # installed unconditionally on all platforms, or if their environment marker
        # matches the environment marker for the package in the current layer
        for pkg in all_required_packages:
            if _SHARED_PKG_MARKER in pkg.marker:
                # Only record the unconditional req in the summary
                shared_packages.append(f"{pkg.name}=={pkg.version}")
                continue
            required_packages.append(str(pkg))
        summary_lines = [
            f"# Package summary for {self.env_name}",
            "#     Auto-generated by venvstacks (DO NOT EDIT)",
        ]
        summary_lines.extend(required_packages)
        summary_lines.append("")
        if shared_packages:
            summary_lines.append("# Shared packages inherited from other layers")
            summary_lines.extend(sorted(shared_packages))
            summary_lines.append("")

        summary_fname = f"packages-{self.env_name}.txt"
        summary_path = requirements_path.with_name(summary_fname)
        summary_path.write_text(
            "\n".join(summary_lines), encoding="utf-8", newline="\n"
        )

    def _iter_dependencies(self) -> Iterator["LayerEnvBase"]:
        return iter(())

    def get_lock_inputs(self) -> tuple[Path, Path, Sequence[LockedPackage]]:
        """Ensure the inputs needed to lock this environment are defined and valid."""
        unlocked_deps = [
            env.env_name for env in self._iter_dependencies() if env.needs_lock()
        ]
        if unlocked_deps:
            self._fail_build(f"Cannot lock with unlocked dependencies: {unlocked_deps}")
        declared_requirements_path = self.env_lock.prepare_lock_inputs()
        pinned_constraints = self._write_pyproject_file(declared_requirements_path)
        return (
            self.requirements_path,
            self._pyproject_path,
            pinned_constraints,
        )

    def lock_requirements(self, lock_time: datetime | None = None) -> EnvironmentLock:
        """Transitively lock the requirements for this environment."""
        pylock_path, pyproject_path, pinned_constraints = self.get_lock_inputs()
        # Packages provided by lower layers will be excluded via their environment markers
        if not self.want_lock and not self.needs_lock(lock_time):
            _LOG.info(f"Using existing lock for {self.env_name} ({str(pylock_path)!r})")
            # Ensure summary files are always emitted, even for existing layer locks
            self._write_package_summary()
            return self.env_lock
        if self.want_lock_reset and pylock_path.exists():
            _LOG.info(
                f"Resetting lock for {self.env_name} (removing {str(pylock_path)!r})"
            )
            pylock_path.unlink()
        want_full_lock = (
            self.want_lock or self.want_lock_reset or self.env_lock.needs_full_lock
        )
        if want_full_lock:
            _LOG.info(f"Locking {self.env_name} (generating {str(pylock_path)!r})")
            self._run_uv_lock(pyproject_path)
            self._run_uv_export_requirements(pylock_path, pyproject_path)
            if not pylock_path.exists():
                self._fail_build(f"Failed to generate {str(pylock_path)!r}")
            # We want to amend the lockfile to skip installing packages provided by lower layers
            # We also want to remove the default header comment and instead add our own
            raw_pylock_text = pylock_path.read_text("utf-8")
            pylock_dict = tomlkit.parse(raw_pylock_text).unwrap()
            raw_pkg: dict[str, Any]
            if pinned_constraints:
                # Edit the environment markers for packages provided by lower layers
                # The components from lower layers are marked as shared if they're either
                # installed unconditionally on all platforms, or if their environment marker
                # matches the environment marker for the package in the current layer
                available_packages = set(pinned_constraints)
                exclusion_clause = "sys_platform == 'from_lower_layer'"
                for raw_pkg in pylock_dict.get("packages", ()):
                    pkg = LockedPackage.from_dict(raw_pkg)
                    unconditional_req = LockedPackage(pkg.name, pkg.version, "", "", [])
                    if (
                        pkg in available_packages
                        or unconditional_req in available_packages
                    ):
                        # Add an unmatchable environment marker to skip package installation
                        pkg_marker = pkg.marker
                        if pkg_marker:
                            raw_pkg["marker"] = f"({pkg_marker}) and {exclusion_clause}"
                        else:
                            raw_pkg["marker"] = exclusion_clause
                        # In both cases, clear the "wheels" and "index" metadata for the package
                        raw_pkg.pop("index", "")
                        raw_pkg.pop("wheel", "")
            # Edit any absolute file paths (whether)
            pylock_dir_path = pylock_path.parent
            for raw_pkg in pylock_dict.get("packages", ()):
                for raw_whl in raw_pkg.get("wheels", ()):
                    _name, local_path = _extract_wheel_details(raw_whl)
                    if local_path is not None:
                        if local_path.is_absolute():
                            # Local paths may technically be anywhere on the system
                            # Making them relative is intended for use cases where
                            # they're stored in a consistent location relative to
                            # the layer lock files (e.g in Git LFS)
                            # We avoid `walk_up=True` to maintain Python 3.11 compatibility
                            try:
                                common_prefix = os.path.commonpath(
                                    (local_path, pylock_dir_path)
                                )
                            except ValueError as path_exc:
                                msg = f"Unable to locate {str(local_path)!r} relative to {str(pylock_dir_path)!r}"
                                self._fail_build(msg, path_exc)
                            common_path = Path(common_prefix)
                            relative_local_path = local_path.relative_to(common_path)
                            relative_pylock_dir_path = pylock_dir_path.relative_to(
                                common_path
                            )
                            relative_prefix = [".."] * len(
                                relative_pylock_dir_path.parts
                            )
                            relative_path = Path(*relative_prefix) / relative_local_path
                            raw_whl.pop("url", None)
                            raw_whl["path"] = str(relative_path)
            amended_pylock_text = tomlkit.dumps(pylock_dict)
            pylock_text_with_header = "\n".join(
                [
                    f"# Locked requirements for {self.env_name} (DO NOT EDIT)",
                    "#     Auto-generated by venvstacks with the following command:",
                    f"#         {Path(sys.executable).name} -Im {__package__} lock",
                    amended_pylock_text,
                ]
            )
            # Save lock files with LF line endings, even on Windows
            pylock_path.write_text(pylock_text_with_header, "utf-8", newline="\n")
        else:
            _LOG.info(f"Incrementing layer version for {self.env_name}")
            # Actually doing the update is handled in `update_lock_metadata`
        self._write_package_summary()
        if self.env_lock.update_lock_metadata(lock_time):
            _LOG.info(f"  Environment lock time set: {self.env_lock.locked_at!r}")
        assert self.env_lock.has_valid_lock
        if self.env_lock.versioned:
            # Layer version may have changed -> rewrite the deployment config
            self._write_deployed_config()
        self.was_locked = True
        assert not self.needs_lock()
        return self.env_lock

    def get_install_inputs(self) -> tuple[Path,]:
        """Ensure the inputs needed to install into this environment are defined and valid."""
        if not self.env_lock.has_valid_lock:
            lock_diagnostics = _format_json(self.env_lock.get_diagnostics())
            failure_details = [
                "Environment must be locked before installing dependencies",
                "Invalid lock details:",
                lock_diagnostics,
            ]
            self._fail_build("\n".join(failure_details))
        requirements_path, _pyproject_path, _pinned_constraints = self.get_lock_inputs()
        return (requirements_path,)

    def install_requirements(self) -> subprocess.CompletedProcess[str]:
        """Install the locked layer requirements into this environment.

        Note: assumes dependencies have already been installed into linked layers.
        """
        # Run a pip dependency upgrade inside the target environment
        install_result = self._run_uv_pip_install(*self.get_install_inputs())
        if not _WINDOWS_BUILD:
            symlink_dir_path = self.dynlib_path
            if symlink_dir_path is None:
                self._fail_build(
                    "Environments must be linked before installing dependencies"
                )
            libraries_to_link, ambiguous_link_targets = map_symlink_targets(
                symlink_dir_path,
                find_shared_libraries(
                    self._py_version_info,
                    self.pylib_path,
                    excluded=self.env_spec.dynlib_exclude,
                ),
            )
            if ambiguous_link_targets:
                err_lines = [
                    "Ambiguous dynamic library link targets:",
                    "",
                ]
                for symlink_path, so_paths in ambiguous_link_targets.items():
                    symlink_info = str(self.get_relative_build_path(symlink_path))
                    so_info = sorted(
                        str(self.get_relative_build_path(so_path))
                        for so_path in so_paths
                    )
                    err_lines.append(f"  {symlink_info} => {so_info}?")
                err_lines.extend(
                    [
                        "",
                        "Set `dynlib_exclude` in the layer definition to resolve this ambiguity.",
                    ]
                )
                self._fail_build("\n".join(err_lines))
            if symlink_dir_path.exists():
                for existing_path in symlink_dir_path.iterdir():
                    # Ensure only currently valid symlinks are included in the layer archive
                    existing_path.unlink()
            for symlink_path, dynlib_path in libraries_to_link.items():
                if symlink_path.exists():
                    if not symlink_path.is_symlink():
                        self._fail_build(
                            f"{str(symlink_path)!r} already exists and is not a symlink"
                        )
                    target_path = symlink_path.readlink()
                    abs_target_path = symlink_path.parent / target_path
                    if not abs_target_path.samefile(dynlib_path):
                        symlink_info = str(self.get_relative_build_path(symlink_path))
                        existing_info = str(
                            self.get_relative_build_path(abs_target_path)
                        )
                        conflicting_info = str(
                            self.get_relative_build_path(dynlib_path)
                        )
                        self._fail_build(
                            f"{symlink_info!r} already exists, "
                            f"but links to {existing_info!r}, not {conflicting_info!r}.\n"
                            "Cleaning the build environment may resolve this conflict."
                        )
                else:
                    symlink_path.parent.mkdir(exist_ok=True, parents=True)
                    symlink_path.symlink_to(dynlib_path)
        return install_result

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        if not lock_only:
            self.install_requirements()

    @abstractmethod
    def _create_new_environment(self, *, lock_only: bool = False) -> None:
        raise NotImplementedError

    def _clean_environment(self) -> None:
        self._build_metadata_path.unlink(missing_ok=True)
        env_path = self.env_path
        if env_path.exists():
            shutil.rmtree(env_path)

    def _update_record_file(self, record_path: Path, removed_paths: set[Path]) -> bool:
        entries = parse_record_file(
            record_path.read_text(encoding="utf-8").splitlines()
        )
        included: list[tuple[str, str, str]] = []
        update_needed = False
        for entry in entries:
            entry_path = _resolve_lexical_path(entry[0], self.pylib_path)
            if entry_path in removed_paths:
                update_needed = True
                continue
            included.append(entry)
        if not update_needed:
            # No files excluded -> existing RECORD file can be left alone
            return False
        # Rewrite the RECORD file without the removed entries
        with record_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f, delimiter=",", quotechar='"', lineterminator="\n")
            for entry in included:
                writer.writerow(entry)
        return True

    def _ensure_portability(self) -> None:
        # Wrapper and activation scripts are not used on deployment targets,
        # so drop them entirely rather than making them portable
        removed_paths: set[Path] = set()
        for item in self.executables_path.iterdir():
            if item.is_dir():
                _LOG.debug(f"    Dropping directory {str(item)!r}")
                shutil.rmtree(item)
            elif not item.name.lower().startswith("python"):
                _LOG.debug(f"    Dropping potentially non-portable file {str(item)!r}")
                item.unlink()
            else:
                continue
            removed_paths.add(item)
        if removed_paths:
            # Also remove any dropped files from installation RECORD files
            for record_path in self.pylib_path.rglob("RECORD"):
                if self._update_record_file(record_path, removed_paths):
                    _LOG.debug(f"    Removed dropped files from {str(record_path)!r}")
        # Symlinks within the build folder should be relative
        # Symlinks outside the build folder shouldn't exist
        build_path = self.build_path
        relative, external = pack_venv.convert_symlinks(self.env_path, build_path)
        if relative:
            msg_lines = ["Converted absolute internal symlinks to relative symlinks:\n"]
            for file_path, target_path in relative:
                link_info = f"{str(file_path)!r} -> {str(target_path)!r}"
                msg_lines.append(f"  {link_info}")
            _LOG.debug("\n".join(msg_lines))
        if external:
            msg_lines = ["Converted absolute external symlinks to hard links:\n"]
            for file_path, target_path in external:
                link_info = f"{str(file_path)!r} -> {str(target_path)!r}"
                msg_lines.append(f"  {link_info}")
            _LOG.debug("\n".join(msg_lines))

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        # Hook for subclasses to optionally override
        assert metadata is not None

    def _prepare_deployed_env(self, deployed_env_path: Path) -> None:
        # Hook for subclasses to optionally override
        assert deployed_env_path.is_absolute()

    def define_archive_build(
        self,
        output_path: Path,
        target_platform: str,
        tag_output: bool = False,
        previous_metadata: ArchiveMetadata | None = None,
        force: bool = False,
    ) -> ArchiveBuildRequest:
        """Define an archive build request for this environment."""
        request = ArchiveBuildRequest.define_build(
            self.env_name,
            self.env_lock,
            self.build_path,
            output_path,
            target_platform,
            tag_output,
            previous_metadata,
            force,
            self._prepare_deployed_env,
        )
        self._update_output_metadata(request.build_metadata)
        return request

    def request_export(
        self,
        output_path: Path,
        previous_metadata: ExportMetadata | None = None,
        force: bool = False,
    ) -> LayerExportRequest:
        """Define a local export request for this environment."""
        request = LayerExportRequest.define_export(
            self.env_name,
            self.env_lock,
            self.build_path,
            output_path,
            previous_metadata,
            force,
            self._prepare_deployed_env,
        )
        self._update_output_metadata(request.export_metadata)
        return request


class RuntimeEnv(LayerEnvBase):
    """Base runtime layer build environment."""

    kind = LayerVariants.RUNTIME
    category = LayerCategories.RUNTIMES

    def _get_python_dir_path(self) -> Path:
        if _WINDOWS_BUILD:
            # python-build-standalone Windows build doesn't put the binary in `Scripts`
            return self.env_path
        return super()._get_python_dir_path()

    def __post_init__(self) -> None:
        # Ensure Python version is set before finishing base class initialisation
        self.py_version = self.env_spec.py_version
        super().__post_init__()
        # Runtimes are their own base Python
        self.base_python_path = self.python_path

    @property
    def env_spec(self) -> RuntimeSpec:
        """Layer specification for this runtime build environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, RuntimeSpec)
        return self._env_spec

    def _get_relative_deployed_base_python(self) -> Path:
        base_python_path = self.base_python_path
        assert base_python_path is not None
        return Path(self._relative_internal_path(base_python_path))

    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        return self._get_deployed_config([], [])

    def _remove_pip(self) -> subprocess.CompletedProcess[str] | None:
        to_be_checked = ["pip", "wheel", "setuptools"]
        to_be_removed = []
        for pylib in to_be_checked:
            if (self.pylib_path / pylib).exists():
                to_be_removed.append(pylib)
        if not to_be_removed:
            return None
        pip_args = [
            "uninstall",
            "--python",
            str(self.python_path),
            *to_be_removed,
        ]
        # "uv pip uninstall" sends routine output to stderr for not-readily-apparent reasons...
        return self._run_uv_pip(pip_args, stderr=subprocess.STDOUT)

    def _create_new_environment(self, *, lock_only: bool = False) -> None:
        self._clean_environment()
        python_runtime = self.env_spec.python_implementation
        install_path = _pdm_python_install(self.build_path, python_runtime)
        if install_path is None:
            self._fail_build(f"Failed to install {python_runtime}")
        shutil.move(install_path, self.env_path)
        # No build step needs `pip` to be installed in the target environment,
        # and we don't want to ship it unless explicitly requested to do so
        # as a declared dependency of an included component
        self._remove_pip()
        _fs_sync()
        if not lock_only:
            _LOG.debug(
                f"Using {str(self.python_path)!r} as runtime environment layer in {self}"
            )
            self.install_requirements()

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        super()._update_output_metadata(metadata)
        # This *is* a runtime layer, so it needs to be updated on maintenance releases
        metadata["runtime_layer"] = self.install_target
        metadata["python_implementation"] = self.env_spec.python_implementation
        metadata["bound_to_implementation"] = True

    def create_build_environment(self, *, clean: bool = False) -> None:
        """Create or update runtime build environment. Returns True if env is new or updated."""
        super()._create_environment(clean=clean, lock_only=True)


class LayeredEnvBase(LayerEnvBase):
    """Common base class for framework and application layer build environments."""

    base_runtime: RuntimeEnv | None = field(init=False, repr=False)
    linked_constraints_paths: list[Path] = field(init=False, repr=False)
    linked_frameworks: list["FrameworkEnv"] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Ensure Python version is set before finishing base class initialisation
        self.py_version = self.env_spec.runtime.py_version
        super().__post_init__()
        # Base runtime env will be linked when creating the build environments
        self.base_runtime = None
        self.linked_constraints_paths = []
        self.linked_frameworks = []

    def get_env_status(
        self, *, report_ops: bool = True, include_deps: bool = False
    ) -> LayerStatus:
        """Get JSON-compatible summary of the environment status and selected operations."""
        # Deps are omitted by default for consistency with the base method behaviour
        env_status = super().get_env_status(report_ops=report_ops)
        if include_deps:
            dep_statuses = [
                dep.get_env_status(report_ops=False)
                for dep in self._iter_dependencies()
            ]
            env_status["dependencies"] = dep_statuses
        return env_status

    @property
    def env_spec(self) -> LayeredSpecBase:
        """Layer specification for this environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, LayeredSpecBase)
        return self._env_spec

    def _iter_dependencies(self) -> Iterator[LayerEnvBase]:
        # Linked frameworks are emitted before the base runtime layer
        for fw_env in self.linked_frameworks:
            yield fw_env
        # This is only ever invoked *after* the environment has been linked
        runtime_env = self.base_runtime
        assert runtime_env is not None
        yield runtime_env

    def _iter_build_pylib_dirs(self) -> Iterator[str]:
        for env in self._iter_dependencies():
            yield str(self.get_relative_build_path(env.pylib_path))

    def _iter_build_dynlib_dirs(self) -> Iterator[str]:
        for env in self._iter_dependencies():
            dynlib_path = env.dynlib_path
            if dynlib_path is not None:
                yield str(self.get_relative_build_path(dynlib_path))

    def _iter_deployed_pylib_dirs(self) -> Iterator[str]:
        for env in self._iter_dependencies():
            yield str(env.get_deployed_path(env.pylib_path))

    def _iter_deployed_dynlib_dirs(self) -> Iterator[str]:
        for env in self._iter_dependencies():
            dynlib_path = env.dynlib_path
            if dynlib_path is not None:
                yield str(env.get_deployed_path(dynlib_path))

    def link_base_runtime(self, runtime: RuntimeEnv) -> None:
        """Link this layered environment to its base runtime environment."""
        if self.base_runtime is not None:
            self._fail_build(f"Layered environment base runtime already linked {self}")
        # Link the runtime environment
        self.base_runtime = runtime
        # Link executable paths
        base_python_path = runtime.python_path
        assert base_python_path.is_absolute()
        assert not base_python_path.is_relative_to(self.env_path)
        self.base_python_path = base_python_path
        # Link runtime layer dependency constraints
        if self.linked_constraints_paths:
            self._fail_build("Layered environment constraint paths already set")
        self.linked_constraints_paths[:] = [runtime.requirements_path]
        self.env_lock.append_other_input(runtime.env_name)
        _LOG.debug(f"Linked {self}")

    def link_layered_environments(
        self,
        runtime: RuntimeEnv,
        frameworks: Mapping[LayerBaseName, "FrameworkEnv"],
    ) -> None:
        """Link this application build environment with its runtime and framework layers."""
        self.link_base_runtime(runtime)
        constraints_paths = self.linked_constraints_paths
        if not constraints_paths:
            self._fail_build("Failed to add base environment constraints path")
        # The runtime site-packages folder is added here rather than via pyvenv.cfg
        # to ensure it appears in sys.path after the framework site-packages folders
        fw_env_names: list[str] = []
        fw_envs = self.linked_frameworks
        if fw_envs:
            self._fail_build("Layered application environment already linked")
        for env_spec in self.env_spec.frameworks:
            fw_env_name = env_spec.name
            fw_env_names.append(fw_env_name)
            fw_env = frameworks[fw_env_name]
            fw_envs.append(fw_env)
            constraints_paths.append(fw_env.requirements_path)
        self.env_lock.extend_other_inputs(fw_env_names)
        # Invalidate this environment's lock if any layer it depends on needs locking
        for env in self._iter_dependencies():
            if env.needs_lock():
                self.env_lock.invalidate_lock()
                break

    def _get_relative_deployed_base_python(self) -> Path | None:
        base_runtime = self.base_runtime
        if base_runtime is None:
            return None
        base_python_path = base_runtime.base_python_path
        assert base_python_path is not None
        assert base_python_path == self.base_python_path
        deployed_base_runtime = base_runtime.install_target
        relative_base_python = base_python_path.relative_to(base_runtime.env_path)
        return Path("..", deployed_base_runtime, relative_base_python)

    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        return self._get_deployed_config(
            self._iter_deployed_pylib_dirs(), self._iter_deployed_dynlib_dirs()
        )

    def get_constraint_paths(self) -> list[Path]:
        """Get the lower level layer constraints imposed on this environment."""
        return self.linked_constraints_paths

    def _resolve_base_python(
        self, deployed_path: Path | None = None
    ) -> tuple[Path, Path]:
        if deployed_path is None:
            # pack_venv will make the generated base Python link relative
            env_python_path = self.python_path
            base_python_path = self.base_python_path
            assert base_python_path is not None
        else:
            # Deployment environment is prepared *after* absolute symlinks
            # are cleaned up, so emit a relative path to the base Python
            # starting from the folder containing the layer's Python link
            venv_base_python_path = self._get_relative_deployed_base_python()
            assert venv_base_python_path is not None
            prefix = [".."] * len(
                self._relative_internal_path(self.python_path.parent).parts
            )
            base_python_path = Path(*prefix, venv_base_python_path)
            env_python_path = deployed_path / self._relative_internal_path(
                self.python_path
            )
        return base_python_path, env_python_path

    def _symlink_base_python(self, deployed_path: Path | None = None) -> None:
        # TODO: Improve code sharing with _wrap_base_python below
        # Make env python a direct symlink to the base Python runtime
        base_python_path, env_python_path = self._resolve_base_python(deployed_path)
        if deployed_path is None:
            _LOG.debug(
                f"Linking {str(env_python_path)!r} -> {str(base_python_path)!r}..."
            )
        elif base_python_path == self.base_python_path:
            # No change to the base Python path -> nothing to do
            return
        else:
            _LOG.debug(
                f"Linking {str(env_python_path)!r} -> {str(base_python_path)!r} for deployment..."
            )
        env_python_path.unlink(missing_ok=True)
        env_python_path.parent.mkdir(parents=True, exist_ok=True)
        env_python_path.symlink_to(base_python_path)
        # Ensure python_, pythonX and pythonX.Y are relative links to ./python
        env_python_dir = env_python_path.parent
        py_major, py_minor = self._py_version_info
        major_link = f"python{py_major}"
        minor_link = f"python{py_major}.{py_minor}"
        wrapper_bypass_link = "python_"
        for alias_link in (major_link, minor_link, wrapper_bypass_link):
            alias_path = env_python_dir / alias_link
            alias_path.unlink(missing_ok=True)
            alias_path.symlink_to("python")

    def _ensure_virtual_environment(self) -> subprocess.CompletedProcess[str]:
        # Use the base Python installation to create a new virtual environment
        if self.base_python_path is None:
            self._fail_build("Base Python path not set")
        options = ["--without-pip"]
        if self.env_path.exists():
            options.append("--upgrade")
            if not _WINDOWS_BUILD:
                # Ensure dynlib loading script wrapper doesn't cause any update problems
                self._symlink_base_python()
        if _WINDOWS_BUILD:
            options.append("--copies")
        else:
            options.append("--symlinks")
        command = [
            str(self.base_python_path),
            "-X",
            "utf8",
            "-Im",
            "venv",
            *options,
            str(self.env_path),
        ]
        # TODO: adjust how the Python command is executed based on UI verbosity settings
        result = run_python_command(command)
        self._link_build_environment()
        _fs_sync()
        _UI.echo(f"Virtual environment configured in {str(self.env_path)!r}")
        return result

    @classmethod
    def _generate_python_sh(
        cls,
        env_python_path: Path,
        wrapper_bypass_name: str,
        dynlib_paths: Sequence[Path],
    ) -> str:
        """Generate a Python wrapper script that sets the dynamic linking config appropriately."""
        assert dynlib_paths
        assert all(p.is_absolute() for p in dynlib_paths)
        # Use file relative paths so the wrapper script is portable (e.g. for local-export)
        # We avoid `walk_up=True` here to maintain Python 3.11 compatibility,
        # and to limit the relative paths to remaining within peer environments
        env_bin_dir_path = env_python_path.parent
        env_bin_dir_name = env_bin_dir_path.name
        env_path = env_bin_dir_path.parent
        env_name = env_path.name
        parent_path = env_path.parent

        def _sh_path(p: Path) -> str:
            parent_relative_path = p.relative_to(parent_path)
            if parent_relative_path.parts[0] != env_name:
                # Path is in a peer environment
                path_parts = ("..", "..", *parent_relative_path.parts)
            elif parent_relative_path.parts[1] != env_bin_dir_name:
                # Path is in the same environment as the wrapper script
                path_parts = ("..", *parent_relative_path.parts[1:])
            else:
                # Path is in the same directory as the wrapper script
                path_parts = parent_relative_path.parts[2:]
            return shlex.quote(str(Path(*path_parts)))

        # Wrapper needs "exec -a" support, so specify a shell that provides it
        # (most notably, "dash", which provide "/bin/sh" on Ubuntu omits it)
        # Also set the relevant environment variable for dynamic loading config
        if sys.platform == "darwin":
            shell = "/bin/zsh"
            dynlib_var = "DYLD_LIBRARY_PATH"
        else:
            shell = "/usr/bin/bash"
            dynlib_var = "LD_LIBRARY_PATH"

        dynlib_content: list[str] = [
            # Based on the PATH manipulation suggestion in https://unix.stackexchange.com/a/124447
            # New entries are appended rather than prepended so the env var can override the default load locations
            f'add_dynlib_dir() {{ case ":${{{dynlib_var}:=$1}}:" in *:"$1":*) ;; *) {dynlib_var}="${dynlib_var}:$1" ;; esac; }}',
            *(f'add_dynlib_dir "$script_dir/{_sh_path(p)}"' for p in dynlib_paths),
            f"export {dynlib_var}",
        ]
        wrapper_script_lines = [
            f"#!{shell}",
            "# Allow extension modules to find shared libraries published by lower layers",
            "set -eu",
            "# Note: `readlink -f` (long available in GNU coreutils) is available on macOS 12.3 and later",
            'script_dir="$(cd "$(dirname "$(readlink -f "$0")")" 1> /dev/null 2>&1 && pwd)"',
            *dynlib_content,
            f'script_path="$script_dir/{env_python_path.name}"',
            f'symlink_path="$script_dir/{wrapper_bypass_name}"',
            'test -f "$script_path" || { echo 1>&2 "Invalid wrapper script path: $script_path"; exit 1; }',
            'test -L "$symlink_path" || { echo 1>&2 "Invalid base Python symlink: $symlink_path"; exit 2; }',
            'test "$symlink_path" -ef "$script_path" && '
            '{ echo 1>&2 "Symlink loop detected: $symlink_path -> $script_path"; exit 3; }',
            'exec -a "$script_path" "$symlink_path" "$@"',
            "",
        ]
        return "\n".join(wrapper_script_lines)

    def _wrap_base_python(
        self, dynlib_paths: Sequence[Path], deployed_path: Path | None = None
    ) -> None:
        # TODO: Improve code sharing with _symlink_base_python above
        # Make python_ a direct symlink to the base Python runtime
        base_python_path, env_python_path = self._resolve_base_python(deployed_path)
        if deployed_path is None:
            _LOG.debug(
                f"Wrapping {str(env_python_path)!r} -> {str(base_python_path)!r} link..."
            )
        elif base_python_path == self.base_python_path and not dynlib_paths:
            # No change to the base Python path -> nothing to do
            return
        else:
            _LOG.debug(
                f"Wrapping {str(env_python_path)!r} -> {str(base_python_path)!r} for deployment..."
            )
        env_python_dir = env_python_path.parent
        wrapper_bypass_path = env_python_dir / "python_"
        _LOG.debug(
            f"Linking {str(wrapper_bypass_path)!r} -> {str(base_python_path)!r}..."
        )
        wrapper_bypass_path.unlink(missing_ok=True)
        wrapper_bypass_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper_bypass_path.symlink_to(base_python_path)
        # Ensure pythonX and pythonX.Y are relative links to ./python
        py_major, py_minor = self._py_version_info
        major_link = f"python{py_major}"
        minor_link = f"python{py_major}.{py_minor}"
        for alias_link in (major_link, minor_link):
            alias_path = env_python_dir / alias_link
            alias_path.unlink(missing_ok=True)
            alias_path.symlink_to("python")
        # Make env python a dynlib loading adjustment wrapper script
        # to allow shared library loading in POSIX environments
        sh_contents = self._generate_python_sh(
            env_python_path, wrapper_bypass_path.name, dynlib_paths
        )
        _LOG.debug(f"Generating {str(env_python_path)!r}...")
        env_python_path.unlink(missing_ok=True)
        env_python_path.write_text(sh_contents, encoding="utf-8")
        os.chmod(env_python_path, 0o755)

    def _link_base_python(self, deployed_path: Path | None = None) -> None:
        if _WINDOWS_BUILD:
            # venv creation in build step handles build environments
            # postinstall script handles deployed environments
            return
        if deployed_path is None:
            target_path = self.build_path
            dynlib_paths = [target_path / d for d in self._iter_build_dynlib_dirs()]
        else:
            target_path = deployed_path.parent
            dynlib_paths = [target_path / d for d in self._iter_deployed_dynlib_dirs()]
        if dynlib_paths:
            self._wrap_base_python(dynlib_paths, deployed_path)
        else:
            self._symlink_base_python(deployed_path)

    def _link_build_environment(self) -> None:
        # Ensure Python is executable in the build environment
        self._link_base_python()
        # Create sitecustomize file for the build environment
        build_path = self.build_path
        build_pylib_paths = [build_path / d for d in self._iter_build_pylib_dirs()]
        build_dynlib_paths = [build_path / d for d in self._iter_build_dynlib_dirs()]
        sc_contents = postinstall.generate_sitecustomize(
            build_pylib_paths, build_dynlib_paths
        )
        if sc_contents is None:
            self._fail_build(
                "Layered environments must at least link a base runtime environment"
            )
        sc_path = self.pylib_path / "sitecustomize.py"
        _LOG.debug(f"Generating {str(sc_path)!r}...")
        sc_path.write_text(sc_contents, encoding="utf-8")

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        if lock_only:
            raise BuildEnvError(
                "Only runtime environments support lock-only installation"
            )
        self._ensure_virtual_environment()
        super()._update_existing_environment()

    def _create_new_environment(self, *, lock_only: bool = False) -> None:
        self._clean_environment()
        self._update_existing_environment(lock_only=lock_only)

    def _prepare_deployed_env(self, deployed_env_path: Path) -> None:
        self._link_base_python(deployed_env_path)

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        super()._update_output_metadata(metadata)
        # Non-windows platforms use symlinks, so only need updates on feature releases
        # Windows copies the main Python binary and support library, so always needs updates
        runtime = self.base_runtime
        assert runtime is not None
        metadata["runtime_layer"] = runtime.install_target
        metadata["python_implementation"] = runtime.env_spec.python_implementation
        metadata["bound_to_implementation"] = bool(_WINDOWS_BUILD)
        framework_env_names = [fw.install_target for fw in self.linked_frameworks]
        metadata["required_layers"] = framework_env_names


class FrameworkEnv(LayeredEnvBase):
    """Framework layer build environment."""

    kind = LayerVariants.FRAMEWORK
    category = LayerCategories.FRAMEWORKS

    @property
    def env_spec(self) -> FrameworkSpec:
        """Layer specification for this framework build environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, FrameworkSpec)
        return self._env_spec


class ApplicationEnv(LayeredEnvBase):
    """Application layer build environment."""

    kind = LayerVariants.APPLICATION
    category = LayerCategories.APPLICATIONS

    launch_module_name: str = field(init=False, repr=False)
    _launch_module_hash: str = field(init=False, repr=False)
    _support_module_info: list[SupportModuleMetadata] = field(init=False, repr=False)

    @property
    def env_spec(self) -> ApplicationSpec:
        """Layer specification for this application build environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, ApplicationSpec)
        return self._env_spec

    def __post_init__(self) -> None:
        super().__post_init__()
        env_spec = self.env_spec
        # Launch module details
        launch_module_path = env_spec.launch_module_path
        self.launch_module_name = launch_module_path.stem
        launch_module_hash = hash_module(
            launch_module_path, walk_iter=self.source_filter.walk
        )
        self._launch_module_hash = launch_module_hash
        _append_version_input = self.env_lock.append_version_input
        _append_version_input(launch_module_hash)
        # Support module details
        support_module_info: list[SupportModuleMetadata] = []
        for support_module_path in env_spec.support_module_paths:
            support_module_name = support_module_path.stem
            support_module_hash = hash_module(
                support_module_path, walk_iter=self.source_filter.walk
            )
            _append_version_input(support_module_hash)
            support_module_info.append(
                {
                    "name": support_module_name,
                    "hash": support_module_hash,
                }
            )
        self._support_module_info = support_module_info

    def _sync_app_module(self, src: Path, dest: Path) -> None:
        # To ensure the timestamps in the layer archive are *always* clamped,
        # we intentionally *don't* copy the launch module file metadata here
        if src.is_file():
            shutil.copyfile(src, dest)
        else:
            shutil.copytree(
                src,
                dest,
                dirs_exist_ok=True,
                copy_function=shutil.copyfile,
                ignore=self.source_filter.ignore,
            )
            # Also override the copied directory timestamps
            for copied_path, _subdirs, _files in walk_path(dest):
                copied_path.touch()

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        super()._update_existing_environment(lock_only=lock_only)
        # Also publish the specified launch module and any
        # support modules as importable top level modules
        env_spec = self.env_spec
        pylib_path = self.pylib_path
        launch_module_source_path = env_spec.launch_module_path
        launch_module_env_path = pylib_path / launch_module_source_path.name
        _LOG.debug(f"Including launch module {launch_module_source_path!r}...")
        self._sync_app_module(launch_module_source_path, launch_module_env_path)
        for support_module_source_path in env_spec.support_module_paths:
            support_module_env_path = pylib_path / support_module_source_path.name
            _LOG.debug(f"Including support module {support_module_source_path!r}...")
            self._sync_app_module(support_module_source_path, support_module_env_path)

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        super()._update_output_metadata(metadata)
        metadata["app_launch_module"] = self.launch_module_name
        metadata["app_launch_module_hash"] = self._launch_module_hash
        if self._support_module_info:
            # Only include this field if the layer defines support modules
            metadata["app_support_modules"] = self._support_module_info

    def get_deployed_config(
        self,
    ) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        config = super().get_deployed_config()
        if self.launch_module_name:
            config["launch_module"] = self.launch_module_name
        return config


######################################################
# Building layered environments based on a TOML file
######################################################

BuildEnv = TypeVar("BuildEnv", bound=LayerEnvBase)


@dataclass
class StackSpec:
    """Layered environment stack specification."""

    # Specified on creation
    spec_path: Path
    runtimes: MutableMapping[LayerBaseName, RuntimeSpec]
    frameworks: MutableMapping[LayerBaseName, FrameworkSpec]
    applications: MutableMapping[LayerBaseName, ApplicationSpec]
    requirements_dir_path: Path
    index_config: PackageIndexConfig = field(
        repr=False, default_factory=PackageIndexConfig
    )

    # Derived from runtime environment in __post_init__
    build_platform: TargetPlatform = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.build_platform = get_build_platform()
        self.spec_path = as_normalized_path(self.spec_path)
        # Resolve requirements_dir_path relative to spec_path
        self.requirements_dir_path = self.resolve_lexical_path(
            self.requirements_dir_path
        )

    @staticmethod
    def _get_layer_name(data: Mapping[str, Any]) -> Any:
        try:
            return data["name"]
        except KeyError:
            pass  # This error context is not interesting
        raise LayerSpecError("Layer specifications must include 'name'")

    @classmethod
    def _delete_field(cls, data: MutableMapping[str, Any], legacy_name: str) -> bool:
        """Ignore removed legacy field. Returns True if field needs to be removed."""
        legacy_field_value = data.pop(legacy_name, None)
        if legacy_field_value is not None:
            layer_name = cls._get_layer_name(data)
            msg = f"Dropping legacy field {legacy_name!r} for layer {layer_name!r}"
            warnings.warn(msg, FutureWarning)
            return True
        return False

    @classmethod
    def _update_field_name(
        cls, data: MutableMapping[str, Any], legacy_name: str, name: str
    ) -> bool:
        """Convert legacy field to current field. Returns True if conversion is needed."""
        legacy_field_value = data.pop(legacy_name, None)
        if legacy_field_value is not None:
            layer_name = cls._get_layer_name(data)
            if name in data:
                msg = f"Layer {layer_name!r} sets both {name!r} and the obsolete {legacy_name!r}"
                raise LayerSpecError(msg)
            data[name] = legacy_field_value
            msg = f"Converting legacy field name {legacy_name!r} to {name!r} for layer {layer_name!r}"
            warnings.warn(msg, FutureWarning)
            return True
        return False

    @classmethod
    def _update_legacy_fields(
        cls,
        data: MutableMapping[str, Any],
        conversions: Mapping[str, str | None],
    ) -> bool:
        modified = False
        for legacy_name, name in conversions.items():
            if name is None:
                field_modified = cls._delete_field(data, legacy_name)
            else:
                field_modified = cls._update_field_name(data, legacy_name, name)
            if field_modified:
                modified = True
        return modified

    _RUNTIME_LEGACY_CONVERSIONS: ClassVar[Mapping[str, str | None]] = {
        "fully_versioned_name": "python_implementation",
        "build_requirements": None,
    }
    _FRAMEWORK_LEGACY_CONVERSIONS: ClassVar[Mapping[str, str | None]] = {
        "build_requirements": None,
    }
    _APPLICATION_LEGACY_CONVERSIONS: ClassVar[Mapping[str, str | None]] = {
        "build_requirements": None,
    }

    @staticmethod
    def _linearize_C3(
        err_prefix: str, declared_deps: Iterable[FrameworkSpec]
    ) -> tuple[FrameworkSpec, ...]:
        # Framework layers are allowed to depend on each other, forming a directed acyclic graph.
        # Root layers depend only on their underlying runtime, not on any other framework layers.
        # To be able to build the envs, these graphs need to be linearized for sys.path inclusion.
        # Rather than inventing anything novel, we use the same C3 linearization as Python itself.
        # See https://www.python.org/download/releases/2.3/mro/ for more details.
        # Note: unlike class MROs, the layer itself is NOT part of the linearization result
        # Work with reversed lists so popping the "head" of each list is a cheap operation
        declared_seq = list(declared_deps)
        declared_seq.reverse()
        # Framework deps are already linearized, so no need to linearize them again
        sequences_to_merge = [
            [*reversed(spec.frameworks), spec] for spec in declared_deps
        ]
        sequences_to_merge.append(declared_seq)
        linearized_deps: list[FrameworkSpec] = []

        def in_tail(cand: FrameworkSpec, seq: Sequence[FrameworkSpec]) -> bool:
            # Reversed lists, so the tail is everything except the last element
            try:
                idx = seq.index(cand)
            except ValueError:
                return False
            return idx < (len(seq) - 1)

        remaining_seqs = [seq for seq in sequences_to_merge if seq]
        while remaining_seqs := [seq for seq in remaining_seqs if seq]:
            # find a merge candidate among the seq heads
            checked: set[LayerBaseName] = set()
            next_dep: FrameworkSpec | None = None
            for seq in remaining_seqs:
                candidate = seq[-1]  # Reversed lists, so the head is the last element
                if candidate.name in checked:
                    # Already failed the check, don't check it again
                    continue
                if any(in_tail(candidate, seq) for seq in remaining_seqs):
                    # In the tail of one of the seqs, so try again later
                    checked.add(candidate.name)
                    continue
                next_dep = candidate
                break
            if next_dep is None:
                # The heads of all remaining sequences are in the tail of at least one sequence,
                # indicating either a self-referential loop, or contradictory resolution orders
                msg = (
                    f"{err_prefix} dependency linearization failed"
                    f" (remaining sequences: {[list(reversed(seq)) for seq in remaining_seqs]!r})"
                )
                raise LayerSpecError(msg)
            linearized_deps.append(next_dep)
            # Update sequences for the successfully merged candidate
            for seq in remaining_seqs:
                if seq[-1] == next_dep:
                    seq.pop()

        return tuple(linearized_deps)

    @classmethod
    def _resolve_layer_deps(
        cls,
        err_prefix: str,
        declared_spec: Mapping[str, Any],
        runtimes: Mapping[LayerBaseName, RuntimeSpec],
        frameworks: Mapping[LayerBaseName, FrameworkSpec],
    ) -> tuple[RuntimeSpec, tuple[FrameworkSpec, ...], dict[NormalizedName, str]]:
        # Note: layers are intentionally allowed to override any *default* package index settings
        declared_runtime: LayerBaseName | None = declared_spec.get("runtime")
        declared_frameworks: Sequence[LayerBaseName] | None = declared_spec.get(
            "frameworks"
        )
        merged_package_indexes: dict[NormalizedName, str] = {}
        runtime_dep: RuntimeSpec | None = None
        framework_deps: tuple[FrameworkSpec, ...]
        if declared_runtime is not None:
            if declared_frameworks is not None:
                msg = (
                    f"{err_prefix} must specify a runtime or framework dependencies, not both"
                    f" (runtime: {declared_runtime!r}; frameworks: {declared_frameworks!r})"
                )
                raise LayerSpecError(msg)
            framework_deps = ()
            runtime_spec_name = declared_runtime
            runtime_dep = runtimes.get(runtime_spec_name)
            if runtime_dep is None:
                msg = f"{err_prefix} references unknown runtime {declared_runtime!r}"
                raise LayerSpecError(msg)
            # Check below that the runtime sources are consistent with the layer's own sources
            merged_package_indexes.update(runtime_dep.package_indexes)
        elif not declared_frameworks:
            msg = f"{err_prefix} must specify a runtime or at least one framework dependency"
            raise LayerSpecError(msg)
        else:
            declared_fw_deps: list[FrameworkSpec] = []
            for fw_name in declared_frameworks:
                fw_dep = frameworks.get(fw_name)
                if fw_dep is None:
                    msg = f"{err_prefix} references unknown framework {fw_name!r}"
                    raise LayerSpecError(msg)
                if runtime_dep is None:
                    runtime_dep = fw_dep.runtime
                elif fw_dep.runtime is not runtime_dep:
                    msg = (
                        f"{err_prefix} references inconsistent frameworks. "
                        f"{declared_fw_deps[0].name!r} requires runtime {runtime_dep.name!r}."
                        f"while {fw_dep.name!r} requires runtime {fw_dep.runtime.name!r}."
                    )
                    raise LayerSpecError(msg)
                declared_fw_deps.append(fw_dep)
            framework_deps = cls._linearize_C3(err_prefix, declared_fw_deps)
            assert runtime_dep is not None
            # Check any framework source overrides are consistent with each other
            for fw_dep in reversed(framework_deps):
                for dist_name, index_name in fw_dep.package_indexes.items():
                    declared_index_name = merged_package_indexes.get(dist_name, None)
                    if declared_index_name and declared_index_name != index_name:
                        msg = (
                            f"{err_prefix} depends on layers with "
                            f"inconsistent package index overrides for {dist_name} "
                            f"({declared_index_name} != {index_name})"
                        )
                        raise LayerSpecError(msg)
                merged_package_indexes.update(fw_dep.package_indexes)
        # Check layer's source overrides are consistent with the layers it depends on
        declared_package_indexes = declared_spec.get("package_indexes", {})
        for raw_dist_name, index_name in declared_package_indexes.items():
            # The package names for this layer haven't been normalised yet
            dist_name = canonicalize_name(raw_dist_name)
            declared_index_name = merged_package_indexes.get(dist_name, None)
            if declared_index_name and declared_index_name != index_name:
                msg = (
                    f"{err_prefix} declares an inconsistent "
                    f"package index override for {raw_dist_name} "
                    f"({declared_index_name} != {index_name})"
                )
                raise LayerSpecError(msg)
        merged_package_indexes.update(declared_package_indexes)
        return runtime_dep, framework_deps, merged_package_indexes

    @classmethod
    def from_dict(cls, fname: StrPath, layer_data: dict[str, Any]) -> Self:
        """Write stack specification to given path as TOML and then load it."""
        stack_spec_path = as_normalized_path(fname)
        stack_spec_path.parent.mkdir(parents=True, exist_ok=True)
        with open(stack_spec_path, "w") as f:
            tomlkit.dump(layer_data, f)
        return cls.load(stack_spec_path)

    @classmethod
    def load(
        cls, fname: StrPath, index_config: PackageIndexConfig | None = None
    ) -> Self:
        """Load stack specification from given TOML file."""
        stack_spec_path = as_normalized_path(fname)
        with open(stack_spec_path, "rb") as f:
            data = tomllib.load(f)
        spec_dir_path = stack_spec_path.parent
        requirements_dir_path = spec_dir_path / "requirements"
        # Fully populate the package index configuration details
        if index_config is None:
            index_config = PackageIndexConfig()
        else:
            index_config = index_config.copy()
        index_config._load_common_tool_config(stack_spec_path)
        # Collect the list of runtime specs
        runtimes: dict[LayerBaseName, RuntimeSpec] = {}
        for rt in data.get("runtimes", ()):
            name = cls._get_layer_name(rt)
            # Handle backwards compatibility fixes and warnings
            cls._update_legacy_fields(rt, cls._RUNTIME_LEGACY_CONVERSIONS)
            # Consistency checks (no field value conversions necessary)
            if name in runtimes:
                msg = f"Runtime names must be distinct ({name!r} already defined)"
                raise LayerSpecError(msg)
            rt["_index_config"] = index_config
            ensure_optional_env_spec_fields(rt)
            runtimes[name] = RuntimeSpec(**rt)
        # Collect the list of framework specs
        frameworks: dict[LayerBaseName, FrameworkSpec] = {}
        for fw in data.get("frameworks", ()):
            name = cls._get_layer_name(fw)
            # Handle backwards compatibility fixes and warnings
            cls._update_legacy_fields(fw, cls._FRAMEWORK_LEGACY_CONVERSIONS)
            # Consistency checks and field value conversions
            if name in frameworks:
                msg = f"Framework names must be distinct ({name!r} already defined)"
                raise LayerSpecError(msg)
            err_prefix = f"Framework {name!r}"
            fw["_index_config"] = index_config
            runtime_dep, framework_deps, package_indexes = cls._resolve_layer_deps(
                err_prefix, fw, runtimes, frameworks
            )
            fw["runtime"] = runtime_dep
            fw["frameworks"] = framework_deps
            fw["package_indexes"] = package_indexes
            ensure_optional_env_spec_fields(fw)
            frameworks[name] = FrameworkSpec(**fw)
        # Collect the list of application specs
        applications: dict[LayerBaseName, ApplicationSpec] = {}
        for app in data.get("applications", ()):
            name = cls._get_layer_name(app)
            # Handle backwards compatibility fixes and warnings
            cls._update_legacy_fields(app, cls._APPLICATION_LEGACY_CONVERSIONS)
            # Consistency checks and field value conversions
            if name in applications:
                msg = f"Application names must be distinct ({name!r} already defined)"
                raise LayerSpecError(msg)
            err_prefix = f"Application {name!r}"
            app["_index_config"] = index_config
            runtime_dep, framework_deps, package_indexes = cls._resolve_layer_deps(
                err_prefix, app, runtimes, frameworks
            )
            app["runtime"] = runtime_dep
            app["frameworks"] = framework_deps
            app["package_indexes"] = package_indexes
            launch_module = app.pop("launch_module")
            launch_module_path = spec_dir_path / launch_module
            launch_module_name = launch_module_path.stem
            support_modules = sorted(app.pop("support_modules", ()))
            support_module_paths = [spec_dir_path / m for m in support_modules]
            support_module_names = [p.stem for p in support_module_paths]
            unique_support_module_names = set(support_module_names)
            if launch_module_name in support_module_names:
                msg = f"Launch module {launch_module_name!r} conflicts with support module in app layer {name!r}"
                raise LayerSpecError(msg)
            if len(unique_support_module_names) < len(support_module_names):
                msg = f"Conflicting support module names in app layer {name!r}"
                raise LayerSpecError(msg)
            app["launch_module_path"] = launch_module_path
            app["support_module_paths"] = support_module_paths
            ensure_optional_env_spec_fields(app)
            applications[name] = ApplicationSpec(**app)
        self = cls(
            stack_spec_path,
            runtimes,
            frameworks,
            applications,
            requirements_dir_path,
            index_config,
        )
        for app_spec in self.applications.values():
            if not app_spec.launch_module_path.exists():
                msg = f"Specified launch module {str(app_spec.launch_module_path)!r} does not exist"
                raise LayerSpecError(msg)
            missing_paths = [p for p in app_spec.support_module_paths if not p.exists()]
            if missing_paths:
                missing_module_info = "\n    ".join(map(str, missing_paths))
                msg = f"Specified support modules do not exist:\n    {missing_module_info}"
                raise LayerSpecError(msg)
        return self

    def all_environment_specs(self) -> Iterator[LayerSpecBase]:
        """Iterate over the specifications for all defined environments.

        All runtimes are produced first, then frameworks, then applications.
        """
        return chain(
            self.runtimes.values(), self.frameworks.values(), self.applications.values()
        )

    def _define_envs(
        self,
        build_path: Path,
        source_filter: SourceTreeContentFilter,
        env_class: type[BuildEnv],
        specs: Mapping[LayerBaseName, LayerSpecBase],
    ) -> MutableMapping[LayerBaseName, BuildEnv]:
        requirements_dir = self.requirements_dir_path
        build_environments: dict[LayerBaseName, BuildEnv] = {}
        build_platform = self.build_platform
        for name, spec in specs.items():
            requirements_path = spec.get_requirements_path(
                build_platform, requirements_dir
            )
            # TODO: Make "source_filter" configurable once there is more than one filter defined
            build_env = env_class(
                spec,
                build_path,
                requirements_path,
                source_filter,
                build_platform,
            )
            build_environments[name] = build_env
            _LOG.info(f"  Defined {name!r}: {build_env}")
        return build_environments

    def resolve_lexical_path(self, related_location: StrPath, /) -> Path:
        """Resolve a path relative to the location of the stack specification."""
        return _resolve_lexical_path(related_location, self.spec_path.parent)

    def define_build_environment(
        self,
        build_dir: StrPath = "",
    ) -> "BuildEnvironment":
        """Define layer build environments for this specification."""
        build_path = self.resolve_lexical_path(build_dir)
        source_filter = get_default_source_filter(self.spec_path.parent)
        _LOG.info("Defining runtime environments:")
        runtimes = self._define_envs(
            build_path, source_filter, RuntimeEnv, self.runtimes
        )
        _LOG.info("Defining framework environments:")
        frameworks = self._define_envs(
            build_path, source_filter, FrameworkEnv, self.frameworks
        )
        for fw_env in frameworks.values():
            runtime = runtimes[fw_env.env_spec.runtime.name]
            fw_env.link_layered_environments(runtime, frameworks)
        _LOG.info("Defining application environments:")
        applications = self._define_envs(
            build_path, source_filter, ApplicationEnv, self.applications
        )
        for app_env in applications.values():
            runtime = runtimes[app_env.env_spec.runtime.name]
            app_env.link_layered_environments(runtime, frameworks)
        return BuildEnvironment(
            self,
            runtimes,
            frameworks,
            applications,
            build_path,
        )


@dataclass
class BuildEnvironment:
    """Interface to build specified layered environment stacks."""

    METADATA_DIR = "__venvstacks__"  # Output subdirectory for the build metadata
    METADATA_MANIFEST = "venvstacks.json"  # File with full metadata for this build
    METADATA_ENV_DIR = (
        "env_metadata"  # Files with metadata snippets for each environment
    )

    # Specified on creation
    stack_spec: StackSpec
    runtimes: MutableMapping[LayerBaseName, RuntimeEnv] = field(repr=False)
    frameworks: MutableMapping[LayerBaseName, FrameworkEnv] = field(repr=False)
    applications: MutableMapping[LayerBaseName, ApplicationEnv] = field(repr=False)
    build_path: Path

    def __post_init__(self) -> None:
        # Resolve local config folders relative to spec path
        stack_spec = self.stack_spec
        self.build_path = stack_spec.resolve_lexical_path(self.build_path)

    # Provide more convenient access to selected stack_spec attributes
    @property
    def requirements_dir_path(self) -> Path:
        """Parent path containing the locked layer requirements."""
        return self.stack_spec.requirements_dir_path

    @property
    def build_platform(self) -> str:
        """Target platform for this environment."""
        return self.stack_spec.build_platform

    # Iterators over various categories of included environments
    def all_environments(self) -> Iterator[LayerEnvBase]:
        """Iterate over all defined environments.

        All runtimes are produced first, then frameworks, then applications.
        """
        return chain(
            self.runtimes.values(), self.frameworks.values(), self.applications.values()
        )

    def environments_to_lock(self) -> Iterator[LayerEnvBase]:
        """Iterate over all environments where locking is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.want_lock is not False:  # Accepts `None` as meaning "lock if needed"
                yield env

    def runtimes_to_lock(self) -> Iterator[RuntimeEnv]:
        """Iterate over runtime environments where locking is requested or allowed."""
        for env in self.runtimes.values():
            if env.want_lock is not False:  # Accepts `None` as meaning "lock if needed"
                yield env

    def environments_to_build(self) -> Iterator[LayerEnvBase]:
        """Iterate over all environments where building is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def runtimes_to_build(self) -> Iterator[RuntimeEnv]:
        """Iterate over runtime environments where building is requested or allowed."""
        for env in self.runtimes.values():
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def venvstacks_to_build(self) -> Iterator[LayeredEnvBase]:
        """Iterate over non-runtime environments where building is requested or allowed.

        Frameworks are produced first, then applications.
        """
        for env in chain(self.frameworks.values(), self.applications.values()):
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def built_environments(self) -> Iterator[LayerEnvBase]:
        """Iterate over all environments that were built by this build process.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.was_built:
                yield env

    def environments_to_publish(self) -> Iterator[LayerEnvBase]:
        """Iterate over all environments where publication is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.want_publish:  # There's no "if needed" option for publication
                yield env

    def get_stack_status(
        self, *, report_ops: bool = True, include_deps: bool = False
    ) -> StackStatus:
        """Get JSON-compatible summary of the environment stack and selected operations."""
        return StackStatus(
            spec_name=str(self.stack_spec.spec_path),
            runtimes=[
                env.get_env_status(report_ops=report_ops)
                for env in self.runtimes.values()
                if not env.excluded
            ],
            frameworks=[
                env.get_env_status(report_ops=report_ops, include_deps=include_deps)
                for env in self.frameworks.values()
                if not env.excluded
            ],
            applications=[
                env.get_env_status(report_ops=report_ops, include_deps=include_deps)
                for env in self.applications.values()
                if not env.excluded
            ],
        )

    # Assign environments to the different operation categories
    def select_operations(
        self,
        lock: bool | None = False,
        build: bool | None = True,
        publish: bool = True,
        *,
        reset_lock: bool = False,
    ) -> None:
        """Configure the selected operations on all defined environments."""
        for env in self.all_environments():
            env.select_operations(
                lock=lock, build=build, publish=publish, reset_lock=reset_lock
            )

    def filter_layers(
        self, patterns: Iterable[str]
    ) -> tuple[Set[EnvNameBuild], Set[str]]:
        """Returns a 2-tuple of matching layer names and patterns which do not match any environments."""
        matching_env_names: set[EnvNameBuild] = set()
        matched_patterns: set[str] = set()
        unmatched_patterns: set[str] = set(patterns)
        for env in self.all_environments():
            env_name = env.env_name
            matched = False
            # Check *all* the unmatched patterns for each layer
            # (this allows a matching env to count as matching multiple patterns)
            for pattern in list(unmatched_patterns):
                if fnmatch(env_name, pattern):
                    unmatched_patterns.remove(pattern)
                    matched_patterns.add(pattern)
                    if not matched:
                        matching_env_names.add(env_name)
                        matched = True
            if matched:
                continue
            # Only check previously matched patterns if necessary
            for pattern in matched_patterns:
                if fnmatch(env_name, pattern):
                    matching_env_names.add(env_name)
                    break
        return matching_env_names, unmatched_patterns

    def select_layers(
        self,
        include: Iterable[EnvNameBuild],
        lock: bool | None = False,
        build: bool | None = True,
        publish: bool = True,
        lock_dependencies: bool = False,
        build_dependencies: bool = False,
        publish_dependencies: bool = False,
        build_derived: bool = True,
        publish_derived: bool = True,
        reset_locks: Iterable[EnvNameBuild] = (),
    ) -> None:
        """Selectively configure operations only on the specified environments."""
        # Ensure later pipeline stages are skipped when earlier ones are skipped
        # Also update the related layer handling based on the enabled pipeline stages
        if lock:
            # When locking, locking derived layers is not optional
            lock_derived = True
            # Don't build or publish dependencies if they're not relocked
            if not lock_dependencies:
                build_dependencies = publish_dependencies = False
        else:
            # If the included layers aren't being locked, don't lock anything else
            lock_derived = lock_dependencies = False
        if build:
            # When building, don't publish environments that haven't been built
            if not build_dependencies:
                publish_dependencies = False
            if not build_derived:
                publish_derived = False
        else:
            # If the included layers aren't being built, don't build anything else
            build_derived = build_dependencies = False
        if not publish:
            # If the included layers aren't being published, don't publish anything else
            publish_derived = publish_dependencies = False
        # Identify explicitly included environments
        envs_by_name: dict[EnvNameBuild, LayerEnvBase] = {
            env.env_name: env for env in self.all_environments()
        }
        included_envs = set(include)
        envs_to_reset = set(reset_locks)
        for env_name, env in envs_by_name.items():
            if env_name in included_envs:
                # Run all requested operations on this environment
                reset_lock = env_name in envs_to_reset
                env.select_operations(
                    lock=lock, build=build, publish=publish, reset_lock=reset_lock
                )
            else:
                # Skip running operations on this environment
                # (Note: this exclusion may be overridden on related layers below)
                env.exclude_layer()
        # Enable operations on related layers if requested
        # Dependencies are always checked so they can be set to "if needed" locks & builds
        check_derived = lock_derived or build_derived or publish_derived
        derived_envs: set[EnvNameBuild] = set()
        dependency_envs: set[EnvNameBuild] = set()
        layered_envs: list[LayeredEnvBase] = [
            *self.frameworks.values(),
            *self.applications.values(),
        ]
        for layered_env in layered_envs:
            env_name = layered_env.env_name
            env_spec = layered_env.env_spec
            rt_env_name = env_spec.runtime.env_name
            fw_env_names = [fw_spec.env_name for fw_spec in env_spec.frameworks]
            if env_name in included_envs:
                # This env is included, check if any of its dependencies need inclusion
                for fw_env_name in fw_env_names:
                    if fw_env_name in included_envs:
                        continue
                    dependency_envs.add(fw_env_name)
                if rt_env_name not in included_envs:
                    dependency_envs.add(rt_env_name)
            elif check_derived:
                # Check for any framework or the runtime this env depends on being included
                if rt_env_name in included_envs:
                    derived_envs.add(env_name)
                else:
                    for fw_env_name in fw_env_names:
                        if fw_env_name in included_envs:
                            derived_envs.add(env_name)
                            break
        # Check if conflicting requirements have been given for any framework layers
        potential_conflicts = derived_envs & dependency_envs
        if potential_conflicts:
            cause = None
            if lock_derived != lock_dependencies:
                cause = "lock"
            elif build_derived != build_dependencies:
                cause = "build"
            elif publish_derived != publish_dependencies:
                cause = "publication"
            if cause is not None:
                msg = f"Conflicting {cause} instructions for {sorted(potential_conflicts)}"
                raise BuildEnvError(msg)
        # Derived environments never need to be locked or built implicitly
        for env_name in derived_envs:
            env = envs_by_name[env_name]
            env.select_operations(
                lock=lock_derived,
                build=build_derived,
                publish=publish_derived,
                reset_lock=lock_derived and (env_name in envs_to_reset),
            )
        # Dependencies are always allowed to be locked or built implicitly
        # (this only happens if the operation's outputs don't exist yet)
        # Also reset dependency layer locks if locking dependency layers
        # is explicitly requested rather than being "only if needed"
        for env_name in dependency_envs:
            env = envs_by_name[env_name]
            env.select_operations(
                lock=lock_dependencies or None,    # Allow locking if needed
                build=build_dependencies or None,  # Allow building if needed
                publish=publish_dependencies,      # No implicit publication
                reset_lock=lock_dependencies and (env_name in envs_to_reset),
            )  # fmt: skip

    # Define the various operations on the included environments
    def _needs_lock(self) -> bool:
        return any(env.needs_lock() for env in self.environments_to_lock())

    def _init_required_dirs(self) -> None:
        """Ensure required folders and files to lock and build environments exist."""
        # Ensure the destination folder for requirements files exists
        self.requirements_dir_path.mkdir(parents=True, exist_ok=True)
        # Ensure the destination folder for the build environments exists
        # (even locking needs to be able to create the base runtime environments)
        build_path = self.build_path
        build_path.mkdir(parents=True, exist_ok=True)
        # Ensure the tool config files exist
        index_config = self.stack_spec.index_config
        index_config._write_common_tool_config_files(build_path)

    def _get_lock_time(self) -> datetime | None:
        return self.stack_spec.index_config._get_uv_exclude_newer()

    def lock_environments(self, *, clean: bool = False) -> Sequence[EnvironmentLock]:
        """Lock build environments for specified layers."""
        # Lock environments without fully building them
        # Necessarily creates the runtime environments and
        # installs any declared build dependencies
        self._init_required_dirs()
        for rt_env in self.runtimes_to_lock():
            rt_env.create_build_environment(clean=clean)
        lock_time = self._get_lock_time()
        return [env.lock_requirements(lock_time) for env in self.environments_to_lock()]

    def create_environments(
        self, *, clean: bool = False, lock: bool | None = False
    ) -> None:
        """Create build environments for specified layers."""
        # Base runtime environments need to exist before dependencies can be locked
        self._init_required_dirs()
        clean_runtime_envs = clean
        if lock or self._needs_lock():
            clean_runtime_envs = False  # Don't clean the runtime envs again below
            self.lock_environments(clean=clean)
        # Create base runtime environments
        for rt_env in self.runtimes_to_build():
            rt_env.create_environment(clean=clean_runtime_envs)
        # Create framework and application environments atop the base runtimes
        for layered_env in self.venvstacks_to_build():
            layered_env.create_environment(clean=clean)
            layered_env.report_python_site_details()

    @staticmethod
    def _env_metadata_path(
        env_metadata_dir: Path, env_name: EnvNameBuild, platform_tag: str = ""
    ) -> Path:
        return env_metadata_dir / f"{env_name}{platform_tag}.json"

    def _load_env_metadata(
        self, env_metadata_dir: Path, env: LayerEnvBase, platform_tag: str
    ) -> Any:
        metadata_path = self._env_metadata_path(
            env_metadata_dir, env.env_name, platform_tag
        )
        if not metadata_path.exists():
            return None
        with metadata_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_archive_metadata(
        self, env_metadata_dir: Path, env: LayerEnvBase, platform_tag: str = ""
    ) -> ArchiveMetadata | None:
        """Load previously published archive metadata."""
        # mypy is right to complain that the JSON hasn't been validated to conform
        # to the ArchiveMetadata interface, but we're OK with letting the runtime
        # errors happen in that scenario. Longer term, explicit JSON schemas should be
        # defined and used for validation when reading the metadata files.
        metadata = self._load_env_metadata(env_metadata_dir, env, platform_tag)
        return cast(ArchiveMetadata, metadata)

    def load_export_metadata(
        self, env_metadata_dir: Path, env: LayerEnvBase
    ) -> ExportMetadata | None:
        """Load previously exported environment metadata."""
        # mypy is right to complain that the JSON hasn't been validated to conform
        # to the ExportMetadata interface, but we're OK with letting the runtime
        # errors happen in that scenario. Longer term, explicit JSON schemas should be
        # defined and used for validation when reading the metadata files.
        metadata = self._load_env_metadata(env_metadata_dir, env, platform_tag="")
        return cast(ExportMetadata, metadata)

    @overload
    def publish_artifacts(
        self,
        output_dir: StrPath | None = ...,
        *,
        force: bool = ...,
        tag_outputs: bool = ...,
        dry_run: Literal[False] = ...,
    ) -> PublishedArchivePaths: ...
    @overload
    def publish_artifacts(
        self,
        output_dir: StrPath | None = ...,
        *,
        force: bool = ...,
        tag_outputs: bool = ...,
        dry_run: Literal[True] = ...,
    ) -> tuple[Path, StackPublishingRequest]: ...
    def publish_artifacts(
        self,
        output_dir: StrPath | None = None,
        *,
        force: bool = False,
        tag_outputs: bool = False,
        dry_run: bool = False,
    ) -> PublishedArchivePaths | tuple[Path, StackPublishingRequest]:
        """Publish metadata and archives for specified layers."""
        layer_data: dict[
            LayerCategories, list[ArchiveMetadata | ArchiveBuildMetadata]
        ] = {
            RuntimeEnv.category: [],
            FrameworkEnv.category: [],
            ApplicationEnv.category: [],
        }
        archive_paths = []
        platform_tag = f"-{self.build_platform}" if tag_outputs else ""
        if output_dir is None:
            output_dir = self.build_path
        output_path = self.stack_spec.resolve_lexical_path(output_dir)
        metadata_dir = output_path / self.METADATA_DIR
        env_metadata_dir = metadata_dir / self.METADATA_ENV_DIR

        build_requests: list[tuple[LayerCategories, ArchiveBuildRequest]] = []
        for env in self.environments_to_publish():
            previous_metadata = self.load_archive_metadata(
                env_metadata_dir, env, platform_tag
            )
            build_requests.append(
                (
                    env.category,
                    env.define_archive_build(
                        output_path,
                        target_platform=self.build_platform,
                        tag_output=tag_outputs,
                        previous_metadata=previous_metadata,
                        force=force and not dry_run,
                    ),
                )
            )

        if dry_run:
            # Return metadata generated by a dry run rather than writing it to disk
            for category, build_request in build_requests:
                layer_data[category].append(build_request.build_metadata)
            publishing_request: StackPublishingRequest = {"layers": layer_data}
            return output_path, publishing_request
        # Build all requested archives and export the corresponding manifests
        output_path.mkdir(parents=True, exist_ok=True)
        result_data = cast(dict[LayerCategories, list[ArchiveMetadata]], layer_data)
        for category, build_request in build_requests:
            build_metadata, archive_path = build_request.create_archive()
            archive_paths.append(archive_path)
            result_data[category].append(build_metadata)
        manifest_data: StackPublishingResult = {"layers": result_data}
        manifest_path, snippet_paths = self._write_artifacts_manifest(
            metadata_dir, manifest_data, platform_tag
        )
        return PublishedArchivePaths(manifest_path, snippet_paths, archive_paths)

    def _write_archive_metadata(
        self,
        env_metadata_dir: StrPath,
        archive_metadata: ArchiveMetadata,
        platform_tag: str = "",
    ) -> Path:
        env_metadata_dir_path = self.stack_spec.resolve_lexical_path(env_metadata_dir)
        metadata_path = self._env_metadata_path(
            env_metadata_dir_path, archive_metadata["layer_name"], platform_tag
        )
        _write_json(metadata_path, archive_metadata)
        return metadata_path

    def _write_artifacts_manifest(
        self,
        metadata_dir: StrPath,
        manifest_data: StackPublishingResult,
        platform_tag: str = "",
    ) -> tuple[Path, list[Path]]:
        formatted_manifest = _format_json(manifest_data)
        # Save the full build metadata
        metadata_dir_path = self.stack_spec.resolve_lexical_path(metadata_dir)
        metadata_dir_path.mkdir(parents=True, exist_ok=True)
        manifest_path = metadata_dir_path / self.METADATA_MANIFEST
        if platform_tag:
            stem, sep, suffixes = manifest_path.name.partition(".")
            tagged_manifest_name = f"{stem}{platform_tag}{sep}{suffixes}"
            manifest_path = manifest_path.with_name(tagged_manifest_name)
        with manifest_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(formatted_manifest + "\n")
        # Save the environment snippets (some of these may also have been loaded from disk)
        env_metadata_dir = metadata_dir_path / self.METADATA_ENV_DIR
        env_metadata_dir.mkdir(parents=True, exist_ok=True)
        snippet_paths: list[Path] = []
        layer_metadata = manifest_data["layers"]
        for category in (
            LayerCategories.RUNTIMES,
            LayerCategories.FRAMEWORKS,
            LayerCategories.APPLICATIONS,
        ):
            for env in layer_metadata[category]:
                snippet_paths.append(
                    self._write_archive_metadata(env_metadata_dir, env, platform_tag)
                )
        return manifest_path, snippet_paths

    @overload
    def export_environments(
        self,
        output_dir: StrPath | None = ...,
        *,
        force: bool = ...,
        dry_run: Literal[False] = ...,
    ) -> ExportedEnvironmentPaths: ...
    @overload
    def export_environments(
        self,
        output_dir: StrPath | None = ...,
        *,
        force: bool = ...,
        dry_run: Literal[True] = ...,
    ) -> tuple[Path, StackExportRequest]: ...
    def export_environments(
        self,
        output_dir: StrPath | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> ExportedEnvironmentPaths | tuple[Path, StackExportRequest]:
        """Locally export environments for specified layers."""
        export_data: dict[LayerCategories, list[ExportMetadata]] = {
            RuntimeEnv.category: [],
            FrameworkEnv.category: [],
            ApplicationEnv.category: [],
        }
        export_paths = []
        if output_dir is None:
            output_dir = self.build_path
        output_path = self.stack_spec.resolve_lexical_path(output_dir)
        metadata_dir = output_path / self.METADATA_DIR
        env_metadata_dir = metadata_dir / self.METADATA_ENV_DIR

        export_requests: list[tuple[LayerCategories, LayerExportRequest]] = []
        for env in self.environments_to_publish():
            previous_metadata = self.load_export_metadata(env_metadata_dir, env)
            export_requests.append(
                (
                    env.category,
                    env.request_export(
                        output_path,
                        previous_metadata=previous_metadata,
                        force=force and not dry_run,
                    ),
                )
            )

        if dry_run:
            # Return metadata generated by a dry run rather than writing it to disk
            for category, export_request in export_requests:
                export_data[category].append(export_request.export_metadata)
            output_request: StackExportRequest = {"layers": export_data}
            return output_path, output_request
        # Export the requested environments and the corresponding manifests
        output_path.mkdir(parents=True, exist_ok=True)
        for category, export_request in export_requests:
            export_metadata, export_path = export_request.export_environment()
            export_paths.append(export_path)
            export_data[category].append(export_metadata)
        manifest_data: StackExportRequest = {"layers": export_data}
        manifest_path, snippet_paths = self._write_export_manifest(
            metadata_dir, manifest_data
        )
        return ExportedEnvironmentPaths(manifest_path, snippet_paths, export_paths)

    def _write_env_metadata(
        self,
        env_metadata_dir: StrPath,
        env_metadata: ExportMetadata,
        platform_tag: str = "",
    ) -> Path:
        env_metadata_dir_path = self.stack_spec.resolve_lexical_path(env_metadata_dir)
        metadata_path = self._env_metadata_path(
            env_metadata_dir_path, env_metadata["layer_name"], platform_tag
        )
        _write_json(metadata_path, env_metadata)
        return metadata_path

    def _write_export_manifest(
        self, metadata_dir: StrPath, manifest_data: StackExportRequest
    ) -> tuple[Path, list[Path]]:
        formatted_manifest = _format_json(manifest_data)
        # Save the full build metadata
        metadata_dir_path = self.stack_spec.resolve_lexical_path(metadata_dir)
        metadata_dir_path.mkdir(parents=True, exist_ok=True)
        manifest_path = metadata_dir_path / self.METADATA_MANIFEST
        with manifest_path.open("w", encoding="utf-8", newline="\n") as f:
            f.write(formatted_manifest + "\n")
        # Save the environment snippets (some of these may also have been loaded from disk)
        env_metadata_dir = metadata_dir_path / self.METADATA_ENV_DIR
        env_metadata_dir.mkdir(parents=True, exist_ok=True)
        snippet_paths: list[Path] = []
        env_metadata = manifest_data["layers"]
        for category in (
            LayerCategories.RUNTIMES,
            LayerCategories.FRAMEWORKS,
            LayerCategories.APPLICATIONS,
        ):
            for env in env_metadata[category]:
                snippet_paths.append(self._write_env_metadata(env_metadata_dir, env))
        return manifest_path, snippet_paths
