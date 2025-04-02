"""Test building the local wheels project produces the expected results."""

import shutil
import subprocess
import sys
import tempfile

from pathlib import Path
from typing import Any, ClassVar


# Use unittest for these test implementations due to pytest's diff handling not working
# well for these tests, as discussed in https://github.com/pytest-dev/pytest/issues/6682
from unittest import mock

import pytest

from support import (
    DeploymentTestCase,
    EnvSummary,
    LayeredEnvSummary,
    ApplicationEnvSummary,
    SpecLoadingTestCase,
    get_os_environ_settings,
)

from venvstacks.stacks import (
    BuildEnvironment,
    PackageIndexConfig,
    StackSpec,
)
from venvstacks._util import run_python_command

##################################
# Sample project test helpers
##################################

_THIS_PATH = Path(__file__)
WHEEL_PROJECT_PATH = _THIS_PATH.parent / "local_wheel_project"
WHEEL_PACKAGES_PATH = WHEEL_PROJECT_PATH / "packages"
WHEEL_PROJECT_STACK_SPEC_PATH = WHEEL_PROJECT_PATH / "venvstacks.toml"
WHEEL_PROJECT_REQUIREMENTS_PATH = WHEEL_PROJECT_PATH / "requirements"
WHEEL_PROJECT_MANIFESTS_PATH = WHEEL_PROJECT_PATH / "expected_manifests"

WHEEL_PROJECT_PATHS = (
    WHEEL_PROJECT_STACK_SPEC_PATH,
    WHEEL_PROJECT_PATH / "dynlib_import.py",
)

# Similar to LayerEnvBase._run_pip, but uses the test runner's Python env
def _run_pip(cmd_args: list[str], **kwds: Any) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-Im",
        "pip",
        "--no-input",
        *cmd_args,
    ]
    return run_python_command(command, **kwds)

def _build_wheel(src_path: Path, output_path: Path) -> subprocess.CompletedProcess[str]:
    return _run_pip(
        [
            "wheel",
            "--no-index",
            "--no-build-isolation",  # Test env is set up for this
            "--wheel-dir",
            str(output_path),
            str(src_path)
        ]
    )

def _build_local_wheels(local_wheel_path: Path):
    for src_project in ("dynlib-publisher", "dynlib-consumer"):
        src_path = WHEEL_PACKAGES_PATH / src_project
        _build_wheel(src_path, local_wheel_path)


def _define_build_env(
    working_path: Path, index_config: PackageIndexConfig
) -> BuildEnvironment:
    """Define a build environment for the sample project in a temporary folder."""
    # To avoid side effects from lock file creation, copy input files to the working path
    for src_path in WHEEL_PROJECT_PATHS:
        dest_path = working_path / src_path.name
        shutil.copyfile(src_path, dest_path)
    # Include "/../" in the spec path in order to test relative path resolution when
    # accessing the Python executables (that can be temperamental, especially on macOS).
    # The subdirectory won't be used for anything, so it being missing shouldn't matter.
    working_spec_path = working_path / "_unused_dir/../venvstacks.toml"
    stack_spec = StackSpec.load(working_spec_path)
    build_path = working_path / "_build🐸"
    return stack_spec.define_build_environment(build_path, index_config)


##################################
# Expected layer definitions
##################################

EXPECTED_RUNTIMES = [
    EnvSummary("cpython-3.11", ""),
]

EXPECTED_FRAMEWORKS = [
    LayeredEnvSummary("both-wheels", "framework-", "cpython-3.11", ()),
    LayeredEnvSummary("only-publisher", "framework-", "cpython-3.11", ()),
    LayeredEnvSummary(
        "only-consumer", "framework-", "cpython-3.11", ("only-publisher",)
    ),
]

EXPECTED_APPLICATIONS = [
    ApplicationEnvSummary(
        "via-combined-layer", "app-", "cpython-3.11", ("both-wheels",)
    ),
    ApplicationEnvSummary(
        "via-split-layers",
        "app-",
        "cpython-3.11",
        (
            "only-consumer",
            "only-publisher",
        ),
    ),
]

EXPECTED_ENVIRONMENTS = EXPECTED_RUNTIMES.copy()
EXPECTED_ENVIRONMENTS.extend(EXPECTED_FRAMEWORKS)
EXPECTED_ENVIRONMENTS.extend(EXPECTED_APPLICATIONS)

##########################
# Test cases
##########################


class TestStackSpec(SpecLoadingTestCase):
    # Test cases that only need the stack specification file

    def test_spec_loading(self) -> None:
        self.check_stack_specification(
            WHEEL_PROJECT_STACK_SPEC_PATH,
            EXPECTED_ENVIRONMENTS,
            EXPECTED_RUNTIMES,
            EXPECTED_FRAMEWORKS,
            EXPECTED_APPLICATIONS,
        )


class TestBuildEnvironment(DeploymentTestCase):
    # Test cases that need the full build environment to exist
    EXPECTED_APP_OUTPUT = "Environment launch module executed successfully"

    _wheel_temp_dir: ClassVar[tempfile.TemporaryDirectory | None] = None
    local_wheel_path: ClassVar[Path]
    working_path: Path
    build_env: BuildEnvironment

    @classmethod
    def setUpClass(cls) -> None:
        local_wheel_dir = tempfile.TemporaryDirectory()
        cls._wheel_temp_dir = local_wheel_dir
        cls.local_wheel_path = local_wheel_path = Path(local_wheel_dir.name)
        _build_local_wheels(local_wheel_path)

    @classmethod
    def tearDownClass(cls) -> None:
        wheel_temp_dir = cls._wheel_temp_dir
        if wheel_temp_dir is not None:
            wheel_temp_dir.cleanup()

    def setUp(self) -> None:
        working_dir = tempfile.TemporaryDirectory()
        self.addCleanup(working_dir.cleanup)
        working_path = Path(working_dir.name)
        self.working_path = working_path
        index_config = PackageIndexConfig(
            query_default_index=False, local_wheel_dirs=[self.local_wheel_path]
        )
        self.build_env = _define_build_env(working_path, index_config)
        os_env_updates = dict(get_os_environ_settings())
        # Loading local wheels, so ignore the date based lock resolution pin,
        # but allow for other env vars to be overridden
        os_env_updates.pop("UV_EXCLUDE_NEWER", None)
        os_env_patch = mock.patch.dict("os.environ", os_env_updates)
        os_env_patch.start()
        self.addCleanup(os_env_patch.stop)

    def test_create_environments(self) -> None:
        # Faster test to check the links between build envs are set up correctly
        # (if this fails, there's no point even trying the full slow test case)
        build_env = self.build_env
        build_env.create_environments()
        self.check_build_environments(self.build_env.all_environments())

    @pytest.mark.slow
    def test_locking_and_publishing(self) -> None:
        # Need long diffs to get useful output from metadata checks
        self.maxDiff = None
        # This is organised as subtests in a monolothic test sequence to reduce CI overhead
        # Separating the tests wouldn't really make them independent, unless the outputs of
        # the initial intermediate steps were checked in for use when testing the later steps.
        # Actually configuring and building the environments is executed outside the subtest
        # declarations, since actual build failures need to fail the entire test method.
        subtests_started = subtests_passed = 0  # Track subtest failures
        build_env = self.build_env
        # Create and link the layer build environments
        build_env.create_environments(lock=True)
        # Don't even try to continue if the environments aren't properly linked
        self.check_build_environments(self.build_env.all_environments())
        # Test stage: ensure exported environments allow launch module execution
        subtests_started += 1
        with self.subTest("Check environment export"):
            export_path = self.working_path / "_export🦎"
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_path, export_result)
            subtests_passed += 1

        # Work aroung pytest-subtests not failing the test case when subtests fail
        # https://github.com/pytest-dev/pytest-subtests/issues/76
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )
