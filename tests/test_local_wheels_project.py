"""Test building the local wheels project produces the expected results."""

import os
import shutil
import subprocess
import sys
import tempfile
import venv

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
from venvstacks._util import get_env_python, run_python_command, WINDOWS_BUILD


##################################
# Sample project test helpers
##################################

_THIS_PATH = Path(__file__)
WHEEL_PROJECT_PATH = _THIS_PATH.parent / "local_wheels_project"
WHEEL_PACKAGES_PATH = WHEEL_PROJECT_PATH / "packages"
WHEEL_BUILD_REQUIREMENTS_PATH = WHEEL_PROJECT_PATH / "build-requirements.txt"
WHEEL_PROJECT_STACK_SPEC_PATH = WHEEL_PROJECT_PATH / "venvstacks.toml"
WHEEL_PROJECT_REQUIREMENTS_PATH = WHEEL_PROJECT_PATH / "requirements"
WHEEL_PROJECT_MANIFESTS_PATH = WHEEL_PROJECT_PATH / "expected_manifests"

WHEEL_PROJECT_PATHS = (
    WHEEL_PROJECT_STACK_SPEC_PATH,
    WHEEL_PROJECT_PATH / "dynlib_import.py",
    WHEEL_PROJECT_PATH / "windows_only_dynlib_import.py",
)


class _WheelBuildEnv:
    def __init__(self, working_path: Path) -> None:
        self._working_path = working_path
        self.wheel_path = wheel_path = working_path / "wheels"
        wheel_path.mkdir()
        self._venv_path = venv_path = working_path / "build_venv"
        venv.create(venv_path, symlinks=(not WINDOWS_BUILD), with_pip=True)
        self._python_path = python_path = get_env_python(venv_path)
        self._run_pip_install(
            ["-r", str(WHEEL_BUILD_REQUIREMENTS_PATH)], with_index=True
        )
        self._venv_bin_path = python_path.parent

    def remove_venv(self):
        # Test suite is done with the build, only keep the built wheels around
        shutil.rmtree(self._venv_path)

    def _run_pip(
        self, cmd_args: list[str], **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        command = [
            str(self._python_path),
            "-X",
            "utf8",
            "-Im",
            "pip",
            "--no-input",
            *cmd_args,
        ]
        return run_python_command(command, **kwds)

    def _run_pip_install(
        self, cmd_args: list[str], *, with_index: bool, **kwds: Any
    ) -> subprocess.CompletedProcess[str]:
        return self._run_pip(
            [
                "install",
                *(() if with_index else ("--no-index",)),
                "--no-deps",
                "--only-binary",
                ":all:",
                "--find-links",
                str(self.wheel_path),
                *cmd_args,
            ]
        )

    def build_wheel(self, src_path: Path) -> subprocess.CompletedProcess[str]:
        path_envvar = os.getenv("PATH", "")
        venv_bin_dir = str(self._venv_bin_path)
        env_settings = {
            "PKGCONF_PYPI_EMBEDDED_ONLY": "1",
        }
        if venv_bin_dir not in path_envvar:
            env_settings["PATH"] = f"{venv_bin_dir}{os.pathsep}{path_envvar}"
        result = self._run_pip(
            [
                "wheel",
                "--no-index",
                "--no-build-isolation",  # Build env is managed by the test suite
                "--wheel-dir",
                str(self.wheel_path),
                str(src_path),
            ],
            env=env_settings,
        )
        # Work around https://github.com/mesonbuild/meson-python/issues/639
        # (even when built on later versions, dynlibs are compatible with 3.11)
        normalized_name = src_path.name.replace("-", "_")
        expected_wheel = f"venvstacks_testing_{normalized_name}-*.whl"
        for built_wheel in self.wheel_path.glob(expected_wheel):
            built_name = built_wheel.name
            py_major, py_minor, *_ = sys.version_info
            cp_tag = f"cp{py_major}{py_minor}"
            fixed_name = built_name.replace(cp_tag, "cp311")
            if fixed_name != built_name:
                fixed_path = built_wheel.with_name(fixed_name)
                os.rename(built_wheel, fixed_path)
                print(f"Renamed {built_wheel} -> {fixed_path}")
            break
        else:
            raise RuntimeError(f"Failed to build expected wheel {expected_wheel!r}")
        return result

    def install_built_wheel(self, name: str) -> subprocess.CompletedProcess[str]:
        return self._run_pip_install([name], with_index=False)


def _build_local_wheels(working_path: Path) -> Path:
    build_env = _WheelBuildEnv(working_path)
    build_env.build_wheel(WHEEL_PACKAGES_PATH / "dynlib-publisher")
    build_env.install_built_wheel("venvstacks-testing-dynlib-publisher")
    build_env.build_wheel(WHEEL_PACKAGES_PATH / "dynlib-consumer")
    # Ensure the shared library in the build folder isn't found by the dynamic linker
    build_env.remove_venv()
    return build_env.wheel_path


def _define_build_env(
    working_path: Path, index_config: PackageIndexConfig
) -> BuildEnvironment:
    """Define a build environment for the sample project in a temporary folder."""
    # To avoid side effects from lock file creation, copy input files to the working path
    # This also means these tests cover the "export to the same filesystem" case
    # on all systems (temp folder -> temp folder)
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
    LayeredEnvSummary("broken-publisher", "framework-", "cpython-3.11", ()),
    LayeredEnvSummary(
        "broken-consumer", "framework-", "cpython-3.11", ("broken-publisher",)
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
    ApplicationEnvSummary(
        "via-add-dll-directory",
        "app-",
        "cpython-3.11",
        (
            "broken-consumer",
            "broken-publisher",
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


@pytest.mark.slow
class TestBuildEnvironment(DeploymentTestCase):
    # Test cases that need the full build environment to exist
    EXPECTED_APP_OUTPUT = "Environment launch module executed successfully"

    _wheel_temp_dir: ClassVar[tempfile.TemporaryDirectory | None] = None
    local_wheel_path: ClassVar[Path]
    working_path: Path
    build_env: BuildEnvironment

    @classmethod
    def setUpClass(cls) -> None:
        work_dir = tempfile.TemporaryDirectory()
        cls._wheel_temp_dir = work_dir
        cls.local_wheel_path = _build_local_wheels(Path(work_dir.name))

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
        already_built = [
            env.env_name
            for env in build_env.all_environments()
            if not env.needs_build()
        ]
        self.assertEqual([], already_built)
        build_env.create_environments()
        self.check_build_environments(self.build_env.all_environments())

    def test_locking_and_publishing(self) -> None:
        # Need long diffs to get useful output from metadata checks
        self.maxDiff = None
        # This is organised as subtests in a monolithic test sequence to reduce CI overhead
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
        export_path = self.working_path / "_export🦎"
        subtests_started += 1
        with self.subTest("Check environment export"):
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_path, export_result)
            subtests_passed += 1
        # Rebuild the environments to ensure symlinks aren't corrupted by doing so
        build_env.create_environments(lock=False)
        subtests_started += 1
        with self.subTest("Check rebuilt environment export"):
            export_result = build_env.export_environments(export_path)
            self.check_environment_exports(export_path, export_result)
            subtests_passed += 1

        # Work around pytest-subtests not failing the test case when subtests fail
        # https://github.com/pytest-dev/pytest-subtests/issues/76
        self.assertEqual(
            subtests_passed, subtests_started, "Fail due to failed subtest(s)"
        )
