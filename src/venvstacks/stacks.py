#!/bin/python3
"""Portable Python environment stacks.

Creates Python runtime, framework, and app environments based on ``venvstacks.toml``
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import warnings

from abc import ABC, abstractmethod
from dataclasses import dataclass, field, InitVar
from datetime import datetime, timezone
from enum import StrEnum
from fnmatch import fnmatch
from itertools import chain
from pathlib import Path
from typing import (
    cast,
    overload,
    Any,
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

from . import pack_venv
from ._injected import postinstall
from ._util import (
    as_normalized_path,
    capture_python_output,
    default_tarfile_filter,
    find_shared_libraries,
    run_python_command,
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


class EnvStackError(ValueError):
    """Common base class for all errors specific to managing environment stacks."""


class LayerSpecError(EnvStackError):
    """Raised when an internal inconsistency is found in a layer specification."""


class BuildEnvError(EnvStackError):
    """Raised when a build environment doesn't comply with process restrictions."""


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


@dataclass
class PackageIndexConfig:
    """Python package index access configuration."""

    query_default_index: bool = field(default=True)
    local_wheel_dirs: InitVar[Sequence[StrPath] | None] = None
    local_wheel_paths: list[Path] = field(init=False)

    def __post_init__(self, local_wheel_dirs: Sequence[StrPath] | None) -> None:
        if isinstance(local_wheel_dirs, (str, Path)):
            err_msg = f"local_wheel_dirs must be a sequence of paths (got {local_wheel_dirs!r})"
            raise TypeError(err_msg)
        if local_wheel_dirs:
            self.local_wheel_paths = [Path(wheel_dir) for wheel_dir in local_wheel_dirs]
        else:
            self.local_wheel_paths = []

    @classmethod
    def disabled(cls) -> Self:
        """Package index configuration that disallows package installation."""
        return cls(
            query_default_index=False,
            local_wheel_dirs=None,
        )

    def resolve_lexical_paths(self, base_path: StrPath) -> None:
        """Lexically resolve paths in config relative to the given base path."""
        base_path = Path(base_path)
        self.local_wheel_paths[:] = [
            _resolve_lexical_path(path, base_path) for path in self.local_wheel_paths
        ]

    def _get_common_pip_args(self) -> list[str]:
        # Local wheel builds are expected for any source-only dependencies
        result = ["--only-binary", ":all:"]
        if not self.query_default_index:
            result.append("--no-index")
        for local_wheel_path in self.local_wheel_paths:
            result.extend(("--find-links", os.fspath(local_wheel_path)))
        return result

    def _get_uv_pip_compile_args(self) -> list[str]:
        return self._get_common_pip_args()

    def _get_pip_install_args(self) -> list[str]:
        return self._get_common_pip_args()


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


class EnvironmentLockMetadata(TypedDict):
    """Details of the last time this environment was locked."""

    # fmt: off
    locked_at: str          # ISO formatted date/time value
    requirements_hash: str  # Uses "algorithm:hexdigest" format
    lock_version: int       # Auto-incremented from previous lock metadata
    # fmt: on


_T = TypeVar("_T")


@dataclass
class EnvironmentLock:
    """Layered environment dependency locking management."""

    requirements_path: Path
    versioned: bool
    lock_metadata_path: Path = field(init=False, repr=False)
    _requirements_hash: str | None = field(init=False, repr=False)
    _last_locked: datetime | None = field(init=False, repr=False)
    _lock_version: int | None = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.lock_metadata_path = Path(f"{self.requirements_path}.json")
        self._requirements_hash = requirements_hash = self._hash_requirements()
        self._last_locked = self._get_last_locked_time(requirements_hash)
        self._lock_version = self._get_last_locked_version(requirements_hash)

    def get_deployed_name(self, env_name: EnvNameBuild) -> EnvNameDeploy:
        """Report layer name with lock version (if any) appended.

        Deployed name matches the build name if automatic lock versioning is disabled.
        """
        if self.versioned:
            return EnvNameDeploy(f"{env_name}@{self.lock_version}")
        return EnvNameDeploy(env_name)

    def _fail_lock(self, message: str) -> NoReturn:
        missing = self.requirements_path.name
        msg = f"Environment has not been locked ({missing} not found)"
        raise BuildEnvError(msg)

    def _raise_if_none(self, value: _T | None) -> _T:
        if value is None:
            self._fail_lock("Environment has not been locked")
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
    def is_locked(self) -> bool:
        """``True`` if layer requirements have been locked."""
        return self._last_locked is not None

    @property
    def locked_at(self) -> str:
        """ISO-formated UTC string reporting the last locked date/time."""
        return _format_as_utc(self.last_locked)

    def _hash_requirements(self) -> str | None:
        requirements_path = self.requirements_path
        if not requirements_path.exists():
            return None
        return _hash_file(self.requirements_path)

    def _load_saved_metadata(self) -> EnvironmentLockMetadata | None:
        """Loads last locked metadata from disk (if it exists)."""
        lock_metadata_path = self.lock_metadata_path
        if not lock_metadata_path.exists():
            return None
        with lock_metadata_path.open("r", encoding="utf-8") as f:
            # mypy is right to complain that the JSON hasn't been validated to conform to
            # the EnvironmentLockMetadata interface, but we're OK with letting the runtime
            # errors happen in that scenario. Longer term, explicit JSON schemas should be
            # defined and used for validation when reading the metadata files.
            return cast(EnvironmentLockMetadata, json.load(f))

    def load_valid_metadata(
        self, requirements_hash: str
    ) -> EnvironmentLockMetadata | None:
        """Loads last locked metadata only if the requirements hash matches."""
        lock_metadata = self._load_saved_metadata()
        if lock_metadata and requirements_hash == lock_metadata["requirements_hash"]:
            return lock_metadata
        return None

    def _get_last_locked_metadata(self, requirements_hash: str) -> datetime | None:
        lock_metadata = self.load_valid_metadata(requirements_hash)
        if lock_metadata is not None:
            return datetime.fromisoformat(lock_metadata["locked_at"])
        return None

    def _get_path_mtime(self) -> datetime | None:
        return _get_path_mtime(self.requirements_path)

    def _get_last_locked_time(self, requirements_hash: str | None) -> datetime | None:
        # Prefer the lock timestamp from an adjacent (still valid) lock metadata file
        if requirements_hash is not None:
            last_locked = self._get_last_locked_metadata(requirements_hash)
            if last_locked is not None:
                return last_locked
        # Otherwise assume the local file mtime reflects when the environment was locked
        # This will return None if the lock file doesn't exist yet
        return self._get_path_mtime()

    def _get_last_locked_version(self, requirements_hash: str | None) -> int | None:
        if requirements_hash is not None:
            lock_metadata = self.load_valid_metadata(requirements_hash)
            if lock_metadata is not None:
                # Unversioned specs are always considered version 1
                return lock_metadata.get("lock_version", 1)
        return None

    def _purge_lock(self) -> bool:
        # Currently a test suite helper, but may become a public API if it proves
        # useful when implementing https://github.com/lmstudio-ai/venvstacks/issues/10
        files_removed = False
        for path_to_remove in (self.requirements_path, self.lock_metadata_path):
            if path_to_remove.exists():
                path_to_remove.unlink()
                files_removed = True
        return files_removed

    def _write_lock_metadata(self) -> None:
        requirements_hash = self._requirements_hash
        if requirements_hash is None:
            self._fail_lock("Environment must be locked before writing lock metadata")
        last_version = self._lock_version
        if last_version is None:
            lock_version = 1
        elif self.versioned:
            lock_version = last_version + 1
        else:
            lock_version = last_version
        lock_metadata = EnvironmentLockMetadata(
            locked_at=self.locked_at,
            requirements_hash=requirements_hash,
            lock_version=lock_version,
        )
        _write_json(self.lock_metadata_path, lock_metadata)

    def update_lock_metadata(self) -> bool:
        """Update the recorded lock metadata for this environment lock."""
        # Calculate current requirements hash
        requirements_hash = self._hash_requirements()
        if requirements_hash is None:
            self._fail_lock("Environment must be locked before updating lock metadata")
        self._requirements_hash = requirements_hash
        # Only update and save the last locked time if
        # the lockfile contents have changed or if
        # the lock metadata file doesn't exist yet
        lock_metadata = self.load_valid_metadata(requirements_hash)
        if lock_metadata is None:
            self._last_locked = last_locked = self._get_path_mtime()
            assert last_locked is not None, (
                "Failed to read lock time for locked environment"
            )
            self._write_lock_metadata()
            return True
        return False


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
    env_metadata.setdefault("dynlib_exclude", [])


@dataclass
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
    dynlib_exclude: list[str] = field(repr=False)

    def __post_init__(self) -> None:
        # When instantiating specs that don't have a prefix,
        # they're not allowed to use prefixes that *are* defined
        if not self.ENV_PREFIX:
            spec_name = self.name
            for spec_type in LayerSpecBase.__subclasses__():
                reserved_prefix = spec_type.ENV_PREFIX
                if not reserved_prefix:
                    continue
                if spec_name.startswith(reserved_prefix + "-"):
                    err = f"{spec_name} starts with reserved prefix {reserved_prefix!r}"
                    raise ValueError(err)

    @property
    def env_name(self) -> EnvNameBuild:
        """Build environment name for this layer specification."""
        prefix = self.ENV_PREFIX
        if prefix:
            return EnvNameBuild(f"{prefix}-{self.name}")
        return EnvNameBuild(self.name)

    def get_requirements_fname(self, platform: str) -> str:
        """Locked requirements file name for this layer specification."""
        return f"requirements-{self.env_name}-{platform}.txt"

    def get_requirements_path(self, platform: str, requirements_dir: StrPath) -> Path:
        """Locked requirements path for this layer specification."""
        requirements_fname = self.get_requirements_fname(platform)
        return Path(requirements_dir) / self.env_name / requirements_fname


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
        )

    @staticmethod
    def _hash_archive(archive_path: Path) -> ArchiveHashes:
        hashes: dict[str, str] = {}
        for algorithm in ArchiveHashes.__required_keys__:
            hashes[algorithm] = _hash_file(archive_path, algorithm, omit_prefix=True)
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
            print(f"Using previously built archive at {str(built_archive_path)!r}")
            previous_metadata = self.archive_metadata
            assert previous_metadata is not None
            return previous_metadata, built_archive_path
        if built_archive_path.exists():
            print(f"Removing outdated archive at {str(built_archive_path)!r}")
            built_archive_path.unlink()
        print(f"Creating archive for {str(env_path)!r}")
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
        )
        assert built_archive_path == archive_path  # pack_venv ensures this is true
        print(f"Created {str(archive_path)!r} from {str(env_path)!r}")

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
            env_name, env_lock, env_path, export_path, export_metadata, needs_export
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
            print(f"Using previously exported environment at {str(export_path)!r}")
            return self.export_metadata, export_path
        if export_path.exists():
            print(f"Removing outdated environment at {str(export_path)!r}")
            export_path.unlink()
        print(f"Exporting {str(env_path)!r} to {str(export_path)!r}")

        def _run_postinstall(_export_path: Path, postinstall_path: Path) -> None:
            self._run_postinstall(postinstall_path)

        exported_path = pack_venv.export_venv(
            env_path,
            export_path,
            _run_postinstall,
        )
        assert self.export_path == exported_path  # pack_venv ensures this is true
        print(f"Created {str(export_path)!r} from {str(env_path)!r}")
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


def _hash_file(
    path: Path, algorithm: str = "sha256", *, omit_prefix: bool = False
) -> str:
    if not path.exists():
        return ""
    with path.open("rb", buffering=0) as f:
        file_hash = hashlib.file_digest(f, algorithm).hexdigest()
    if omit_prefix:
        return file_hash
    return f"{algorithm}:{file_hash}"


def _hash_directory(
    path: Path, algorithm: str = "sha256", *, omit_prefix: bool = False
) -> str:
    incremental_hash = hashlib.new(algorithm)
    # Python 3.11 compatibility: use os.walk instead of Path.walk
    for this_dir, subdirs, files in os.walk(path):
        if not files:
            continue
        dir_path = Path(this_dir)
        incremental_hash.update(dir_path.name.encode())
        # Ensure directory tree iteration order is deterministic
        subdirs.sort()
        for file in sorted(files):
            file_path = dir_path / file
            incremental_hash.update(file_path.name.encode())
            file_hash = _hash_file(file_path, algorithm)
            incremental_hash.update(file_hash.encode())
    dir_hash = incremental_hash.hexdigest()
    if omit_prefix:
        return dir_hash
    return f"{algorithm}/{dir_hash}"


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
    index_config: PackageIndexConfig = field(repr=False)

    # Derived from target path and spec in __post_init__
    env_path: Path = field(init=False)
    pylib_path: Path = field(init=False, repr=False)
    dynlib_path: Path | None = field(init=False, repr=False)
    executables_path: Path = field(init=False, repr=False)
    python_path: Path = field(init=False, repr=False)
    env_lock: EnvironmentLock = field(init=False)

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

    # State flags used to selectively execute some cleanup operations
    was_created: bool = field(default=False, init=False, repr=False)
    was_built: bool = field(default=False, init=False, repr=False)

    def _get_py_scheme_path(self, category: str) -> Path:
        return _get_py_scheme_path(category, self.env_path, self.py_version)

    def _get_python_dir_path(self) -> Path:
        # Dedicated method so subclasses can adjust this if needed
        return self._get_py_scheme_path("scripts")

    @property
    def env_name(self) -> EnvNameBuild:
        """The name of this environment in the build folder."""
        return self.env_spec.env_name

    @property
    def install_target(self) -> EnvNameDeploy:
        """The environment name used for this layer when deployed."""
        return self.env_lock.get_deployed_name(self.env_spec.env_name)

    def get_deployed_path(self, build_path: Path) -> str:
        """Get relative deployment location for a build env path."""
        env_deployed_path = Path(self.install_target)
        relative_path = build_path.relative_to(self.env_path)
        return str(env_deployed_path / relative_path)

    def __post_init__(self) -> None:
        # Concrete subclasses must set the version before finishing the base initialisation
        # Assert its existence here to make failures to do so easier to diagnose
        assert self.py_version is not None, "Subclass failed to set 'py_version'"
        self.env_path = self.build_path / self.env_name
        # Note: purelib and platlib are the same location in virtual environments
        # (even when they have different names, platlib is a symlink to purelib)
        self.pylib_path = self._get_py_scheme_path("purelib")
        self.executables_path = self._get_py_scheme_path("scripts")
        self.python_path = self._get_python_dir_path() / _binary_with_extension(
            "python"
        )
        if _WINDOWS_BUILD:
            # Windows DLL loading is typically handled via os.add_dll_directory()
            # Intel install some DLLs in a weird spot that needs extra config to handle
            self.dynlib_path = self.env_path / "Library" / "bin"
        else:
            # Allow POSIX extension modules to load shared libraries from lower layers
            self.dynlib_path = self.env_path / "share" / "venv" / "dynlib"
        self.env_lock = EnvironmentLock(
            self.requirements_path,
            self.env_spec.versioned,
        )
        # Ensure symlinks in the environment paths aren't inadvertently resolved
        assert self.pylib_path.relative_to(self.env_path)
        assert self.executables_path.relative_to(self.env_path)
        assert self.dynlib_path.relative_to(self.env_path)

    @property
    def env_spec(self) -> LayerSpecBase:
        """Layer specification for this environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        return self._env_spec

    @abstractmethod
    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        raise NotImplementedError

    def _get_deployed_config(
        self,
        pylib_dirs: Iterable[str],
        dynlib_dirs: Iterable[str],
        link_external_base: bool = True,
    ) -> postinstall.LayerConfig:
        # Helper for subclass get_deployed_config implementations
        base_python_path = self.base_python_path
        if base_python_path is None:
            self._fail_build("Cannot get deployment config for unlinked layer")
        build_env_path = self.env_path
        build_env_name = build_env_path.name
        build_path = build_env_path.parent

        def relative_to_env(relative_build_path: Path) -> str:
            # Input path is relative to the base of the build directory
            # Output path is relative to the base of the environment
            # Note: we avoid `walk_up=True` here, firstly to maintain
            #       Python 3.11 compatibility, but also to limit the
            #       the relative paths to *peer* environments, rather
            #       than all potentially valid relative path calculations
            if relative_build_path.is_absolute():
                self._fail_build(f"{relative_build_path} is not a relative path")
            if relative_build_path.parts[0] == build_env_name:
                # Emit internally relative path
                return str(Path(*relative_build_path.parts[1:]))
            # Emit relative reference to peer environment
            return str(Path("..", *relative_build_path.parts))

        def from_internal_path(target_build_path: Path) -> str:
            # Input path is an absolute path inside the environment
            # Output path is relative to the base of the environment
            return str(target_build_path.relative_to(build_env_path))

        def from_external_path(target_build_path: Path) -> str:
            # Input path is an absolute path, potentially from a peer environment
            # Output path is relative to the base of the environment
            relative_build_path = target_build_path.relative_to(build_path)
            return relative_to_env(relative_build_path)

        layer_python = from_internal_path(self.python_path)
        if link_external_base:
            base_python = from_external_path(base_python_path)
        else:
            # "base_python" in a runtime layer refers to the layer itself
            assert layer_python == from_internal_path(base_python_path)
            base_python = layer_python

        return postinstall.LayerConfig(
            python=layer_python,
            py_version=self.py_version,
            base_python=base_python,
            site_dir=from_internal_path(self.pylib_path),
            pylib_dirs=[relative_to_env(Path(d)) for d in pylib_dirs],
            dynlib_dirs=[relative_to_env(Path(d)) for d in dynlib_dirs],
        )

    def _write_deployed_config(self) -> None:
        # This is written as part of creating/updating the build environments
        config_path = self.env_path / postinstall.DEPLOYED_LAYER_CONFIG
        print(f"Generating {str(config_path)!r}...")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(config_path, self.get_deployed_config())

    def _fail_build(self, message: str) -> NoReturn:
        attributed_message = f"Layer {self.env_name}: {message}"
        raise BuildEnvError(attributed_message)

    def select_operations(
        self,
        lock: bool | None = False,
        build: bool | None = True,
        publish: bool = True,
        *,
        reset_lock: bool = False,
    ) -> None:
        """Enable the selected operations for this environment."""
        self.want_lock = lock
        self.want_lock_reset = reset_lock
        self.want_build = build
        self.want_publish = publish
        # Also reset operation state tracking
        self.was_created = False
        self.was_built = False

    def _create_environment(
        self, *, clean: bool = False, lock_only: bool = False
    ) -> None:
        env_path = self.env_path
        env_updated = False
        create_env = True
        if not env_path.exists():
            print(f"{str(env_path)!r} does not exist, creating...")
        elif clean:
            print(f"{str(env_path)!r} exists, replacing...")
            shutil.rmtree(self.env_path)
        else:
            if self.want_build or self.was_created:
                # Run the update if requested, or if env was created earlier in the build
                print(f"{str(env_path)!r} exists, updating...")
                self._update_existing_environment(lock_only=lock_only)
                env_updated = True
            else:
                print(f"{str(env_path)!r} exists, reusing without updating...")
            create_env = False
        if create_env:
            self._create_new_environment(lock_only=lock_only)
        self._write_deployed_config()
        self.was_created = create_env
        self.was_built = create_env or env_updated

    def create_environment(self, clean: bool = False) -> None:
        """Create or update specified environment. Returns True if env is new or updated."""
        self._create_environment(clean=clean)
        self._ensure_portability()

    def report_python_site_details(self) -> subprocess.CompletedProcess[str]:
        """Print the results of running ``python -m site`` in this environment."""
        print(f"Reporting environment details for {str(self.env_path)!r}")
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
        ]
        return run_python_command(command, **kwds)

    def _run_uv_pip(
        self, cmd_args: list[str], **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        return self._run_uv("pip", cmd_args, **kwds)

    def _run_uv_pip_compile(
        self,
        requirements_path: StrPath,
        requirements_input_path: StrPath,
        constraints: Sequence[StrPath],
    ) -> subprocess.CompletedProcess[str]:
        # TODO: Explore whether resolution in `--universal` mode might eliminate the
        #       need for per-platform lock files (it depends on whether `uv` is assuming
        #       dependency declarations don't vary across wheels, which is not a valid
        #       assumption for some Python packages, including `pytorch`)
        cli_lock_command = f"{Path(sys.executable).name} -Im {__package__} lock"
        uv_pip_args = [
            "compile",
            "-o",
            os.fspath(requirements_path),
            "--python",
            str(self.base_python_path),
            "--python-version",
            self.py_version,
            "--custom-compile-command",
            cli_lock_command,
            *self.index_config._get_uv_pip_compile_args(),
            "--quiet",
            "--no-color",
            "--no-config",
            "--no-annotate",  # Annotations include file paths, creating portability problems
            "--generate-hashes",
            "--strip-extras",
            "--no-upgrade",  # Delete the existing lock files to upgrade dependencies
            "--allow-unsafe",  # Despite the name, this turns off an unwanted legacy behaviour
            # that disallowed pinning some packaging related PyPI projects
        ]
        for constraint_path in constraints:
            uv_pip_args.extend(("-c", os.fspath(constraint_path)))
        uv_pip_args.append(os.fspath(requirements_input_path))
        return self._run_uv_pip(uv_pip_args)

    def _run_pip(
        self, cmd_args: list[str], **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(self.tools_python_path),
            "-X",
            "utf8",
            "-Im",
            "pip",
            "--python",
            str(self.python_path),
            "--no-input",
            *cmd_args,
        ]
        return run_python_command(command, **kwds)

    def _run_pip_install(
        self, *pip_install_args: str
    ) -> subprocess.CompletedProcess[str]:
        # TODO: Switch to `uv pip install` once https://github.com/astral-sh/uv/issues/2500
        #       is resolved (so environment layering is still handled correctly)
        # Requirements are fully transitively locked, so no implicit deps are allowed
        # Implicit source builds are not supported (use local wheel dirs instead)
        pip_args = [
            "install",
            "--no-warn-script-location",
            *self.index_config._get_pip_install_args(),
            "--no-deps",
            "--upgrade",
            *pip_install_args,
        ]
        result = self._run_pip(pip_args)
        print(f"Dependencies installed and updated in {str(self.env_path)!r}")
        return result

    def get_constraint_paths(self) -> list[Path]:
        """Get the lower level layer constraints imposed on this environment."""
        # No constraints files by default, subclasses override as necessary
        return []

    def needs_lock(self, platform: str, requirements_dir: StrPath) -> bool:
        """Returns true if this environment needs to be locked."""
        if self.want_lock is False:
            # Locking step has been explicitly disabled, so override the check
            # Later steps will fail if the lock file is needed but missing
            return False
        if self.want_lock_reset:
            # If the lock is to be reset, then locking is needed unless
            # the lock operation has been explicitly disabled
            return True
        # If the lock is not to be reset, then locking is needed
        # if the locked requirements file doesn't already exist
        lock_path = self.env_spec.get_requirements_path(platform, requirements_dir)
        return not lock_path.exists()

    def lock_requirements(self) -> EnvironmentLock:
        """Transitively lock the requirements for this environment."""
        spec = self.env_spec
        requirements_path = self.requirements_path
        if not self.want_lock and requirements_path.exists():
            print(f"Using existing {str(requirements_path)!r}")
            return self.env_lock
        print(f"Generating {str(requirements_path)!r}")
        requirements_path.parent.mkdir(parents=True, exist_ok=True)
        constraints = self.get_constraint_paths()
        requirements_input_path = requirements_path.with_suffix(".in")
        with requirements_input_path.open("w", encoding="utf-8", newline="\n") as f:
            lines = [
                "# DO NOT EDIT. Automatically generated by venvstacks.",
                "#              Relock layer dependencies to update.",
                *spec.requirements,
                "",
            ]
            f.write("\n".join(lines))
        if self.want_lock_reset and requirements_path.exists():
            print(f"Removing previous {str(requirements_path)!r}")
            requirements_path.unlink()
        self._run_uv_pip_compile(
            requirements_path, requirements_input_path, constraints
        )
        if not requirements_path.exists():
            self._fail_build(f"Failed to generate {str(requirements_path)!r}")
        # TODO: Also emit a summary file with just the version details (no hashes)
        #       https://github.com/lmstudio-ai/venvstacks/issues/108
        if self.env_lock.update_lock_metadata():
            print(f"  Environment lock time set: {self.env_lock.locked_at!r}")
        return self.env_lock

    def install_requirements(self) -> subprocess.CompletedProcess[str]:
        """Install the locked layer requirements into this environment.

        Note: assumes dependencies have already been installed into linked layers.
        """
        # Run a pip dependency upgrade inside the target environment
        if not self.env_lock.is_locked:
            self._fail_build(
                "Environment must be locked before installing dependencies"
            )
        install_result = self._run_pip_install(
            "-r",
            str(self.requirements_path),
        )
        if not _WINDOWS_BUILD:
            # TODO: Add a shared library exclusion mechanism
            symlink_dir_path = self.dynlib_path
            if symlink_dir_path is None:
                self._fail_build(
                    "Environments must be linked before installing dependencies"
                )
            for so_path in find_shared_libraries(
                self.py_version, self.pylib_path, excluded=self.env_spec.dynlib_exclude
            ):
                symlink_path = symlink_dir_path / so_path.name
                if symlink_path.exists():
                    if not symlink_path.is_symlink():
                        self._fail_build(
                            f"{str(symlink_path)!r} already exists and is not a symlink"
                        )
                    target_path = symlink_path.readlink()
                    if not target_path.samefile(so_path):
                        self._fail_build(
                            f"{str(symlink_path)!r} already exists, but links to {str(target_path)!r}, not {str(so_path)!r}"
                        )
                else:
                    symlink_path.parent.mkdir(exist_ok=True, parents=True)
                    symlink_path.symlink_to(so_path)
        return install_result

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        if not lock_only:
            self.install_requirements()

    @abstractmethod
    def _create_new_environment(self, *, lock_only: bool = False) -> None:
        raise NotImplementedError

    def _ensure_portability(self) -> None:
        # Wrapper and activation scripts are not used on deployment targets,
        # so drop them entirely rather than making them portable
        for item in self.executables_path.iterdir():
            if item.is_dir():
                print(f"    Dropping directory {str(item)!r}")
                shutil.rmtree(item)
            elif not item.name.lower().startswith("python"):
                print(f"    Dropping potentially non-portable file {str(item)!r}")
                item.unlink()
        # Symlinks within the build folder should be relative
        # Symlinks outside the build folder shouldn't exist
        build_path = self.build_path
        relative, external = pack_venv.convert_symlinks(self.env_path, build_path)
        if relative:
            msg_lines = ["Converted absolute internal symlinks to relative symlinks:\n"]
            for file_path, target_path in relative:
                link_info = f"{str(file_path)!r} -> {str(target_path)!r}"
                msg_lines.append(f"  {link_info}")
            print("\n".join(msg_lines))
        if external:
            msg_lines = ["Converted absolute external symlinks to hard links:\n"]
            for file_path, target_path in external:
                link_info = f"{str(file_path)!r} -> {str(target_path)!r}"
                msg_lines.append(f"  {link_info}")
            print("\n".join(msg_lines))

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        # Hook for subclasses to override
        assert metadata is not None  # Avoid linter complaints about unused parameters

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

    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        return self._get_deployed_config([], [], link_external_base=False)

    def _remove_pip(self) -> subprocess.CompletedProcess[str] | None:
        to_be_checked = ["pip", "wheel", "setuptools"]
        to_be_removed = []
        for pylib in to_be_checked:
            if (self.pylib_path / pylib).exists():
                to_be_removed.append(pylib)
        if not to_be_removed:
            return None
        pip_args = ["uninstall", "-y", *to_be_removed]
        return self._run_pip(pip_args)

    def _create_new_environment(self, *, lock_only: bool = False) -> None:
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
            print(
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

    @property
    def env_spec(self) -> LayeredSpecBase:
        """Layer specification for this environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, LayeredSpecBase)
        return self._env_spec

    def _linked_environments(self) -> Iterator[LayerEnvBase]:
        # Linked frameworks are emitted before the base runtime layer
        for fw_env in self.linked_frameworks:
            yield fw_env
        # This is only ever invoked *after* the environment has been linked
        runtime_env = self.base_runtime
        assert runtime_env is not None
        yield runtime_env

    def _iter_build_pylib_dirs(self) -> Iterator[str]:
        for env in self._linked_environments():
            yield str(env.pylib_path.relative_to(self.build_path))

    def _iter_build_dynlib_dirs(self) -> Iterator[str]:
        for env in self._linked_environments():
            dynlib_path = env.dynlib_path
            if dynlib_path is not None:
                yield str(dynlib_path.relative_to(self.build_path))

    def _iter_deployed_pylib_dirs(self) -> Iterator[str]:
        for env in self._linked_environments():
            yield env.get_deployed_path(env.pylib_path)

    def _iter_deployed_dynlib_dirs(self) -> Iterator[str]:
        for env in self._linked_environments():
            dynlib_path = env.dynlib_path
            if dynlib_path is not None:
                yield env.get_deployed_path(dynlib_path)

    def link_base_runtime(self, runtime: RuntimeEnv) -> None:
        """Link this layered environment to its base runtime environment."""
        if self.base_runtime is not None:
            raise BuildEnvError(
                f"Layered environment base runtime already linked {self}"
            )
        # Link the runtime environment
        self.base_runtime = runtime
        # Link executable paths
        self.base_python_path = runtime.python_path
        # Link runtime layer dependency constraints
        if self.linked_constraints_paths:
            self._fail_build("Layered environment base runtime already linked")
        self.linked_constraints_paths[:] = [runtime.requirements_path]
        print(f"Linked {self}")

    def link_layered_environments(
        self, runtime: RuntimeEnv, frameworks: Mapping[LayerBaseName, "FrameworkEnv"]
    ) -> None:
        """Link this application build environment with its runtime and framework layers."""
        self.link_base_runtime(runtime)
        constraints_paths = self.linked_constraints_paths
        if not constraints_paths:
            self._fail_build("Failed to add base environment constraints path")
        # The runtime site-packages folder is added here rather than via pyvenv.cfg
        # to ensure it appears in sys.path after the framework site-packages folders
        fw_envs = self.linked_frameworks
        if fw_envs:
            self._fail_build("Layered application environment already linked")
        for env_spec in self.env_spec.frameworks:
            env = frameworks[env_spec.name]
            fw_envs.append(env)
            constraints_paths.append(env.requirements_path)

    def get_deployed_config(self) -> postinstall.LayerConfig:
        """Layer config to be published in `venvstacks_layer.json`."""
        return self._get_deployed_config(
            self._iter_deployed_pylib_dirs(), self._iter_deployed_dynlib_dirs()
        )

    def get_constraint_paths(self) -> list[Path]:
        """Get the lower level layer constraints imposed on this environment."""
        return self.linked_constraints_paths

    def _ensure_virtual_environment(self) -> subprocess.CompletedProcess[str]:
        # Use the base Python installation to create a new virtual environment
        if self.base_python_path is None:
            self._fail_build("Base Python path not set")
        options = ["--without-pip"]
        if self.env_path.exists():
            options.append("--upgrade")
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
        result = run_python_command(command)
        self._link_build_environment()
        _fs_sync()
        print(f"Virtual environment configured in {str(self.env_path)!r}")
        return result

    def _link_build_environment(self) -> None:
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
        print(f"Generating {str(sc_path)!r}...")
        sc_path.write_text(sc_contents, encoding="utf-8")
        if not _WINDOWS_BUILD and build_dynlib_paths:
            # Allow shared library loading in POSIX environments
            base_python_path = self.base_python_path
            if base_python_path is None:
                self._fail_build(
                    "Layered environments must at least link a base runtime environment"
                )
            sh_path = self.python_path
            wrapper_info = postinstall.generate_python_sh(sh_path, build_dynlib_paths)
            assert wrapper_info is not None
            sh_contents, symlink_path = wrapper_info
            print(f"Renaming {str(sh_path)!r} -> {str(symlink_path)!r}...")
            sh_path.rename(symlink_path)
            print(f"Generating {str(sh_path)!r}...")
            sh_path.write_text(sh_contents, encoding="utf-8")
            os.chmod(sh_path, 0x755)

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        if lock_only:
            raise BuildEnvError(
                "Only runtime environments support lock-only installation"
            )
        self._ensure_virtual_environment()
        super()._update_existing_environment()

    def _create_new_environment(self, *, lock_only: bool = False) -> None:
        self._update_existing_environment(lock_only=lock_only)

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        super()._update_output_metadata(metadata)
        # Non-windows platforms use symlinks, so only need updates on feature releases
        # Windows copies the main Python binary and support libary, so always needs updates
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

    @property
    def env_spec(self) -> ApplicationSpec:
        """Layer specification for this application build environment."""
        # Define property to allow covariance of the declared type of `env_spec`
        assert isinstance(self._env_spec, ApplicationSpec)
        return self._env_spec

    def __post_init__(self) -> None:
        super().__post_init__()
        self.launch_module_name = self.env_spec.launch_module_path.stem

    def _update_existing_environment(self, *, lock_only: bool = False) -> None:
        super()._update_existing_environment(lock_only=lock_only)
        # Also publish the specified launch module as an importable top level module
        launch_module_source_path = self.env_spec.launch_module_path
        launch_module_env_path = self.pylib_path / launch_module_source_path.name
        print(f"Including launch module {launch_module_source_path!r}...")
        if launch_module_source_path.is_file():
            shutil.copyfile(launch_module_source_path, launch_module_env_path)
        else:
            shutil.copytree(
                launch_module_source_path, launch_module_env_path, dirs_exist_ok=True
            )

    def _update_output_metadata(self, metadata: LayerSpecMetadata) -> None:
        super()._update_output_metadata(metadata)
        metadata["app_launch_module"] = self.launch_module_name
        if self.env_spec.launch_module_path.is_file():
            metadata["app_launch_module_hash"] = _hash_file(
                self.env_spec.launch_module_path
            )
        else:
            metadata["app_launch_module_hash"] = _hash_directory(
                self.env_spec.launch_module_path
            )


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

    # Derived from runtime environment in __post_init__
    build_platform: str = field(init=False, repr=False)

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
    ) -> tuple[RuntimeSpec, tuple[FrameworkSpec, ...]]:
        declared_runtime: LayerBaseName | None = declared_spec.get("runtime")
        declared_frameworks: Sequence[LayerBaseName] | None = declared_spec.get(
            "frameworks"
        )
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
        elif not declared_frameworks:
            msg = f"{err_prefix} must specify a runtime or at least one framework dependency"
            raise LayerSpecError(msg)
        else:
            declared_fw_deps: list[FrameworkSpec] = []
            for fw_name in declared_frameworks:
                fw_spec = frameworks.get(fw_name)
                if fw_spec is None:
                    msg = f"{err_prefix} references unknown framework {fw_name!r}"
                    raise LayerSpecError(msg)
                if runtime_dep is None:
                    runtime_dep = fw_spec.runtime
                elif fw_spec.runtime is not runtime_dep:
                    msg = (
                        f"{err_prefix} references inconsistent frameworks. "
                        f"{declared_fw_deps[0].name!r} requires runtime {runtime_dep.name!r}."
                        f"while {fw_spec.name!r} requires runtime {fw_spec.runtime.name!r}."
                    )
                    raise LayerSpecError(msg)
                declared_fw_deps.append(fw_spec)
            framework_deps = cls._linearize_C3(err_prefix, declared_fw_deps)
            assert runtime_dep is not None
        return runtime_dep, framework_deps

    @classmethod
    def load(cls, fname: StrPath) -> Self:
        """Load stack specification from given TOML file."""
        stack_spec_path = as_normalized_path(fname)
        with open(stack_spec_path, "rb") as f:
            data = tomllib.load(f)
        spec_dir_path = stack_spec_path.parent
        requirements_dir_path = spec_dir_path / "requirements"
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
            runtime_dep, framework_deps = cls._resolve_layer_deps(
                err_prefix, fw, runtimes, frameworks
            )
            fw["runtime"] = runtime_dep
            fw["frameworks"] = framework_deps
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
            launch_module_path = spec_dir_path / app.pop("launch_module")
            if not launch_module_path.exists():
                msg = f"Specified launch module {str(launch_module_path)!r} does not exist)"
                raise LayerSpecError(msg)
            err_prefix = f"Application {name!r}"
            runtime_dep, framework_deps = cls._resolve_layer_deps(
                err_prefix, app, runtimes, frameworks
            )
            app["runtime"] = runtime_dep
            app["frameworks"] = framework_deps
            app["launch_module_path"] = launch_module_path
            ensure_optional_env_spec_fields(app)
            applications[name] = ApplicationSpec(**app)
        return cls(
            stack_spec_path, runtimes, frameworks, applications, requirements_dir_path
        )

    def all_environment_specs(self) -> Iterable[LayerSpecBase]:
        """Iterate over the specifications for all defined environments.

        All runtimes are produced first, then frameworks, then applications.
        """
        return chain(
            self.runtimes.values(), self.frameworks.values(), self.applications.values()
        )

    def _define_envs(
        self,
        build_path: Path,
        index_config: PackageIndexConfig,
        env_class: type[BuildEnv],
        specs: Mapping[LayerBaseName, LayerSpecBase],
    ) -> MutableMapping[LayerBaseName, BuildEnv]:
        requirements_dir = self.requirements_dir_path
        build_environments: dict[LayerBaseName, BuildEnv] = {}
        build_platform = self.build_platform
        for name, spec in specs.items():
            if build_platform not in spec.platforms:
                print(f"  Skipping env {name!r} as it does not target this platform")
                continue
            requirements_path = spec.get_requirements_path(
                build_platform, requirements_dir
            )
            build_env = env_class(spec, build_path, requirements_path, index_config)
            build_environments[name] = build_env
            print(f"  Defined {name!r}: {build_env!r}")
        return build_environments

    def resolve_lexical_path(self, related_location: StrPath, /) -> Path:
        """Resolve a path relative to the location of the stack specification."""
        return _resolve_lexical_path(related_location, self.spec_path.parent)

    def define_build_environment(
        self,
        build_dir: StrPath = "",
        index_config: PackageIndexConfig | None = None,
    ) -> "BuildEnvironment":
        """Define layer build environments for this specification."""
        build_path = self.resolve_lexical_path(build_dir)
        if index_config is None:
            index_config = PackageIndexConfig()
        index_config.resolve_lexical_paths(self.spec_path.parent)
        print("Defining runtime environments:")
        runtimes = self._define_envs(
            build_path, index_config, RuntimeEnv, self.runtimes
        )
        print("Defining framework environments:")
        frameworks = self._define_envs(
            build_path, index_config, FrameworkEnv, self.frameworks
        )
        for fw_env in frameworks.values():
            runtime = runtimes[fw_env.env_spec.runtime.name]
            fw_env.link_layered_environments(runtime, frameworks)
        print("Defining application environments:")
        applications = self._define_envs(
            build_path, index_config, ApplicationEnv, self.applications
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
    def all_environments(self) -> Iterable[LayerEnvBase]:
        """Iterate over all defined environments.

        All runtimes are produced first, then frameworks, then applications.
        """
        return chain(
            self.runtimes.values(), self.frameworks.values(), self.applications.values()
        )

    def environments_to_lock(self) -> Iterable[LayerEnvBase]:
        """Iterate over all environments where locking is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.want_lock is not False:  # Accepts `None` as meaning "lock if needed"
                yield env

    def runtimes_to_lock(self) -> Iterable[RuntimeEnv]:
        """Iterate over runtime environments where locking is requested or allowed."""
        for env in self.runtimes.values():
            if env.want_lock is not False:  # Accepts `None` as meaning "lock if needed"
                yield env

    def environments_to_build(self) -> Iterable[LayerEnvBase]:
        """Iterate over all environments where building is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def runtimes_to_build(self) -> Iterable[RuntimeEnv]:
        """Iterate over runtime environments where building is requested or allowed."""
        for env in self.runtimes.values():
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def venvstacks_to_build(self) -> Iterable[LayeredEnvBase]:
        """Iterate over non-runtime environments where building is requested or allowed.

        Frameworks are produced first, then applications.
        """
        for env in chain(self.frameworks.values(), self.applications.values()):
            if (
                env.want_build is not False
            ):  # Accepts `None` as meaning "build if needed"
                yield env

    def built_environments(self) -> Iterable[LayerEnvBase]:
        """Iterate over all environments that were built by this build process.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.was_built:
                yield env

    def environments_to_publish(self) -> Iterable[LayerEnvBase]:
        """Iterate over all environments where publication is requested or allowed.

        Runtimes are produced first, then frameworks, then applications.
        """
        for env in self.all_environments():
            if env.want_publish:  # There's no "if needed" option for publication
                yield env

    # Assign environments to the different operation categories
    def select_operations(
        self,
        lock: bool | None = False,
        build: bool | None = True,
        publish: bool = True,
        *,
        reset_locks: bool = False,
    ) -> None:
        """Configure the selected operations on all defined environments."""
        for env in self.all_environments():
            env.select_operations(
                lock=lock, build=build, publish=publish, reset_lock=reset_locks
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
        reset_locks: Iterable[str] = (),
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
                env.select_operations(lock=False, build=False, publish=False)
        # Enable operations on related layers if requested
        # Dependencies are always checked so they can be set to "if needed" locks & builds
        check_derived = lock_derived or build_derived or publish_derived
        derived_envs: set[EnvNameBuild] = set()
        dependency_envs: set[EnvNameBuild] = set()
        # Check frameworks
        for fw_env in self.frameworks.values():
            env_name = fw_env.env_name
            rt_env_name = fw_env.env_spec.runtime.env_name
            if env_name in included_envs:
                # This env is included, check if any of its dependencies need inclusion
                if rt_env_name not in included_envs:
                    dependency_envs.add(rt_env_name)
            elif check_derived:
                # Check for the runtime this env depends on being included
                if rt_env_name in included_envs:
                    derived_envs.add(env_name)
        # Check applications
        for app_env in self.applications.values():
            env_name = app_env.env_name
            app_spec = app_env.env_spec
            rt_env_name = app_spec.runtime.env_name
            fw_env_names = [fw_spec.env_name for fw_spec in app_spec.frameworks]
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
                lock=lock_derived, build=build_derived, publish=publish_derived
            )
        # Dependencies are always allowed to be locked or built implicitly
        # (this only happens if the operation's outputs don't exist yet)
        for env_name in dependency_envs:
            env = envs_by_name[env_name]
            env.select_operations(
                lock=lock_dependencies or None,    # Allow locking if neeeded
                build=build_dependencies or None,  # Allow building if needed
                publish=publish_dependencies,      # No implicit publication
            )  # fmt: skip

    # Define the various operations on the included environments
    def _needs_lock(self) -> bool:
        spec_dir = self.requirements_dir_path
        build_platform = self.build_platform

        return any(
            env.needs_lock(build_platform, spec_dir)
            for env in self.environments_to_lock()
        )

    def lock_environments(self, *, clean: bool = False) -> Sequence[EnvironmentLock]:
        """Lock build environments for specified layers."""
        # Lock environments without fully building them
        # Necessarily creates the runtime environments and
        # installs any declared build dependencies
        self.requirements_dir_path.mkdir(parents=True, exist_ok=True)
        for rt_env in self.runtimes_to_lock():
            rt_env.create_build_environment(clean=clean)
        return [env.lock_requirements() for env in self.environments_to_lock()]

    def create_environments(self, *, clean: bool = False, lock: bool = False) -> None:
        """Create build environments for specified layers."""
        # Base runtime environments need to exist before dependencies can be locked
        self.build_path.mkdir(parents=True, exist_ok=True)
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
