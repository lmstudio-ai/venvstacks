"""Test building the sample project produces the expected results"""

import os.path
import shutil
import tempfile

from itertools import chain
from pathlib import Path
from typing import Any


# Use unittest for the actual test implementations due to the diff-handling in pytest being
# atrociously bad, as discussed in https://github.com/pytest-dev/pytest/issues/6682
import unittest
from unittest import mock

import pytest  # To mark slow test cases

from support import (
    DeploymentTestCase,
    EnvSummary,
    LayeredEnvSummary,
    ApplicationEnvSummary,
    ManifestData,
    get_artifact_export_path,
    force_artifact_export,
    get_os_environ_settings,
)

from venvstacks.stacks import (
    ArchiveBuildMetadata,
    ArchiveMetadata,
    BuildEnvironment,
    StackSpec,
    LayerCategories,
)

##################################
# Sample project test helpers
##################################

_THIS_PATH = Path(__file__)
SAMPLE_PROJECT_EXPORT_DIR = _THIS_PATH.stem
SAMPLE_PROJECT_PATH = _THIS_PATH.parent / "sample_project"
SAMPLE_PROJECT_STACK_SPEC_PATH = SAMPLE_PROJECT_PATH / "venvstacks.toml"
SAMPLE_PROJECT_REQUIREMENTS_PATH = SAMPLE_PROJECT_PATH / "requirements"
SAMPLE_PROJECT_MANIFESTS_PATH = SAMPLE_PROJECT_PATH / "expected_manifests"


def _define_build_env(working_path: Path) -> BuildEnvironment:
    """Define a build environment for the sample project in a temporary folder"""
    # To simplify regeneration of committed lockfiles and metadata,
    # use the spec file directly from its checked out location
    stack_spec = StackSpec.load(SAMPLE_PROJECT_STACK_SPEC_PATH)
    build_path = working_path / "_build🐸"
    return stack_spec.define_build_environment(build_path)


def _get_expected_metadata(build_env: BuildEnvironment) -> ManifestData:
    """Path to the expected sample project archive metadata for the current platform"""
    return ManifestData(SAMPLE_PROJECT_MANIFESTS_PATH / build_env.build_platform)


def _get_expected_dry_run_result(
    build_env: BuildEnvironment, expect_tagged_outputs: bool = False
) -> dict[str, Any]:
    # Dry run results report LayerCategories instances rather than plain strings
    untagged_metadata = _get_expected_metadata(build_env).combined_data
    all_layer_manifests = untagged_metadata["layers"]
    filtered_layer_manifests: dict[LayerCategories, Any] = {}
    for category, archive_manifests in all_layer_manifests.items():
        filtered_layer_manifests[LayerCategories(category)] = archive_manifests
    # Dry run results omit any metadata keys relating solely to the built archives
    build_request_keys = (
        ArchiveBuildMetadata.__required_keys__ | ArchiveBuildMetadata.__optional_keys__
    )
    archive_keys = ArchiveMetadata.__required_keys__ | ArchiveMetadata.__optional_keys__
    archive_only_keys = archive_keys - build_request_keys
    platform_tag = build_env.build_platform
    for archive_metadata in chain(*all_layer_manifests.values()):
        for key in archive_only_keys:
            archive_metadata.pop(key, None)
        if expect_tagged_outputs:
            # Saved metadata is for untagged builds, so the tagged output dry run
            # will always indicate that a new build is needed
            # Inputs haven't changed, so the iteration number won't be increased
            install_target = archive_metadata["install_target"]
            build_iteration = archive_metadata["archive_build"]
            expected_tag = f"{platform_tag}-{build_iteration}"
            tagged_build_name = f"{install_target}-{expected_tag}"
            archive_name: str = archive_metadata["archive_name"]
            archive_suffix = archive_name.removeprefix(install_target)
            archive_metadata["archive_name"] = f"{tagged_build_name}{archive_suffix}"
    return {"layers": filtered_layer_manifests}


def _collect_locked_requirements(build_env: BuildEnvironment) -> dict[Path, str]:
    locked_requirements: dict[Path, str] = {}
    lock_dir_path = build_env.requirements_dir_path
    build_platform = build_env.build_platform
    for env in build_env.all_environments():
        env_spec = env.env_spec
        env_requirements_path = env_spec.get_requirements_path(
            build_platform, lock_dir_path
        )
        env_requirements_text = ""
        if env_requirements_path.exists():
            env_requirements_text = env_requirements_path.read_text()
        locked_requirements[env_requirements_path] = env_requirements_text
    return locked_requirements


def _export_locked_requirements(
    artifact_export_path: Path | None,
    build_env: BuildEnvironment,
    lock_paths: list[Path],
) -> None:
    if artifact_export_path is None:
        # Artifact export has not been enabled
        return
    export_dir_path = artifact_export_path / SAMPLE_PROJECT_EXPORT_DIR / "requirements"
    export_dir_path.mkdir(parents=True, exist_ok=True)
    print(f"Exporting locked requirements files to {str(export_dir_path)!r}")
    spec_dir_path = build_env.requirements_dir_path
    for locked_requirements_path in lock_paths:
        export_path = export_dir_path / locked_requirements_path.relative_to(
            spec_dir_path
        )
        export_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(locked_requirements_path, export_path)


def _export_manifests(
    manifests_export_path: Path, manifest_path: Path, archive_metadata_path: Path
) -> None:
    manifests_export_path.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest_path, manifests_export_path / manifest_path.name)
    shutil.copytree(
        archive_metadata_path,
        manifests_export_path / archive_metadata_path.name,
        dirs_exist_ok=True,
    )


def _export_archives(
    artifact_export_path: Path | None,
    build_env: BuildEnvironment,
    manifest_path: Path,
    archive_metadata_paths: list[Path],
    archive_paths: list[Path],
) -> None:
    print("Copying generated artifact manifest files back to source tree")
    metadata_path = SAMPLE_PROJECT_MANIFESTS_PATH / build_env.build_platform
    archive_metadata_path = Path(os.path.commonpath(archive_metadata_paths))
    _export_manifests(metadata_path, manifest_path, archive_metadata_path)
    if artifact_export_path is None:
        # Artifact export has not been enabled
        return
    # Export manifests from CI
    test_export_dir_path = artifact_export_path / SAMPLE_PROJECT_EXPORT_DIR
    export_manifests_dir_path = test_export_dir_path / "manifests"
    print(f"Exporting manifest files to {str(export_manifests_dir_path)!r}")
    _export_manifests(export_manifests_dir_path, manifest_path, archive_metadata_path)
    # Export archives from CI
    export_archives_dir_path = test_export_dir_path / "archives"
    print(f"Exporting archive files to {str(export_archives_dir_path)!r}")
    export_archives_dir_path.mkdir(parents=True, exist_ok=True)
    archive_dir_path = build_env.build_path
    for archive_path in archive_paths:
        relative_archive_path = archive_path.relative_to(archive_dir_path)
        export_archive_path = export_archives_dir_path / relative_archive_path
        export_archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(archive_path, export_archive_path)


##################################
# Expected layer definitions
##################################

EXPECTED_RUNTIMES = [
    EnvSummary("cpython@3.11", ""),
    EnvSummary("cpython@3.12", ""),
]

EXPECTED_FRAMEWORKS = [
    LayeredEnvSummary("scipy", "framework-", "cpython@3.11"),
    LayeredEnvSummary("sklearn", "framework-", "cpython@3.12"),
    LayeredEnvSummary("http-client", "framework-", "cpython@3.11"),
]

EXPECTED_APPLICATIONS = [
    ApplicationEnvSummary("scipy-import", "app-", "cpython@3.11", ("scipy",)),
    ApplicationEnvSummary(
        "scipy-client",
        "app-",
        "cpython@3.11",
        (
            "scipy",
            "http-client",
        ),
    ),
    ApplicationEnvSummary("sklearn-import", "app-", "cpython@3.12", ("sklearn",)),
]

EXPECTED_ENVIRONMENTS = EXPECTED_RUNTIMES.copy()
EXPECTED_ENVIRONMENTS.extend(EXPECTED_FRAMEWORKS)
EXPECTED_ENVIRONMENTS.extend(EXPECTED_APPLICATIONS)

##########################
# Test cases
##########################


class TestStackSpec(unittest.TestCase):
    # Test cases that only need the stack specification file

    def test_spec_loading(self) -> None:
        stack_spec = StackSpec.load(SAMPLE_PROJECT_STACK_SPEC_PATH)
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


class TestBuildEnvironment(DeploymentTestCase):
    # Test cases that need the full build environment to exist
    EXPECTED_APP_OUTPUT = "Environment launch module executed successfully"

    working_path: Path
    build_env: BuildEnvironment

    def setUp(self) -> None:
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        working_path = Path(working_dir.name)
        self.working_path = working_path
        self.build_env = _define_build_env(working_path)
        os_env_updates = get_os_environ_settings()
        os_env_patch = mock.patch.dict("os.environ", os_env_updates)
        os_env_patch.start()
        self.addCleanup(os_env_patch.stop)
        self.artifact_export_path = get_artifact_export_path()
        self.export_on_success = force_artifact_export()

    @pytest.mark.slow
    @pytest.mark.expected_output
    def test_build_is_reproducible(self) -> None:
        # Need long diffs to get useful output from metadata checks
        self.maxDiff = None
        # This is organised as subtests in a monolothic test sequence to reduce CI overhead
        # Separating the tests wouldn't really make them independent, unless the outputs of
        # the initial intermediate steps were checked in for use when testing the later steps.
        # Actually configuring and building the environments is executed outside the subtest
        # declarations, since actual build failures need to fail the entire test method.
        subtests_started = subtests_passed = 0  # Track subtest failures
        build_env = self.build_env
        artifact_export_path = self.artifact_export_path
        # Read expected results from committed test data
        expected_archive_metadata = _get_expected_metadata(build_env)
        expected_dry_run_result = _get_expected_dry_run_result(build_env)
        expected_tagged_dry_run_result = _get_expected_dry_run_result(
            build_env, expect_tagged_outputs=True
        )
        # Test stage: create and link build environments
        committed_locked_requirements = _collect_locked_requirements(build_env)
        build_env.create_environments(lock=True)
        subtests_started += 1
        with self.subTest("Check build environments have been linked"):
            self.check_build_environments(self.build_env.all_environments())
            subtests_passed += 1
        # Test stage: ensure lock files can be regenerated without alteration
        generated_locked_requirements = _collect_locked_requirements(build_env)
        export_locked_requirements = True
        subtests_started += 1
        with self.subTest("Ensure lock files are reproducible"):
            self.assertEqual(
                generated_locked_requirements, committed_locked_requirements
            )
            export_locked_requirements = self.export_on_success  # Only export if forced
            subtests_passed += 1
        if export_locked_requirements:
            # Lock files will already have been written back to the source tree location
            # Also export them to the CI test artifact upload path (if set)
            _export_locked_requirements(
                artifact_export_path,
                build_env,
                list(generated_locked_requirements.keys()),
            )
        # Test stage: ensure environments can be populated without building the artifacts
        build_env.create_environments()  # Use committed lock files
        subtests_started += 1
        with self.subTest("Ensure archive publication requests are reproducible"):
            # Check generation of untagged archive names
            dry_run_result = build_env.publish_artifacts(dry_run=True)[1]
            self.assertEqual(dry_run_result, expected_dry_run_result)
            # Check generation of tagged archive names
            tagged_dry_run_result = build_env.publish_artifacts(
                dry_run=True, tag_outputs=True
            )[1]
            self.assertEqual(tagged_dry_run_result, expected_tagged_dry_run_result)
            # Dry run metadata may be incorrect because the expected outputs are being updated,
            # so always continue on and execute the full archive publication subtest
            subtests_passed += 1
        subtests_started += 1
        with self.subTest(
            "Ensure dry run builds do not update lock files or manifests"
        ):
            # No changes to lock files
            post_rebuild_locked_requirements = _collect_locked_requirements(build_env)
            self.assertEqual(
                post_rebuild_locked_requirements, generated_locked_requirements
            )
            subtests_passed += 1
        # Test stage: ensure built artifacts have the expected manifest contents
        manifest_path, snippet_paths, archive_paths = build_env.publish_artifacts()
        export_published_archives = True
        subtests_started += 1
        with self.subTest("Ensure artifact metadata is reproducible"):
            # Generated metadata should match committed reference metadata
            generated_archive_metadata = ManifestData(
                manifest_path.parent, snippet_paths
            )
            self.assertEqual(
                generated_archive_metadata.combined_data,
                expected_archive_metadata.combined_data,
            )
            self.assertCountEqual(
                generated_archive_metadata.snippet_data,
                expected_archive_metadata.snippet_data,
            )
            # Archive should be emitted for every environment defined for this platform
            num_environments = len(list(build_env.all_environments()))
            self.assertEqual(len(archive_paths), num_environments)
            export_published_archives = self.export_on_success  # Only export if forced
            # No changes to lock files
            post_publish_locked_requirements = _collect_locked_requirements(build_env)
            self.assertEqual(
                post_publish_locked_requirements, generated_locked_requirements
            )
            subtests_passed += 1
        if export_published_archives:
            # Export manifests and archives to the CI test artifact upload path (if set)
            # Also write manifests back to the source tree location for local updates
            _export_archives(
                artifact_export_path,
                build_env,
                manifest_path,
                snippet_paths,
                archive_paths,
            )
        # Test stage: ensure exported environments allow launch module execution
        subtests_started += 1
        with self.subTest("Check environment export"):
            export_path = self.working_path / "_export🦎"
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_result)
            subtests_passed += 1

        # Work aroung pytest-subtests not failing the test case when subtests fail
        # https://github.com/pytest-dev/pytest-subtests/issues/76
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )

    def test_default_operation_selection(self) -> None:
        subtests_started = subtests_passed = 0  # Track subtest failures
        build_env = self.build_env
        # Test default state
        for env in build_env.all_environments():
            subtests_started += 1
            with self.subTest(env=env.env_name):
                self.assertIsNone(env.want_lock, "want_lock should be None")
                self.assertTrue(env.want_build, "want_build should be True")
                self.assertTrue(env.want_publish, "want_publish should be True")
                subtests_passed += 1
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )

    def test_operation_selection(self) -> None:
        subtests_started = subtests_passed = 0  # Track subtest failures
        requested_operations = (
            (False, False, False),  # Don't actually do anything
            (True, False, False),  # Just lock
            (True, True, False),  # Lock and build
            (None, None, True),  # Publish (locking and building if needed)
            (False, False, True),  # Publish (without modification to current state)
            (True, True, True),  # Lock, build, and publish
        )
        build_env = self.build_env
        for requested in requested_operations:
            want_lock, want_build, want_publish = requested
            build_env.select_operations(want_lock, want_build, want_publish)
            for env in build_env.all_environments():
                subtests_started += 1
                with self.subTest(env=env.env_name, requested=requested):
                    self.assertEqual(env.want_lock, want_lock, "want_lock mismatch")
                    self.assertEqual(env.want_build, want_build, "want_build mismatch")
                    self.assertEqual(
                        env.want_publish, want_publish, "want_publish mismatch"
                    )
                    subtests_passed += 1
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )

    def test_get_unmatched_patterns(self) -> None:
        build_env = self.build_env
        matching = ["app-*", "*@*", "framework-*", "app-scipy-import"]
        self.assertEqual(build_env.get_unmatched_patterns(matching), [])
        unknown = ["unknown", "app-?", "*-app"]
        self.assertEqual(build_env.get_unmatched_patterns(unknown), unknown)
        combined = sorted(matching + unknown)
        self.assertEqual(build_env.get_unmatched_patterns(combined), sorted(unknown))

    def test_layer_selection(self) -> None:
        subtests_started = subtests_passed = 0  # Track subtest failures
        included = ["framework-sklearn"]
        dependencies = ["cpython@3.12"]
        derived = ["app-sklearn-import"]
        build_env = self.build_env

        build_env.select_layers(included, lock=True)
        for env in build_env.all_environments():
            subtests_started += 1
            env_name = env.env_name
            with self.subTest(env=env_name):
                if env_name in included:
                    self.assertTrue(
                        env.want_lock, "want_lock not set for included layer"
                    )
                    self.assertTrue(
                        env.want_build, "want_build not set for included layer"
                    )
                    self.assertTrue(
                        env.want_publish, "want_publish not set for included layer"
                    )
                elif env_name in dependencies:
                    self.assertIsNone(
                        env.want_lock, "want_lock is not None for dependency"
                    )
                    self.assertIsNone(
                        env.want_build, "want_build is not None for dependency"
                    )
                    self.assertFalse(
                        env.want_publish, "want_publish is set for dependency"
                    )
                elif env_name in derived:
                    self.assertTrue(
                        env.want_lock, "want_lock not set for derived layer"
                    )
                    self.assertTrue(
                        env.want_build, "want_build not set for derived layer"
                    )
                    self.assertTrue(
                        env.want_publish, "want_publish not set for derived layer"
                    )
                else:
                    self.assertFalse(env.want_lock, "want_lock set for excluded layer")
                    self.assertFalse(
                        env.want_build, "want_build set for excluded layer"
                    )
                    self.assertFalse(
                        env.want_publish, "want_publish set for excluded layer"
                    )
                subtests_passed += 1
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )


# TODO: Add test case for cleaning an existing build environment
# TODO: Add test case that confirms operation & layer selection has the desired effect
# TODO: Add more layer selection test cases beyond the current one (including derivation)
