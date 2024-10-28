"""Test building the minimal project produces the expected results"""

import json
import shutil
import tempfile

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast, Mapping, Sequence, TypeVar

# Use unittest for consistency with test_sample_project (which needs the better diff support)
import unittest
from unittest.mock import Mock

import pytest  # To mark slow test cases

from support import (
    EnvSummary,
    LayeredEnvSummary,
    ApplicationEnvSummary,
    ManifestData,
    make_mock_index_config,
    get_sys_path,
    run_module,
)

from venvstacks.stacks import (
    ArchiveBuildMetadata,
    ArchiveMetadata,
    StackPublishingRequest,
    BuildEnvironment,
    EnvNameDeploy,
    StackSpec,
    ExportedEnvironmentPaths,
    ExportMetadata,
    PackageIndexConfig,
    PublishedArchivePaths,
    get_build_platform,
)
from venvstacks._util import get_env_python, run_python_command, WINDOWS_BUILD

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


def _define_build_env(working_path: Path) -> BuildEnvironment:
    """Define a build environment for the sample project in a temporary folder"""
    # To avoid side effects from lock file creation, copy input files to the working path
    for src_path in MINIMAL_PROJECT_PATHS:
        dest_path = working_path / src_path.name
        shutil.copyfile(src_path, dest_path)
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
    EnvSummary("cpython@3.11", ""),
]

EXPECTED_FRAMEWORKS = [
    LayeredEnvSummary("layer", "framework-", "cpython@3.11"),
]

EXPECTED_APPLICATIONS = [
    ApplicationEnvSummary("empty", "app-", "cpython@3.11", ("layer",)),
]

EXPECTED_ENVIRONMENTS = EXPECTED_RUNTIMES.copy()
EXPECTED_ENVIRONMENTS.extend(EXPECTED_FRAMEWORKS)
EXPECTED_ENVIRONMENTS.extend(EXPECTED_APPLICATIONS)

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
                    "framework-layer",
                ],
                "target_platform": BUILD_PLATFORM,
            },
        ],
        "frameworks": [
            {
                "archive_build": 1,
                "install_target": "framework-layer",
                "archive_name": f"framework-layer{ARCHIVE_SUFFIX}",
                "target_platform": BUILD_PLATFORM,
            },
        ],
        "runtimes": [
            {
                "archive_build": 1,
                "install_target": "cpython@3.11",
                "archive_name": f"cpython@3.11{ARCHIVE_SUFFIX}",
                "target_platform": BUILD_PLATFORM,
            },
        ],
    }
}

LastLockedTimes = dict[str, datetime]  # Mapping from install target names to lock times
_CHECKED_KEYS = frozenset(EXPECTED_MANIFEST["layers"]["applications"][0])


def _filter_archive_manifest(archive_manifest: ArchiveBuildMetadata) -> ArchiveSummary:
    """Drop archive manifest fields that aren't covered by this set of test cases"""
    summary: ArchiveSummary = {}
    for key in _CHECKED_KEYS:
        value = archive_manifest.get(key)
        if value is not None:
            summary[key] = value
    return summary


def _filter_manifest(
    manifest: StackPublishingRequest,
) -> tuple[BuildManifest, LastLockedTimes]:
    """Extract manifest fields that are relevant to this set of test cases"""
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
    """Add expected build tag to fields that are expected to include the build tag"""
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


class TestMinimalSpec(unittest.TestCase):
    # Test cases that only need the stack specification file

    def test_spec_loading(self) -> None:
        expected_spec_path = MINIMAL_PROJECT_STACK_SPEC_PATH
        stack_spec = StackSpec.load(expected_spec_path)
        runtime_keys = list(stack_spec.runtimes)
        framework_keys = list(stack_spec.frameworks)
        application_keys = list(stack_spec.applications)
        spec_keys = runtime_keys + framework_keys + application_keys
        self.assertCountEqual(spec_keys, set(spec_keys))
        expected_spec_names = [env.spec_name for env in EXPECTED_ENVIRONMENTS]
        self.assertCountEqual(spec_keys, expected_spec_names)
        spec_names = [env.name for env in stack_spec.all_environment_specs()]
        self.assertCountEqual(spec_names, expected_spec_names)
        expected_env_names = [env.env_name for env in EXPECTED_ENVIRONMENTS]
        env_names = [env.env_name for env in stack_spec.all_environment_specs()]
        self.assertCountEqual(env_names, expected_env_names)
        for rt_summary in EXPECTED_RUNTIMES:
            spec_name = rt_summary.spec_name
            rt_env = stack_spec.runtimes[spec_name]
            self.assertEqual(rt_env.name, spec_name)
            self.assertEqual(rt_env.env_name, rt_summary.env_name)
        for fw_summary in EXPECTED_FRAMEWORKS:
            spec_name = fw_summary.spec_name
            fw_env = stack_spec.frameworks[spec_name]
            self.assertEqual(fw_env.name, spec_name)
            self.assertEqual(fw_env.env_name, fw_summary.env_name)
        for app_summary in EXPECTED_APPLICATIONS:
            spec_name = app_summary.spec_name
            app_env = stack_spec.applications[spec_name]
            self.assertEqual(app_env.name, spec_name)
            self.assertEqual(app_env.env_name, app_summary.env_name)
        # Check path attributes
        self.assertEqual(stack_spec.spec_path, expected_spec_path)
        expected_requirements_dir_path = expected_spec_path.parent / "requirements"
        self.assertEqual(
            stack_spec.requirements_dir_path, expected_requirements_dir_path
        )


class TestMinimalBuildDirectoryResolution(unittest.TestCase):
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


class TestMinimalOutputDirectoryResolution(unittest.TestCase):
    # These test cases don't need the build environment to actually exist

    def setUp(self) -> None:
        # Need a temporary directory to avoid cross-test side effects
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        self.working_path = working_path = Path(working_dir.name)
        self.build_env = build_env = _define_build_env(working_path)
        build_env.select_operations(lock=False, build=False, publish=True)
        self.expected_build_path = working_path / "_build🐸"
        # Mimic the environments already being locked
        build_platform = build_env.build_platform
        lock_dir_path = build_env.requirements_dir_path
        for env in build_env.all_environments():
            env_spec = env.env_spec
            requirements_path = env_spec.get_requirements_path(
                build_platform, lock_dir_path
            )
            requirements_path.parent.mkdir(parents=True, exist_ok=True)
            requirements_path.write_text("")
            env.env_lock.update_lock_metadata()
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


class TestMinimalBuild(unittest.TestCase):
    # Test cases that actually create the build environment folders

    working_path: Path
    build_env: BuildEnvironment

    def setUp(self) -> None:
        # Need a temporary directory to avoid cross-test side effects
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        self.working_path = working_path = Path(working_dir.name)
        self.build_env = _define_build_env(working_path)

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

    # TODO: Refactor to share the environment checking code with test_sample_project
    def assertSysPathEntry(self, expected: str, env_sys_path: Sequence[str]) -> None:
        self.assertTrue(
            any(expected in path_entry for path_entry in env_sys_path),
            f"No entry containing {expected!r} found in {env_sys_path}",
        )

    T = TypeVar("T", bound=Mapping[str, Any])

    def check_deployed_environments(
        self,
        layered_metadata: dict[str, Sequence[T]],
        get_exported_python: Callable[[T], tuple[str, Path, list[str]]],
    ) -> None:
        for rt_env in layered_metadata["runtimes"]:
            env_name, _, env_sys_path = get_exported_python(rt_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Runtime environment layer should be completely self-contained
            self.assertTrue(
                all(env_name in path_entry for path_entry in env_sys_path),
                f"Path outside {env_name} in {env_sys_path}",
            )
        for fw_env in layered_metadata["frameworks"]:
            env_name, _, env_sys_path = get_exported_python(fw_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Framework and runtime should both appear in sys.path
            runtime_name = fw_env["runtime_name"]
            short_runtime_name = ".".join(runtime_name.split(".")[:2])
            self.assertSysPathEntry(env_name, env_sys_path)
            self.assertSysPathEntry(short_runtime_name, env_sys_path)
        for app_env in layered_metadata["applications"]:
            env_name, env_python, env_sys_path = get_exported_python(app_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Application, frameworks and runtime should all appear in sys.path
            runtime_name = app_env["runtime_name"]
            short_runtime_name = ".".join(runtime_name.split(".")[:2])
            self.assertSysPathEntry(env_name, env_sys_path)
            self.assertTrue(
                any(env_name in path_entry for path_entry in env_sys_path),
                f"No entry containing {env_name} found in {env_sys_path}",
            )
            for fw_env_name in app_env["required_layers"]:
                self.assertSysPathEntry(fw_env_name, env_sys_path)
            self.assertSysPathEntry(short_runtime_name, env_sys_path)
            # Launch module should be executable
            launch_module = app_env["app_launch_module"]
            launch_result = run_module(env_python, launch_module)
            self.assertEqual(launch_result.stdout, "")
            self.assertEqual(launch_result.stderr, "")

    @staticmethod
    def _run_postinstall(base_python_path: Path, env_path: Path) -> None:
        postinstall_script = env_path / "postinstall.py"
        if postinstall_script.exists():
            run_python_command([str(base_python_path), str(postinstall_script)])

    def check_archive_deployment(self, published_paths: PublishedArchivePaths) -> None:
        metadata_path, snippet_paths, archive_paths = published_paths
        published_manifests = ManifestData(metadata_path, snippet_paths)
        # TODO: read the base Python path for each environment from the metadata
        #       https://github.com/lmstudio-ai/venvstacks/issues/19
        with tempfile.TemporaryDirectory() as deployment_dir:
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
            base_runtime_env_path = env_name_to_path[base_runtime_env_name]
            base_python_path = get_env_python(base_runtime_env_path)
            self._run_postinstall(base_python_path, env_path)
            for env_name, env_path in env_name_to_path.items():
                if env_name == base_runtime_env_name:
                    # Already configured
                    continue
                self._run_postinstall(base_python_path, env_path)

            def get_exported_python(
                env: ArchiveMetadata,
            ) -> tuple[EnvNameDeploy, Path, list[str]]:
                env_name = env["install_target"]
                env_path = env_name_to_path[env_name]
                env_python = get_env_python(env_path)
                env_sys_path = get_sys_path(env_python)
                return env_name, env_python, env_sys_path

            self.check_deployed_environments(layered_metadata, get_exported_python)

    def check_environment_exports(self, export_paths: ExportedEnvironmentPaths) -> None:
        metadata_path, snippet_paths, env_paths = export_paths
        exported_manifests = ManifestData(metadata_path, snippet_paths)
        env_name_to_path: dict[str, Path] = {}
        for env_metadata, env_path in zip(exported_manifests.snippet_data, env_paths):
            # TODO: Check more details regarding expected metadata contents
            self.assertTrue(env_path.exists())
            env_name = EnvNameDeploy(env_metadata["install_target"])
            self.assertEqual(env_path.name, env_name)
            env_name_to_path[env_name] = env_path
        layered_metadata = exported_manifests.combined_data["layers"]

        def get_exported_python(
            env: ExportMetadata,
        ) -> tuple[EnvNameDeploy, Path, list[str]]:
            env_name = env["install_target"]
            env_path = env_name_to_path[env_name]
            env_python = get_env_python(env_path)
            env_sys_path = get_sys_path(env_python)
            return env_name, env_python, env_sys_path

        self.check_deployed_environments(layered_metadata, get_exported_python)

    @pytest.mark.slow
    def test_locking_and_publishing(self) -> None:
        # This is organised as subtests in a monolothic test sequence to reduce CI overhead
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
        # Ensure the locking and publication steps always run for all environments
        build_env.select_operations(lock=True, build=True, publish=True)
        # Handle running this test case repeatedly in a local checkout
        for env in build_env.all_environments():
            env.env_lock._purge_lock()
        # Test stage: check dry run metadata results are as expected
        minimum_lock_time = datetime.now(timezone.utc)
        build_env.create_environments()
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
                mock_compile.assert_called_once()
                mock_compile.reset_mock()
                mock_install = cast(Mock, env.index_config._get_pip_install_args)
                mock_install.assert_called_once_with(None)
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
                mock_compile.assert_called_once()
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
                mock_compile.assert_called_once()
                mock_compile.reset_mock()
                mock_install = cast(Mock, env.index_config._get_pip_install_args)
                mock_install.assert_not_called()
            subtests_passed += 1
        # Test stage: ensure exported environments allow launch module execution
        subtests_started += 1
        with self.subTest("Check environment export"):
            export_path = self.working_path / "_export🦎"
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_result)
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

        # Work aroung pytest-subtests not failing the test case when subtests fail
        # https://github.com/pytest-dev/pytest-subtests/issues/76
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )
