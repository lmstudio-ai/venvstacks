"""Test building the minimal project produces the expected results."""

import json
import shutil
import sys
import tempfile

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

# Use unittest for consistency with test_sample_project (which needs the better diff support)
import unittest
from unittest.mock import Mock

import pytest  # To mark slow test cases

from support import (
    ApplicationEnvSummary,
    DeploymentTestCase,
    EnvSummary,
    LayeredEnvSummary,
    ManifestData,
    SpecLoadingTestCase,
    make_mock_index_config,
    get_sys_path,
)

from venvstacks.stacks import (
    ArchiveBuildMetadata,
    ArchiveMetadata,
    StackPublishingRequest,
    BuildEnvError,
    BuildEnvironment,
    EnvNameBuild,
    EnvNameDeploy,
    StackSpec,
    StackStatus,
    PackageIndexConfig,
    PublishedArchivePaths,
    get_build_platform,
)
from venvstacks._util import get_env_python, capture_python_output, WINDOWS_BUILD

##################################
# Minimal project test helpers
##################################

_THIS_PATH = Path(__file__)
MINIMAL_PROJECT_PATH = _THIS_PATH.parent / "minimal_project"
MINIMAL_PROJECT_STACK_SPEC_PATH = MINIMAL_PROJECT_PATH / "venvstacks.toml"
MINIMAL_PROJECT_PATHS = (
    MINIMAL_PROJECT_STACK_SPEC_PATH,
    MINIMAL_PROJECT_PATH / "empty.py",
)


def _copy_project_input_files(working_path: Path) -> None:
    """Copy the input files for the project to the given temporary folder."""
    # To avoid side effects from lock file creation, copy project files to the working path
    # This also means these tests cover the "export to the same filesystem" case
    # on all systems (temp folder -> temp folder)
    for src_path in MINIMAL_PROJECT_PATHS:
        dest_path = working_path / src_path.name
        shutil.copyfile(src_path, dest_path)


def _define_build_env(working_path: Path) -> BuildEnvironment:
    """Define a build environment for the sample project in a temporary folder."""
    _copy_project_input_files(working_path)
    # Include "/../" in the spec path in order to test relative path resolution when
    # accessing the Python executables (that can be temperamental, especially on macOS).
    # The subdirectory won't be used for anything, so it being missing shouldn't matter.
    working_spec_path = working_path / "_unused_dir/../venvstacks.toml"
    stack_spec = StackSpec.load(working_spec_path)
    build_path = working_path / "_build🐸"
    return stack_spec.define_build_environment(build_path)


##################################
# Expected stack definitions
##################################

EXPECTED_RUNTIMES = [
    EnvSummary("cpython-3.11", ""),
]

EXPECTED_FRAMEWORKS = [
    LayeredEnvSummary("layerA", "framework-", "cpython-3.11", ()),
    LayeredEnvSummary("layerB", "framework-", "cpython-3.11", ("layerA",)),
    LayeredEnvSummary("layerC", "framework-", "cpython-3.11", ("layerA",)),
    LayeredEnvSummary(
        "layerD", "framework-", "cpython-3.11", ("layerB", "layerC", "layerA")
    ),
    LayeredEnvSummary("layerE", "framework-", "cpython-3.11", ("layerB", "layerA")),
    LayeredEnvSummary(
        "layerF", "framework-", "cpython-3.11", ("layerE", "layerB", "layerA")
    ),
]

EXPECTED_APPLICATIONS = [
    ApplicationEnvSummary(
        "empty",
        "app-",
        "cpython-3.11",
        ("layerD", "layerF", "layerE", "layerB", "layerC", "layerA"),
    ),
    ApplicationEnvSummary("no-framework", "app-", "cpython-3.11", ()),
]

EXPECTED_ENVIRONMENTS = EXPECTED_RUNTIMES.copy()
EXPECTED_ENVIRONMENTS.extend(EXPECTED_FRAMEWORKS)
EXPECTED_ENVIRONMENTS.extend(EXPECTED_APPLICATIONS)

EXPECTED_STACK_STATUS: StackStatus = {
  "applications": [
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("app-empty"),
      "name": EnvNameBuild("app-empty"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("app-no-framework"),
      "name": EnvNameBuild("app-no-framework"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
  ],
  "frameworks": [
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerA"),
      "name": EnvNameBuild("framework-layerA"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerB"),
      "name": EnvNameBuild("framework-layerB"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerC"),
      "name": EnvNameBuild("framework-layerC"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerD"),
      "name": EnvNameBuild("framework-layerD"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerE"),
      "name": EnvNameBuild("framework-layerE"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("framework-layerF"),
      "name": EnvNameBuild("framework-layerF"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
  ],
  "runtimes": [
    {
      "has_valid_lock": False,
      "install_target": EnvNameDeploy("cpython-3.11"),
      "name": EnvNameBuild("cpython-3.11"),
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
  ],
  "spec_name": str(MINIMAL_PROJECT_STACK_SPEC_PATH),
}

# The expected manifest here omits all content dependent fields
# (those are checked when testing the full sample project)
ArchiveSummary = dict[str, Any]
ArchiveSummaries = dict[str, list[ArchiveSummary]]
BuildManifest = dict[str, ArchiveSummaries]
ARCHIVE_SUFFIX = ".zip" if WINDOWS_BUILD else ".tar.xz"
BUILD_PLATFORM = str(get_build_platform())
EXPECTED_MANIFEST: BuildManifest = {
    "layers": {
        "applications": [
            {
                "app_launch_module": "empty",
                "archive_build": 1,
                "install_target": "app-empty",
                "archive_name": f"app-empty{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerD",
                    "framework-layerF",
                    "framework-layerE",
                    "framework-layerB",
                    "framework-layerC",
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "app_launch_module": "empty",
                "archive_build": 1,
                "install_target": "app-no-framework",
                "archive_name": f"app-no-framework{ARCHIVE_SUFFIX}",
                "required_layers": [],
                "target_platform": BUILD_PLATFORM,
            },
        ],
        "frameworks": [
            {
                "archive_build": 1,
                "install_target": "framework-layerA",
                "archive_name": f"framework-layerA{ARCHIVE_SUFFIX}",
                "required_layers": [],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "archive_build": 1,
                "install_target": "framework-layerB",
                "archive_name": f"framework-layerB{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "archive_build": 1,
                "install_target": "framework-layerC",
                "archive_name": f"framework-layerC{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "archive_build": 1,
                "install_target": "framework-layerD",
                "archive_name": f"framework-layerD{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerB",
                    "framework-layerC",
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "archive_build": 1,
                "install_target": "framework-layerE",
                "archive_name": f"framework-layerE{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerB",
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
            {
                "archive_build": 1,
                "install_target": "framework-layerF",
                "archive_name": f"framework-layerF{ARCHIVE_SUFFIX}",
                "required_layers": [
                    "framework-layerE",
                    "framework-layerB",
                    "framework-layerA",
                ],
                "target_platform": BUILD_PLATFORM,
            },
        ],
        "runtimes": [
            {
                "archive_build": 1,
                "install_target": "cpython-3.11",
                "archive_name": f"cpython-3.11{ARCHIVE_SUFFIX}",
                "target_platform": BUILD_PLATFORM,
            },
        ],
    }
}

LastLockedTimes = dict[str, datetime]  # Mapping from install target names to lock times
_CHECKED_KEYS = frozenset(EXPECTED_MANIFEST["layers"]["applications"][0])


def _filter_archive_manifest(archive_manifest: ArchiveBuildMetadata) -> ArchiveSummary:
    """Drop archive manifest fields that aren't covered by this set of test cases."""
    summary: ArchiveSummary = {}
    for key in _CHECKED_KEYS:
        value = archive_manifest.get(key)
        if value is not None:
            summary[key] = value
    return summary


def _filter_manifest(
    manifest: StackPublishingRequest,
) -> tuple[BuildManifest, LastLockedTimes]:
    """Extract manifest fields that are relevant to this set of test cases."""
    filtered_summaries: ArchiveSummaries = {}
    last_locked_times: LastLockedTimes = {}
    for kind, archive_manifests in manifest["layers"].items():
        filtered_summaries[kind] = summaries = []
        for archive_manifest in archive_manifests:
            summaries.append(_filter_archive_manifest(archive_manifest))
            last_locked_times[archive_manifest["install_target"]] = (
                datetime.fromisoformat(archive_manifest["locked_at"])
            )
    return {"layers": filtered_summaries}, last_locked_times


def _tag_manifest(manifest: BuildManifest, expected_tag: str) -> BuildManifest:
    """Add expected build tag to fields that are expected to include the build tag."""
    tagged_summaries: ArchiveSummaries = {}
    for kind, summaries in manifest["layers"].items():
        tagged_summaries[kind] = new_summaries = []
        for summary in summaries:
            new_summary = summary.copy()
            new_summaries.append(new_summary)
            # Archive name has the build tag inserted before the extension
            install_target = summary["install_target"]
            new_summary["archive_name"] = (
                f"{install_target}{expected_tag}{ARCHIVE_SUFFIX}"
            )
    return {"layers": tagged_summaries}


##########################
# Test cases
##########################


class TestMinimalSpec(SpecLoadingTestCase):
    # Test cases that only need the stack specification file

    def test_spec_loading(self) -> None:
        self.check_stack_specification(
            MINIMAL_PROJECT_STACK_SPEC_PATH,
            EXPECTED_ENVIRONMENTS,
            EXPECTED_RUNTIMES,
            EXPECTED_FRAMEWORKS,
            EXPECTED_APPLICATIONS,
        )


class TestMinimalBuildConfig(unittest.TestCase):
    # These test cases don't need the build environment to actually exist

    def setUp(self) -> None:
        # No files are created, so no need to use a temporary directory
        self.stack_spec = StackSpec.load(MINIMAL_PROJECT_STACK_SPEC_PATH)

    def test_default_build_directory(self) -> None:
        stack_spec = self.stack_spec
        build_env = stack_spec.define_build_environment()
        expected_build_path = stack_spec.spec_path.parent
        self.assertEqual(build_env.build_path, expected_build_path)
        # The spec directory necessarily already exists
        self.assertTrue(expected_build_path.exists())

    def test_custom_build_directory_relative(self) -> None:
        stack_spec = self.stack_spec
        build_env = stack_spec.define_build_environment("custom")
        expected_build_path = stack_spec.spec_path.parent / "custom"
        self.assertEqual(build_env.build_path, expected_build_path)
        # Build directory is only created when needed, not immediately
        self.assertFalse(expected_build_path.exists())

    def test_custom_build_directory_user(self) -> None:
        build_env = self.stack_spec.define_build_environment("~/custom")
        expected_build_path = Path.home() / "custom"
        self.assertEqual(build_env.build_path, expected_build_path)
        # Build directory is only created when needed, not immediately
        self.assertFalse(expected_build_path.exists())

    def test_custom_build_directory_absolute(self) -> None:
        expected_build_path = Path("/custom").absolute()  # Add drive info on Windows
        build_env = self.stack_spec.define_build_environment(expected_build_path)
        self.assertEqual(build_env.build_path, expected_build_path)
        # Build directory is only created when needed, not immediately
        self.assertFalse(expected_build_path.exists())

    def test_env_categories_without_lock_files(self) -> None:
        stack_spec = self.stack_spec
        build_env = stack_spec.define_build_environment()
        expected_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        all_names = [env.env_name for env in build_env.all_environments()]
        self.assertEqual(all_names, expected_names)
        # No lock files, so all envs should need locking
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = [env.env_name for env in envs_to_lock]
        self.assertEqual(lock_names, expected_names)
        self.assertTrue(all(env.needs_lock() for env in envs_to_lock))
        self.assertTrue(build_env._needs_lock())
        # All envs should be flagged for building
        build_names = [env.env_name for env in build_env.environments_to_build()]
        self.assertEqual(build_names, expected_names)
        # All envs should be flagged for publishing
        publish_names = [env.env_name for env in build_env.environments_to_publish()]
        self.assertEqual(publish_names, expected_names)

    def test_env_categories_with_ops_disabled(self) -> None:
        stack_spec = self.stack_spec
        build_env = stack_spec.define_build_environment()
        # Disable all operations
        # Also check disabling locking entirely overrides the lock reset request
        build_env.select_operations(
            lock=False, build=False, publish=False, reset_lock=True
        )
        expected_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        all_envs = list(build_env.all_environments())
        all_names = [env.env_name for env in all_envs]
        self.assertEqual(all_names, expected_names)
        # No envs should be selected for locking
        self.assertEqual(list(build_env.environments_to_lock()), [])
        self.assertFalse(any(env.needs_lock() for env in all_envs))
        self.assertFalse(build_env._needs_lock())
        # No envs should be flagged for building
        self.assertEqual(list(build_env.environments_to_build()), [])
        # No envs should be flagged for publishing
        self.assertEqual(list(build_env.environments_to_publish()), [])

    def test_get_stack_status(self) -> None:
        # Also covers testing get_env_status on the individual layers
        self.maxDiff = None
        # Test stack status summary
        stack_spec = self.stack_spec
        build_env = stack_spec.define_build_environment()
        # Default status: report ops, omit layer deps
        expected_stack_status = deepcopy(EXPECTED_STACK_STATUS)
        stack_status = build_env.get_stack_status()
        self.assertEqual(expected_stack_status, stack_status)
        # Minimal status: omit ops, omit layer deps
        expected_stack_status_no_ops = deepcopy(EXPECTED_STACK_STATUS)
        for category in ("applications", "frameworks", "runtimes"):
            for layer_status in expected_stack_status_no_ops[category]:
                layer_status["selected_operations"] = None
        stack_status_no_ops = build_env.get_stack_status(report_ops=False)
        self.assertEqual(stack_status_no_ops, expected_stack_status_no_ops)

class TestMinimalBuildConfigWithExistingLockFiles(unittest.TestCase):
    # These test cases don't need the build environment to actually exist

    def setUp(self) -> None:
        # Need a temporary directory to avoid cross-test side effects
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        self.working_path = working_path = Path(working_dir.name)
        self.build_env = build_env = _define_build_env(working_path)
        self.expected_build_path = working_path / "_build🐸"
        # Mimic the environments already being locked
        build_platform = build_env.build_platform
        lock_dir_path = build_env.requirements_dir_path
        for env in build_env.all_environments():
            env_spec = env.env_spec
            env.env_lock.prepare_lock_inputs()  # Also creates relevant subdir
            requirements_path = env_spec.get_requirements_path(
                build_platform, lock_dir_path
            )
            requirements_path.write_text("")
            env.env_lock.update_lock_metadata()
            self.assertIsNotNone(env.env_lock.load_valid_metadata())
        # Path diffs can get surprisingly long
        self.maxDiff = None

    def check_publishing_request(
        self, publishing_request: StackPublishingRequest
    ) -> None:
        self.assertEqual(_filter_manifest(publishing_request)[0], EXPECTED_MANIFEST)

    def test_default_output_directory(self) -> None:
        build_env = self.build_env
        output_path, publishing_request = build_env.publish_artifacts(dry_run=True)
        # Build folder is used as the default output directory
        expected_output_path = self.expected_build_path
        self.assertEqual(output_path, expected_output_path)
        self.check_publishing_request(publishing_request)
        # The build directory necessarily already exists
        self.assertFalse(expected_output_path.exists())

    def test_custom_output_directory_relative(self) -> None:
        build_env = self.build_env
        output_path, publishing_request = build_env.publish_artifacts(
            "custom", dry_run=True
        )
        expected_output_path = self.working_path / "custom"
        self.assertEqual(output_path, expected_output_path)
        self.check_publishing_request(publishing_request)
        # Dry run doesn't create the output directory
        self.assertFalse(expected_output_path.exists())

    def test_custom_output_directory_user(self) -> None:
        build_env = self.build_env
        output_path, publishing_request = build_env.publish_artifacts(
            "~/custom", dry_run=True
        )
        expected_output_path = Path.home() / "custom"
        self.assertEqual(output_path, expected_output_path)
        self.check_publishing_request(publishing_request)
        # Dry run doesn't create the output directory
        self.assertFalse(expected_output_path.exists())

    def test_custom_output_directory_absolute(self) -> None:
        build_env = self.build_env
        expected_output_path = Path("/custom").absolute()  # Add drive info on Windows
        output_path, publishing_request = build_env.publish_artifacts(
            expected_output_path, dry_run=True
        )
        self.assertEqual(output_path, expected_output_path)
        self.check_publishing_request(publishing_request)
        # Dry run doesn't create the output directory
        self.assertFalse(expected_output_path.exists())

    def test_env_categories_with_lock_files(self) -> None:
        build_env = self.build_env
        expected_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        all_names = [env.env_name for env in build_env.all_environments()]
        self.assertEqual(all_names, expected_names)
        # Lock files exist, so no envs should *need* locking,
        # but their lock status should still be checked by default
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = [env.env_name for env in envs_to_lock]
        self.assertEqual(lock_names, expected_names)
        self.assertFalse(any(env.needs_lock() for env in envs_to_lock))
        self.assertFalse(build_env._needs_lock())
        # All envs should be flagged for building
        build_names = [env.env_name for env in build_env.environments_to_build()]
        self.assertEqual(build_names, expected_names)
        # All envs should be flagged for publishing
        publish_names = [env.env_name for env in build_env.environments_to_publish()]
        self.assertEqual(publish_names, expected_names)

    def test_env_categories_lock_with_lock_reset(self) -> None:
        build_env = self.build_env
        # Enable locking with locked requirement resets
        build_env.select_operations(
            lock=True, build=False, publish=False, reset_lock=True
        )
        expected_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        all_names = [env.env_name for env in build_env.all_environments()]
        self.assertEqual(all_names, expected_names)
        # Lock reset requested, so all envs should need locking
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = [env.env_name for env in envs_to_lock]
        self.assertEqual(lock_names, expected_names)
        self.assertTrue(all(env.needs_lock() for env in envs_to_lock))
        self.assertTrue(build_env._needs_lock())
        # No envs should be flagged for building
        self.assertEqual(list(build_env.environments_to_build()), [])
        # No envs should be flagged for publishing
        self.assertEqual(list(build_env.environments_to_publish()), [])

    def test_env_categories_lock_layers_with_lock_reset(self) -> None:
        build_env = self.build_env
        # Enable locking with locked requirement resets
        all_names = [env.env_name for env in build_env.all_environments()]
        build_env.select_layers(
            lock=True,
            build=False,
            publish=False,
            include=all_names,
            reset_locks=all_names,
        )
        # Lock reset requested, so all envs should need locking
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = [env.env_name for env in envs_to_lock]
        self.assertEqual(lock_names, all_names)
        self.assertTrue(all(env.needs_lock() for env in envs_to_lock))
        self.assertTrue(build_env._needs_lock())
        # No envs should be flagged for building
        self.assertEqual(list(build_env.environments_to_build()), [])
        # No envs should be flagged for publishing
        self.assertEqual(list(build_env.environments_to_publish()), [])

    def test_env_categories_selective_lock_with_lock_reset(self) -> None:
        build_env = self.build_env
        # Locking only "framework-layerA" with the default settings:
        # * should omit "app-no-framework" entirely
        # * should only lock the runtime layer if necessary (no implicit reset)
        # * should lock and reset everything else directly or as a derived layer
        locked_layer = "framework-layerA"
        no_lock = {EnvNameBuild("app-no-framework")}
        no_reset = build_env.filter_layers(["cpython-*"])[0] | no_lock
        assert len(no_reset) > 1

        all_names = {env.env_name for env in build_env.all_environments()}
        included, _ = build_env.filter_layers([locked_layer])
        assert included == {"framework-layerA"}
        build_env.select_layers(
            lock=True,
            build=False,
            publish=False,
            include=included,
            reset_locks=all_names,
        )
        # Ensure expected envs want and need locking
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = {env.env_name for env in envs_to_lock}
        self.assertEqual(lock_names, all_names - no_lock)
        self.assertTrue(
            all(
                env.needs_lock() for env in envs_to_lock if env.env_name not in no_reset
            )
        )
        self.assertTrue(build_env._needs_lock())
        # Mark the runtime environment as unlocked
        for rt_env in build_env.runtimes.values():
            rt_env.env_lock._purge_lock()
        # Check the runtime environment has been added to layers to lock
        envs_to_lock = list(build_env.environments_to_lock())
        lock_names = {env.env_name for env in envs_to_lock}
        self.assertEqual(lock_names, all_names - no_lock)
        self.assertTrue(all(env.needs_lock() for env in envs_to_lock))
        self.assertTrue(build_env._needs_lock())

    def test_lock_input_cache_is_optional(self):
        build_env = self.build_env
        stack_spec = build_env.stack_spec
        # Lock input files should serve as a pure cache
        for env in build_env.all_environments():
            env.env_lock._clear_lock_input_cache()
        # Create a new instance using the same input and build folders
        new_env = stack_spec.define_build_environment(build_env.build_path)
        del build_env  # Ensure all checks are run against the new instance
        expected_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        all_names = [env.env_name for env in new_env.all_environments()]
        self.assertEqual(all_names, expected_names)
        # Lock files still exist, so no envs should need locking
        unlocked = [
            env.env_name for env in new_env.all_environments() if env.needs_lock()
        ]
        self.assertEqual(unlocked, [])
        self.assertFalse(new_env._needs_lock())


class TestMinimalBuild(DeploymentTestCase):
    # Test cases that actually create the build environment folders

    working_path: Path
    build_env: BuildEnvironment

    def setUp(self) -> None:
        # Need a temporary directory to avoid cross-test side effects
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        self.working_path = working_path = Path(working_dir.name)
        self.build_env = _define_build_env(working_path)
        self.maxDiff = None

    def assertRecentlyLocked(
        self, last_locked_times: LastLockedTimes, minimum_lock_time: datetime
    ) -> None:
        for install_target, last_locked in last_locked_times.items():
            # Use a tuple comparison so the install_target value gets
            # reported without needing to define nested subtests
            self.assertGreaterEqual(
                (install_target, last_locked), (install_target, minimum_lock_time)
            )

    @staticmethod
    def _load_archive_summary(metadata_path: Path) -> ArchiveSummary:
        with metadata_path.open("r", encoding="utf-8") as f:
            return _filter_archive_manifest(json.load(f))

    @staticmethod
    def _load_build_manifest(metadata_path: Path) -> BuildManifest:
        with metadata_path.open("r", encoding="utf-8") as f:
            return _filter_manifest(json.load(f))[0]

    def mock_index_config_options(
        self, reference_config: PackageIndexConfig | None = None
    ) -> None:
        # Mock the index configs in order to check for
        # expected CLI argument lookups
        for env in self.build_env.all_environments():
            if reference_config is None:
                env_reference_config = env.index_config
            else:
                env_reference_config = reference_config
            env.index_config = make_mock_index_config(env_reference_config)

    def check_publication_result(
        self,
        publication_result: PublishedArchivePaths,
        dry_run_result: BuildManifest,
        expected_tag: str | None,
    ) -> None:
        # Build dir is used as the default output path
        expected_output_path = self.build_env.build_path
        expected_metadata_path = expected_output_path / BuildEnvironment.METADATA_DIR
        expected_env_metadata_path = (
            expected_metadata_path / BuildEnvironment.METADATA_ENV_DIR
        )
        if expected_tag is None:
            expected_metadata_name = "venvstacks.json"
            expected_snippet_suffix = ".json"
        else:
            expected_metadata_name = f"venvstacks{expected_tag}.json"
            expected_snippet_suffix = f"{expected_tag}.json"
        manifest_path, snippet_paths, archive_paths = publication_result
        # Check overall manifest file
        expected_manifest_path = expected_metadata_path / expected_metadata_name
        self.assertEqual(manifest_path, expected_manifest_path)
        manifest_data = self._load_build_manifest(manifest_path)
        self.assertEqual(manifest_data, dry_run_result)
        # Check individual archive manifests
        expected_summaries: dict[str, ArchiveSummary] = {}
        for archive_summaries in dry_run_result["layers"].values():
            for archive_summary in archive_summaries:
                install_target = archive_summary["install_target"]
                expected_summaries[install_target] = archive_summary
        for snippet_path in snippet_paths:
            archive_summary = self._load_archive_summary(snippet_path)
            install_target = archive_summary["install_target"]
            expected_snippet_name = f"{install_target}{expected_snippet_suffix}"
            expected_snippet_path = expected_env_metadata_path / expected_snippet_name
            self.assertEqual(snippet_path, expected_snippet_path)
            self.assertEqual(archive_summary, expected_summaries[install_target])
        # Check the names and location of the generated archives
        expected_archive_paths: list[Path] = []
        for archive_summaries in dry_run_result["layers"].values():
            for archive_summary in archive_summaries:
                expected_archive_path = (
                    expected_output_path / archive_summary["archive_name"]
                )
                expected_archive_paths.append(expected_archive_path)
        expected_archive_paths.sort()
        self.assertEqual(sorted(archive_paths), expected_archive_paths)

    @staticmethod
    def _run_postinstall(env_path: Path) -> None:
        postinstall_script = env_path / "postinstall.py"
        if postinstall_script.exists():
            # Post-installation scripts are required to work even when they're
            # executed with an entirely unrelated Python installation
            capture_python_output(
                [sys.executable, "-X", "utf8", "-I", str(postinstall_script)]
            )

    def check_archive_deployment(self, published_paths: PublishedArchivePaths) -> None:
        metadata_path, snippet_paths, archive_paths = published_paths
        published_manifests = ManifestData(metadata_path, snippet_paths)
        # TODO: read the base Python path for each environment from the metadata
        #       https://github.com/lmstudio-ai/venvstacks/issues/19
        # TODO: figure out a more robust way of handling Windows potentially still
        #       having the Python executables in the environment open when the
        #       parent process tries to clean up the deployment directory.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as deployment_dir:
            # Extract archives
            deployment_path = Path(deployment_dir)
            env_name_to_path: dict[EnvNameDeploy, Path] = {}
            expected_dirs: list[str] = []
            for archive_metadata, archive_path in zip(
                published_manifests.snippet_data, archive_paths
            ):
                if ".tar" in archive_path.suffixes:
                    # Layered env tar archives typically have symlinks to their runtime environment
                    shutil.unpack_archive(
                        archive_path, deployment_path, filter="fully_trusted"
                    )
                else:
                    shutil.unpack_archive(archive_path, deployment_path)
                env_name = EnvNameDeploy(archive_metadata["install_target"])
                self.assertEqual(archive_path.name[: len(env_name)], env_name)
                expected_dirs.append(env_name)
                env_path = deployment_path / env_name
                env_name_to_path[env_name] = env_path
            self.assertCountEqual(
                [p.name for p in deployment_path.iterdir()], expected_dirs
            )
            # Run the post install scripts
            self.assertTrue(published_manifests.combined_data)
            layered_metadata = published_manifests.combined_data["layers"]
            base_runtime_env_name = layered_metadata["runtimes"][0]["install_target"]
            env_path = env_name_to_path[base_runtime_env_name]
            self._run_postinstall(env_path)
            for env_name, env_path in env_name_to_path.items():
                if env_name == base_runtime_env_name:
                    # Already configured
                    continue
                self._run_postinstall(env_path)

            def get_deployed_env_details(
                env: ArchiveMetadata,
            ) -> tuple[EnvNameDeploy, Path, list[str]]:
                env_name = env["install_target"]
                env_path = env_name_to_path[env_name]
                env_python = get_env_python(env_path)
                env_sys_path = get_sys_path(env_python)
                return env_name, env_path, env_sys_path

            self.check_deployed_environments(layered_metadata, get_deployed_env_details)

    def test_create_environments(self) -> None:
        # Faster test to check the links between build envs are set up correctly
        # (if this fails, there's no point even trying the full slow test case)
        build_env = self.build_env
        already_built = [
            env.env_name
            for env in build_env.all_environments()
            if not env.needs_build()
        ]
        self.assertEqual(already_built, [])
        build_env.create_environments()
        self.check_build_environments(self.build_env.all_environments())

    def test_build_with_invalid_locks(self) -> None:
        # Ensure attempt to build without locking first raises a detailed exception
        build_env = self.build_env
        build_env.select_operations(lock=False, build=True, publish=False)
        # Operation selection overrides the lock status check
        self.assertFalse(build_env._needs_lock())
        with pytest.raises(BuildEnvError, match="Invalid lock details"):
            build_env.create_environments()
        # Check lower level environment methods
        rt_env = next(build_env.runtimes_to_build())
        self.assertFalse(rt_env.needs_lock())  # Op selection override applies here
        self.assertFalse(rt_env.env_lock.has_valid_lock)  # But not to the lock itself
        with pytest.raises(BuildEnvError, match="Invalid lock details"):
            rt_env.install_requirements()

    @pytest.mark.slow
    def test_locking_and_publishing(self) -> None:
        # This is organised as subtests in a monolithic test sequence to reduce CI overhead
        # Separating the tests wouldn't really make them independent, unless the outputs of
        # the earlier steps were checked in for use when testing the later steps.
        # Actually configuring and building the environments is executed outside the subtest
        # declarations, since actual build failures need to fail the entire test method.
        subtests_started = subtests_passed = 0  # Track subtest failures
        build_env = self.build_env
        self.mock_index_config_options()
        platform_tag = build_env.build_platform
        expected_tag = f"-{platform_tag}"
        versioned_tag = (
            f"{expected_tag}-1"  # No previous metadata when running the test
        )
        expected_dry_run_result = EXPECTED_MANIFEST
        expected_tagged_dry_run_result = _tag_manifest(EXPECTED_MANIFEST, versioned_tag)
        minimum_lock_time = datetime.now(timezone.utc)
        # Ensure the locking and publication steps always run for all environments
        build_env.select_operations(lock=True, build=True, publish=True)
        self.assertTrue(build_env._needs_lock())
        # Handle running this test case repeatedly in a local checkout
        for env in build_env.all_environments():
            env.env_lock._purge_lock()
        # Create and link the layer build environments
        build_env.create_environments()
        # Don't even try to continue if the environments aren't properly linked
        self.check_build_environments(self.build_env.all_environments())
        # Test stage: check dry run metadata results are as expected
        subtests_started += 1
        with self.subTest("Check untagged dry run"):
            dry_run_result, dry_run_last_locked_times = _filter_manifest(
                build_env.publish_artifacts(dry_run=True)[1]
            )
            self.assertEqual(dry_run_result, expected_dry_run_result)
            self.assertRecentlyLocked(dry_run_last_locked_times, minimum_lock_time)
            # Check for expected subprocess argument lookups
            for env in self.build_env.all_environments():
                # First environment build: lock with uv, install with pip
                mock_compile = cast(Mock, env.index_config._get_uv_pip_compile_args)
                mock_compile.assert_called_once_with()
                mock_compile.reset_mock()
                mock_install = cast(Mock, env.index_config._get_pip_install_args)
                mock_install.assert_called_once_with()
                mock_install.reset_mock()
            subtests_passed += 1
        subtests_started += 1
        with self.subTest("Check tagged dry run"):
            tagged_dry_run_result, tagged_last_locked_times = _filter_manifest(
                build_env.publish_artifacts(dry_run=True, tag_outputs=True)[1]
            )
            self.assertEqual(tagged_dry_run_result, expected_tagged_dry_run_result)
            self.assertEqual(tagged_last_locked_times, dry_run_last_locked_times)
            subtests_passed += 1
        # Test stage: ensure lock timestamps don't change when requirements don't change
        build_env.lock_environments()
        self.assertFalse(build_env._needs_lock())
        subtests_started += 1
        with self.subTest("Check lock timestamps don't change for stable requirements"):
            stable_dry_run_result, stable_last_locked_times = _filter_manifest(
                build_env.publish_artifacts(dry_run=True)[1]
            )
            self.assertEqual(stable_dry_run_result, expected_dry_run_result)
            self.assertEqual(stable_last_locked_times, dry_run_last_locked_times)
            # Check for expected subprocess argument lookups
            for env in self.build_env.all_environments():
                # The lock file is recreated, the timestamp metadata just doesn't
                # get updated if the hash of the contents doesn't change
                mock_compile = cast(Mock, env.index_config._get_uv_pip_compile_args)
                mock_compile.assert_called_once_with()
                mock_compile.reset_mock()
                mock_install = cast(Mock, env.index_config._get_pip_install_args)
                mock_install.assert_not_called()
            subtests_passed += 1
        # Test stage: ensure lock timestamps *do* change when the requirements "change"
        for env in build_env.all_environments():
            # Rather than actually make the hash change, instead change the hash *records*
            env_lock = env.env_lock
            env_lock._requirements_hash = "ensure requirements appear to have changed"
            env_lock._write_lock_metadata()
        minimum_relock_time = datetime.now(timezone.utc)
        build_env.lock_environments()
        subtests_started += 1
        with self.subTest("Check lock timestamps change for updated requirements"):
            relocked_dry_run_result, relocked_last_locked_times = _filter_manifest(
                build_env.publish_artifacts(dry_run=True)[1]
            )
            self.assertEqual(relocked_dry_run_result, expected_dry_run_result)
            self.assertGreater(minimum_relock_time, minimum_lock_time)
            self.assertRecentlyLocked(relocked_last_locked_times, minimum_relock_time)
            # Check for expected subprocess argument lookups
            for env in self.build_env.all_environments():
                # Locked, but not rebuilt, so only uv should be called
                mock_compile = cast(Mock, env.index_config._get_uv_pip_compile_args)
                mock_compile.assert_called_once_with()
                mock_compile.reset_mock()
                mock_install = cast(Mock, env.index_config._get_pip_install_args)
                mock_install.assert_not_called()
            subtests_passed += 1
        # Test stage: ensure exported environments allow launch module execution
        subtests_started += 1
        with self.subTest("Check environment export"):
            export_path = self.working_path / "_export🦎"
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_path, export_result)
            subtests_passed += 1
        # Test stage: ensure published archives and manifests have the expected name
        #             and that unpacking them allows launch module execution
        subtests_started += 1
        with self.subTest("Check untagged publication"):
            publication_result = build_env.publish_artifacts()
            self.check_publication_result(
                publication_result, dry_run_result, expected_tag=None
            )
            self.check_archive_deployment(publication_result)
            subtests_passed += 1
        subtests_started += 1
        with self.subTest("Check tagged publication"):
            tagged_publication_result = build_env.publish_artifacts(tag_outputs=True)
            self.check_publication_result(
                tagged_publication_result, tagged_dry_run_result, expected_tag
            )
            self.check_archive_deployment(tagged_publication_result)
            subtests_passed += 1
        # TODO: Add another test stage that confirms build versions increment as expected

        # Work around pytest-subtests not failing the test case when subtests fail
        # https://github.com/pytest-dev/pytest-subtests/issues/76
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )
