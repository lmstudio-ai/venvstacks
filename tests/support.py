"""Test support for venvstacks testing"""

import json
import os
import subprocess
import sys
import tomllib
import unittest

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Callable, cast, Mapping, Sequence, TypeVar
from unittest.mock import create_autospec

import pytest

from venvstacks._util import get_env_python, run_python_command

from venvstacks.stacks import (
    BuildEnvironment,
    EnvNameDeploy,
    ExportedEnvironmentPaths,
    ExportMetadata,
    LayerBaseName,
    PackageIndexConfig,
)

_THIS_DIR = Path(__file__).parent

##################################
# Marking test cases
##################################

# Basic marking uses the pytest.mark API directly
# See pyproject.toml and tests/README.md for the defined marks


def requires_venv(description: str) -> pytest.MarkDecorator:
    """Skip test case when running tests outside a virtual environment"""
    return pytest.mark.skipif(
        sys.prefix == sys.base_prefix,
        reason=f"{description} requires test execution in venv",
    )


##################################
# Exporting test artifacts
##################################

TEST_EXPORT_ENV_VAR = (
    "VENVSTACKS_EXPORT_TEST_ARTIFACTS"  # Output directory for artifacts
)
FORCED_EXPORT_ENV_VAR = "VENVSTACKS_FORCE_TEST_EXPORT"  # Force export if non-empty


def get_artifact_export_path() -> Path | None:
    """Location to export notable artifacts generated during test execution"""
    export_dir = os.environ.get(TEST_EXPORT_ENV_VAR)
    if not export_dir:
        return None
    export_path = Path(export_dir)
    if not export_path.exists():
        return None
    return export_path


def force_artifact_export() -> bool:
    """Indicate artifacts should be exported even if a test case passes"""
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


# Applications
@dataclass(frozen=True)
class ApplicationEnvSummary(LayeredEnvSummary):
    framework_spec_names: tuple[str, ...]


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
        if not attr_name.startswith(("_get_pip_", "_get_uv_")):
            continue
        mock_method = getattr(mock_config, attr_name)
        mock_method.side_effect = getattr(reference_config, attr_name)
    return mock_config


##############################################
# Running commands in a deployed environment
##############################################


def capture_python_output(command: list[str]) -> subprocess.CompletedProcess[str]:
    return run_python_command(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def get_sys_path(env_python: Path) -> list[str]:
    command = [str(env_python), "-Ic", "import json, sys; print(json.dumps(sys.path))"]
    result = capture_python_output(command)
    return cast(list[str], json.loads(result.stdout))


def run_module(env_python: Path, module_name: str) -> subprocess.CompletedProcess[str]:
    command = [str(env_python), "-Im", module_name]
    return capture_python_output(command)


###########################################################
# Checking deployed environments for the expected details
###########################################################


class DeploymentTestCase(unittest.TestCase):
    """Native unittest test case with additional deployment validation checks"""
    EXPECTED_APP_OUTPUT = ""

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
            self.assertEqual(launch_result.stdout, self.EXPECTED_APP_OUTPUT)
            self.assertEqual(launch_result.stderr, "")

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
