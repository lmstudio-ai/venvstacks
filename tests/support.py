"""Test support for venvstacks testing."""

import json
import os
import subprocess
import sys
import tomllib
import unittest

from dataclasses import dataclass, fields
from pathlib import Path
from traceback import format_exception
from typing import Any, Callable, cast, Iterable, Mapping, Sequence, TypeVar
from unittest.mock import create_autospec

import pytest

from venvstacks._util import get_env_python, capture_python_output
from venvstacks._injected.postinstall import DEPLOYED_LAYER_CONFIG

from venvstacks.stacks import (
    BuildEnvironment,
    EnvNameDeploy,
    ExportedEnvironmentPaths,
    ExportMetadata,
    LayerBaseName,
    LayerEnvBase,
    LayeredEnvBase,
    LayerVariants,
    PackageIndexConfig,
    StackSpec,
)

_THIS_DIR = Path(__file__).parent

##################################
# Marking test cases
##################################

# Basic marking uses the pytest.mark API directly
# See pyproject.toml and tests/README.md for the defined marks


def requires_venv(description: str) -> pytest.MarkDecorator:
    """Skip test case when running tests outside a virtual environment."""
    return pytest.mark.skipif(
        sys.prefix == sys.base_prefix,
        reason=f"{description} requires test execution in venv",
    )


##################################
# General reporting utilities
##################################


def report_traceback(exc: BaseException | None) -> str:
    if exc is None:
        return "Expected exception was not raised"
    return "\n".join(format_exception(exc))


##################################
# Exporting test artifacts
##################################

TEST_EXPORT_ENV_VAR = (
    "VENVSTACKS_EXPORT_TEST_ARTIFACTS"  # Output directory for artifacts
)
FORCED_EXPORT_ENV_VAR = "VENVSTACKS_FORCE_TEST_EXPORT"  # Force export if non-empty


def get_artifact_export_path() -> Path | None:
    """Location to export notable artifacts generated during test execution."""
    export_dir = os.environ.get(TEST_EXPORT_ENV_VAR)
    if not export_dir:
        return None
    export_path = Path(export_dir)
    if not export_path.exists():
        return None
    return export_path


def force_artifact_export() -> bool:
    """Indicate artifacts should be exported even if a test case passes."""
    # Export is forced if the environment var is defined and non-empty
    return bool(os.environ.get(FORCED_EXPORT_ENV_VAR))


####################################
# Ensuring predictable test output
####################################

# Note: tests that rely on the expected output config should be
#       marked as "expected_output" tests so they're executed
#       when regenerating the expected output files

_OUTPUT_CONFIG_PATH = _THIS_DIR / "expected-output-config.toml"
_OUTPUT_CONFIG: Mapping[str, Any] | None = None


def _cast_config(config_mapping: Any) -> Mapping[str, str]:
    return cast(Mapping[str, str], config_mapping)


def get_output_config() -> Mapping[str, Any]:
    global _OUTPUT_CONFIG
    if _OUTPUT_CONFIG is None:
        data = _OUTPUT_CONFIG_PATH.read_text()
        _OUTPUT_CONFIG = tomllib.loads(data)
    return _OUTPUT_CONFIG


def get_pinned_dev_packages() -> Mapping[str, str]:
    return _cast_config(get_output_config()["pinned-dev-packages"])


def get_os_environ_settings() -> Mapping[str, str]:
    return _cast_config(get_output_config()["env"])


##################################
# Expected layer definitions
##################################


# Runtimes
@dataclass(frozen=True)
class EnvSummary:
    _spec_name: str
    env_prefix: str

    @property
    def spec_name(self) -> LayerBaseName:
        return LayerBaseName(self._spec_name)

    @property
    def env_name(self) -> EnvNameDeploy:
        return EnvNameDeploy(self.env_prefix + self._spec_name)


# Frameworks
@dataclass(frozen=True)
class LayeredEnvSummary(EnvSummary):
    runtime_spec_name: str
    framework_spec_names: tuple[str, ...]


# Applications
@dataclass(frozen=True)
class ApplicationEnvSummary(LayeredEnvSummary):
    pass


############################################
# Reading published and exported manifests
############################################


class ManifestData:
    # Speculative: should this helper class be part of the public venvstacks API?
    combined_data: dict[str, Any]
    snippet_data: list[dict[str, Any]]

    def __init__(self, metadata_path: Path, snippet_paths: list[Path] | None = None):
        if metadata_path.suffix == ".json":
            manifest_path = metadata_path
            metadata_path = metadata_path.parent
        else:
            manifest_path = metadata_path / BuildEnvironment.METADATA_MANIFEST
        if manifest_path.exists():
            manifest_data = json.loads(manifest_path.read_text("utf-8"))
            if not isinstance(manifest_data, dict):
                msg = f"{manifest_path!r} data is not a dict: {manifest_data!r}"
                raise TypeError(msg)
            self.combined_data = manifest_data
        else:
            self.combined_data = {}
        self.snippet_data = snippet_data = []
        if snippet_paths is None:
            snippet_base_path = metadata_path / BuildEnvironment.METADATA_ENV_DIR
            if snippet_base_path.exists():
                snippet_paths = sorted(snippet_base_path.iterdir())
            else:
                snippet_paths = []
        for snippet_path in snippet_paths:
            metadata_snippet = json.loads(snippet_path.read_text("utf-8"))
            if not isinstance(metadata_snippet, dict):
                msg = f"{snippet_path!r} data is not a dict: {metadata_snippet!r}"
                raise TypeError(msg)
            snippet_data.append(metadata_snippet)


##################################
# Expected package index access
##################################


def make_mock_index_config(reference_config: PackageIndexConfig | None = None) -> Any:
    if reference_config is None:
        reference_config = PackageIndexConfig()
    mock_config = create_autospec(reference_config, spec_set=True)
    # Make conditional checks and iteration reflect the actual field values
    checked_methods = ("__bool__", "__len__", "__iter__")
    for field in fields(reference_config):
        attr_name = field.name
        mock_field = getattr(mock_config, attr_name)
        field_value = getattr(reference_config, attr_name)
        for method_name in checked_methods:
            mock_method = getattr(mock_field, method_name, None)
            if mock_method is None:
                continue
            mock_method.side_effect = getattr(field_value, method_name)
    # Still call the actual CLI arg retrieval methods
    for attr_name in dir(reference_config):
        if not attr_name.startswith("_get_uv_"):
            continue
        mock_method = getattr(mock_config, attr_name)
        mock_method.side_effect = getattr(reference_config, attr_name)
    return mock_config


##############################################
# Running commands in a deployed environment
##############################################


def get_sys_path(env_python: Path) -> list[str]:
    command = [
        str(env_python),
        "-X",
        "utf8",
        "-Ic",
        "import json, sys; print(json.dumps(sys.path))",
    ]
    result = capture_python_output(command)
    return cast(list[str], json.loads(result.stdout))


def run_module(env_python: Path, module_name: str) -> subprocess.CompletedProcess[str]:
    command = [str(env_python), "-X", "utf8", "-Im", module_name]
    try:
        return capture_python_output(command)
    except subprocess.CalledProcessError as exc:
        print(exc)
        print(exc.stdout)
        print(exc.stderr)
        raise


#######################################################
# Checking specification loading for expected details
#######################################################


class SpecLoadingTestCase(unittest.TestCase):
    """Native unittest test case with additional spec loading validation checks."""

    def check_stack_specification(
        self,
        expected_spec_path: Path,
        expected_environments: Sequence[EnvSummary],
        expected_runtimes: Sequence[EnvSummary],
        expected_frameworks: Sequence[LayeredEnvSummary],
        expected_applications: Sequence[LayeredEnvSummary],
    ) -> None:
        stack_spec = StackSpec.load(expected_spec_path)
        runtime_keys = list(stack_spec.runtimes)
        framework_keys = list(stack_spec.frameworks)
        application_keys = list(stack_spec.applications)
        spec_keys = runtime_keys + framework_keys + application_keys
        self.assertCountEqual(spec_keys, set(spec_keys))
        expected_spec_names = [env.spec_name for env in expected_environments]
        self.assertCountEqual(expected_spec_names, spec_keys)
        spec_names = [env.name for env in stack_spec.all_environment_specs()]
        self.assertCountEqual(expected_spec_names, spec_names)
        expected_env_names = [env.env_name for env in expected_environments]
        env_names = [env.env_name for env in stack_spec.all_environment_specs()]
        self.assertCountEqual(expected_env_names, env_names)
        for rt_summary in expected_runtimes:
            spec_name = rt_summary.spec_name
            rt_env = stack_spec.runtimes[spec_name]
            self.assertEqual(rt_env.name, spec_name)
            self.assertEqual(rt_env.env_name, rt_summary.env_name)
        del spec_name, rt_env, rt_summary
        for fw_summary in expected_frameworks:
            spec_name = fw_summary.spec_name
            fw_env = stack_spec.frameworks[spec_name]
            self.assertEqual(fw_env.name, spec_name)
            self.assertEqual(fw_env.env_name, fw_summary.env_name)
            self.assertEqual(fw_env.runtime.name, fw_summary.runtime_spec_name)
            fw_dep_names = tuple(spec.name for spec in fw_env.frameworks)
            self.assertEqual(fw_dep_names, fw_summary.framework_spec_names)
        del spec_name, fw_dep_names, fw_env, fw_summary
        for app_summary in expected_applications:
            spec_name = app_summary.spec_name
            app_env = stack_spec.applications[spec_name]
            self.assertEqual(app_env.name, spec_name)
            self.assertEqual(app_env.env_name, app_summary.env_name)
            self.assertEqual(app_env.runtime.name, app_summary.runtime_spec_name)
            fw_dep_names = tuple(spec.name for spec in app_env.frameworks)
            self.assertEqual(fw_dep_names, app_summary.framework_spec_names)
        del spec_name, fw_dep_names, app_env, app_summary
        # Check path attributes
        self.assertEqual(expected_spec_path, stack_spec.spec_path)
        expected_requirements_dir_path = expected_spec_path.parent / "requirements"
        self.assertEqual(
            expected_requirements_dir_path, stack_spec.requirements_dir_path
        )


#######################################################
# Checking deployed environments for expected details
#######################################################


_T = TypeVar("_T", bound=Mapping[str, Any])


class DeploymentTestCase(unittest.TestCase):
    """Native unittest test case with additional deployment validation checks."""

    EXPECTED_APP_OUTPUT = ""

    def assertPathExists(self, expected_path: Path) -> None:
        self.assertTrue(expected_path.exists(), f"No such path: {str(expected_path)}")

    def assertPathContains(self, containing_path: Path, contained_path: Path) -> None:
        self.assertTrue(
            contained_path.is_relative_to(containing_path),
            f"{str(containing_path)!r} is not a parent folder of {str(contained_path)!r}",
        )

    def assertSysPathEntry(self, expected: str, env_sys_path: Sequence[str]) -> None:
        self.assertTrue(
            any(expected in path_entry for path_entry in env_sys_path),
            f"No entry containing {expected!r} found in {env_sys_path}",
        )

    def check_env_sys_path(
        self,
        env_path: Path,
        env_sys_path: Sequence[str],
        *,
        self_contained: bool = False,
    ) -> None:
        sys_path_entries = [Path(path_entry) for path_entry in env_sys_path]
        # Regardless of env type, sys.path entries must be absolute
        self.assertTrue(
            all(p.is_absolute() for p in sys_path_entries),
            f"Relative path entry found in {env_sys_path}",
        )
        # Regardless of env type, sys.path entries must exist
        # (except the stdlib's optional zip archive entry)
        for path_entry in sys_path_entries:
            if path_entry.suffix:
                continue
            self.assertPathExists(path_entry)

        # Check for sys.path references outside this environment
        def _is_relative_to(p: Path, base_path: Path) -> bool:
            # Also accept paths which have been fully resolved by the Python runtime
            return p.is_relative_to(base_path) or p.is_relative_to(base_path.resolve())

        if self_contained:
            # All sys.path entries should be inside the environment
            self.assertTrue(
                all(_is_relative_to(p, env_path) for p in sys_path_entries),
                f"Path outside deployed {env_path} in {env_sys_path}",
            )
        else:
            # All sys.path entries should be inside the environment's parent,
            # but at least one sys.path entry should refer to a peer environment
            peer_env_path = env_path.parent
            self.assertTrue(
                all(_is_relative_to(p, peer_env_path) for p in sys_path_entries),
                f"Path outside deployed {peer_env_path} in {env_sys_path}",
            )
            self.assertFalse(
                all(_is_relative_to(p, env_path) for p in sys_path_entries),
                f"No path outside deployed {env_path} in {env_sys_path}",
            )

    def check_build_environments(self, build_envs: Iterable[LayerEnvBase]) -> None:
        for env in build_envs:
            env_path = env.env_path
            config_path = env_path / DEPLOYED_LAYER_CONFIG
            self.assertPathExists(config_path)
            layer_config = json.loads(config_path.read_text(encoding="utf-8"))
            env_python = env_path / layer_config["python"]
            expected_python_path = env.python_path
            self.assertEqual(str(expected_python_path), str(env_python))
            base_python_path = env_path / layer_config["base_python"]
            is_runtime_env = env.kind == LayerVariants.RUNTIME
            if is_runtime_env:
                # base_python should refer to the runtime layer itself
                # without any normalisation of parent folder references
                expected_base_python_path = expected_python_path
            else:
                # base_python should refer to the venv's deployed base Python runtime
                base_runtime = cast(LayeredEnvBase, env).base_runtime
                self.assertIsNotNone(base_runtime)
                assert base_runtime is not None
                relative_base_python = base_runtime.python_path.relative_to(
                    base_runtime.env_path
                )
                expected_base_python_path = Path(
                    env_path, "..", base_runtime.install_target, relative_base_python
                )
            self.assertEqual(str(expected_base_python_path), str(base_python_path))
            env_sys_path = get_sys_path(env_python)
            # Base runtime environments are expected to be self-contained
            self.check_env_sys_path(
                env_path, env_sys_path, self_contained=is_runtime_env
            )
            # Only Python executables, links and/or wrapper scripts should be present
            bin_path = env.executables_path
            self.assertEqual(list(bin_path.glob("python*")), list(bin_path.iterdir()))
            # RECORD files should exist, *without* any entries for executables
            pylib_path = env.pylib_path
            if next(pylib_path.glob("*.dist-info"), None) is not None:
                # Env has at least one package installed, so RECORD files should exist
                record_paths = [*pylib_path.rglob("RECORD")]
                self.assertNotEqual(record_paths, [])
                # No executables should be listed in any RECORD file
                bin_pattern = f"/../{bin_path.name}/"
                for record_path in record_paths:
                    if bin_pattern in record_path.read_text(encoding="utf-8"):
                        self.fail(f"{bin_pattern!r} found in {str(record_path)!r}")
            if env.needs_build():
                # Check the individual elements of the build validity check
                self.assertTrue(env.env_path.exists())
                self.assertTrue(env._build_metadata_path.exists())
                last_metadata = env._load_last_build_metadata()
                self.assertEqual(last_metadata, env._get_build_metadata())
                self.fail(
                    f"Layer {env.env_name!r} still needs building for an unknown reason"
                )

    def check_deployed_environments(
        self,
        layered_metadata: dict[str, Sequence[_T]],
        get_env_details: Callable[[_T], tuple[str, Path, list[str]]],
    ) -> None:
        for rt_env in layered_metadata["runtimes"]:
            env_name, env_path, env_sys_path = get_env_details(rt_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Runtime environment layer should be completely self-contained
            self.check_env_sys_path(env_path, env_sys_path, self_contained=True)
            # No hidden build files should be published
            self.assertEqual(list(env_path.glob(".*")), [])
        for fw_env in layered_metadata["frameworks"]:
            env_name, env_path, env_sys_path = get_env_details(fw_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Frameworks are expected to reference *at least* their base runtime environment
            self.check_env_sys_path(env_path, env_sys_path)
            # Framework and runtime should both appear in sys.path
            runtime_layer = fw_env["runtime_layer"]
            short_runtime_name = ".".join(runtime_layer.split(".")[:2])
            self.assertSysPathEntry(env_name, env_sys_path)
            self.assertSysPathEntry(short_runtime_name, env_sys_path)
            # No hidden build files should be published
            self.assertEqual(list(env_path.glob(".*")), [])
        for app_env in layered_metadata["applications"]:
            env_name, env_path, env_sys_path = get_env_details(app_env)
            self.assertTrue(env_sys_path)  # Environment should have sys.path entries
            # Applications are expected to reference *at least* their base runtime environment
            self.check_env_sys_path(env_path, env_sys_path)
            # Application, frameworks and runtime should all appear in sys.path
            runtime_layer = app_env["runtime_layer"]
            short_runtime_name = ".".join(runtime_layer.split(".")[:2])
            self.assertSysPathEntry(env_name, env_sys_path)
            self.assertTrue(
                any(env_name in path_entry for path_entry in env_sys_path),
                f"No entry containing {env_name} found in {env_sys_path}",
            )
            for fw_env_name in app_env["required_layers"]:
                self.assertSysPathEntry(fw_env_name, env_sys_path)
            self.assertSysPathEntry(short_runtime_name, env_sys_path)
            # No hidden build files should be published
            self.assertEqual(list(env_path.glob(".*")), [])
            # Launch module should be executable
            env_config_path = env_path / DEPLOYED_LAYER_CONFIG
            env_config = json.loads(env_config_path.read_text(encoding="utf-8"))
            env_python = env_path / env_config["python"]
            launch_module = app_env["app_launch_module"]
            # Ensure the external and internal launch metadata is consistent
            assert env_config["launch_module"] == launch_module
            launch_result = run_module(env_python, launch_module)
            # Tolerate extra trailing whitespace on stdout
            self.assertEqual(self.EXPECTED_APP_OUTPUT, launch_result.stdout.rstrip())
            # Nothing at all should be emitted on stderr
            self.assertEqual("", launch_result.stderr)
            # Support modules should be available for import
            support_module_info = app_env.get("app_support_modules")
            if support_module_info is not None:
                self.assertGreater(len(support_module_info), 0)
                for module_info in support_module_info:
                    # Any support modules used in test cases produce no output
                    # (other than potentially a newline indicator)
                    mod_exec_result = run_module(env_python, module_info["name"])
                    self.assertEqual("", mod_exec_result.stdout.rstrip())
                    self.assertEqual("", mod_exec_result.stderr)

    def check_environment_exports(
        self, export_path: Path, export_paths: ExportedEnvironmentPaths
    ) -> None:
        metadata_path, snippet_paths, env_paths = export_paths
        exported_manifests = ManifestData(metadata_path, snippet_paths)
        env_name_to_path: dict[str, Path] = {}
        for env_metadata, env_path in zip(exported_manifests.snippet_data, env_paths):
            # TODO: Check more details regarding expected metadata contents
            self.assertPathExists(env_path)
            self.assertPathContains(export_path, env_path)
            env_name = EnvNameDeploy(env_metadata["install_target"])
            self.assertEqual(env_path.name, env_name)
            env_name_to_path[env_name] = env_path
        layered_metadata = exported_manifests.combined_data["layers"]

        def get_exported_env_details(
            env: ExportMetadata,
        ) -> tuple[EnvNameDeploy, Path, list[str]]:
            env_name = env["install_target"]
            env_path = env_name_to_path[env_name]
            env_python = get_env_python(env_path)
            env_sys_path = get_sys_path(env_python)
            return env_name, env_path, env_sys_path

        self.check_deployed_environments(layered_metadata, get_exported_env_details)
