"""Test cases for CLI invocation."""

import subprocess
import sys

from collections import namedtuple
from contextlib import contextmanager
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    cast,
    Generator,
    get_type_hints,
    Iterable,
    Iterator,
    Self,
    Sequence,
    Set,
)
from unittest.mock import call as mock_call, create_autospec, MagicMock, patch

import pytest

import click.testing
import typer
from typer.models import ArgumentInfo, OptionInfo
from typer.testing import CliRunner

from venvstacks import cli
from venvstacks.stacks import (
    BuildEnvironment,
    EnvNameBuild,
    EnvironmentLock,
    PackageIndexConfig,
    StackStatus,
)
from venvstacks._util import run_python_command_unchecked

from support import report_traceback, requires_venv


def _mock_path(contents: str | None = None) -> Any:
    mock_path = create_autospec(Path, spec_set=True, instance=True)
    mock_path.exists.return_value = True
    if contents is None:
        # Pretend this is a directory path
        mock_path.is_dir.return_value = True
    else:
        # Pretend this is a readable file path
        mock_path.read_text.return_value = contents
        mock_path.is_dir.return_value = False
    return mock_path


def mock_environment_locking(*, clean: bool = False) -> Sequence[EnvironmentLock]:
    return []


def mock_output_generation(output_dir: Path, *, dry_run: bool = False, **_: Any) -> Any:
    if dry_run:
        return _mock_path(), {}
    return _mock_path("{}"), [], []


MOCK_LAYERS = ["runtime", "framework-A", "framework-B", "app-1", "app-2", "app-3"]

MockEnv = namedtuple("MockEnv", ("env_name",))


def mock_environment_iterator() -> Iterator[MockEnv]:
    for env_name in MOCK_LAYERS:
        yield MockEnv(env_name)


def mock_layer_filtering(patterns: Iterable[str]) -> tuple[Set[EnvNameBuild], Set[str]]:
    matching = set(
        env for env in MOCK_LAYERS if any(fnmatch(env, pattern) for pattern in patterns)
    )
    return cast(Set[EnvNameBuild], matching), set()


def mock_stack_status(
    *, report_ops: bool = True, include_deps: bool = False
) -> StackStatus:
    return {
        "applications": [],
        "frameworks": [],
        "runtimes": [],
        "spec_name": "/no/such/spec",
    }


@dataclass(repr=False, eq=False)
class MockedRunner:
    app: typer.Typer
    mocked_stack_spec: MagicMock

    runner: CliRunner = field(init=False)
    mocked_build_env: MagicMock = field(init=False)

    def __post_init__(self) -> None:
        # Note: `mock` doesn't quite handle `dataclass` instances correctly
        #       (see https://github.com/python/cpython/issues/124176 for details)
        #       However, the CLI doesn't currently try to access any of the missing
        #       attributes, so the autospec mocking here is sufficient in practice.
        self.runner = CliRunner(catch_exceptions=False)
        mocked_stack_spec = self.mocked_stack_spec
        # Use the patched in mock as the sole defined spec instance
        mocked_stack_spec.load.return_value = mocked_stack_spec
        # Patch in a mocked build environment
        mocked_build_env = create_autospec(
            BuildEnvironment, spec_set=True, instance=True
        )
        # use the mocked build environment in test cases
        mocked_stack_spec.define_build_environment.return_value = mocked_build_env
        self.mocked_build_env = mocked_build_env
        # Control the result of the environment locking step
        mocked_build_env.lock_environments.side_effect = mock_environment_locking
        # Control the result of the layer filter step
        mocked_build_env.all_environments.side_effect = mock_environment_iterator
        mocked_build_env.filter_layers.side_effect = mock_layer_filtering
        # Control the result of artifact publication and environment exports
        mocked_build_env.publish_artifacts.side_effect = mock_output_generation
        mocked_build_env.export_environments.side_effect = mock_output_generation
        # Control the result of stack status queries
        mocked_build_env.get_stack_status.side_effect = mock_stack_status

    @classmethod
    @contextmanager
    def cli_patch_installed(cls, cli_module: ModuleType) -> Iterator[Self]:
        """Patch the given CLI module to invoke a mocked StackSpec instance."""
        app = cli_module._cli
        patch_cm = patch.object(cli_module, "StackSpec", autospec=True, spec_set=True)
        with patch_cm as mocked_stack_spec:
            yield cls(app, mocked_stack_spec)

    def invoke(self, cli_args: list[str]) -> click.testing.Result:
        return self.runner.invoke(self.app, cli_args)

    def assert_build_config(self, expected_build_dir: str) -> None:
        """Check environment build path and index configuration details."""
        env_definition = self.mocked_stack_spec.define_build_environment
        env_definition.assert_called_with(expected_build_dir)

    _OUTPUT_METHODS = {
        "build": "publish_artifacts",
        "publish": "publish_artifacts",
        "local-export": "export_environments",
    }

    def get_output_method(self, command: str) -> MagicMock:
        """Return the Mock expected to be called for the given output command."""
        output_method_name = self._OUTPUT_METHODS[command]
        return cast(MagicMock, getattr(self.mocked_build_env, output_method_name))

    _DEFAULT_OUTPUT_DIRS = {
        "build": "_artifacts",
        "publish": "_artifacts",
        "local-export": "_export",
    }

    def get_default_output_dir(self, command: str) -> str:
        """Return the Mock expected to be called for the given output command."""
        return self._DEFAULT_OUTPUT_DIRS[command]


@pytest.fixture
def mocked_runner() -> Generator[MockedRunner, None, None]:
    with MockedRunner.cli_patch_installed(cli) as mocked_app:
        yield mocked_app


class TestTopLevelCommand:
    def test_implicit_help(self, mocked_runner: MockedRunner) -> None:
        result = mocked_runner.invoke([])
        # Usage message should suggest indirect execution
        assert "Usage: python -m venvstacks [" in result.stdout
        # Top-level callback docstring is used as the overall CLI help text
        cli_help = cli.handle_app_options.__doc__
        assert cli_help is not None
        assert cli_help.strip() in result.stdout
        # Subcommands are listed in the top level help
        assert str(cli.build.__name__) in result.stdout
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0
        assert not result.stderr

    @requires_venv("Entry point test")
    def test_entry_point_help_raw(self) -> None:
        expected_entry_point = Path(sys.executable).parent / "venvstacks"
        command = [str(expected_entry_point), "--help"]
        subprocess_result = run_python_command_unchecked(
            command, text=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if subprocess_result.stdout:
            # Usage message should suggest direct execution
            assert b"Usage: venvstacks [" in subprocess_result.stdout
            # Top-level callback docstring is used as the overall CLI help text
            cli_help = cli.handle_app_options.__doc__
            assert cli_help is not None
            assert cli_help.strip().encode() in subprocess_result.stdout
        # Check operation result last to ensure test results are as informative as possible
        assert subprocess_result.returncode == 0
        assert subprocess_result.stdout
        assert not subprocess_result.stderr

    @requires_venv("Entry point test")
    def test_entry_point_help(self) -> None:
        expected_entry_point = Path(sys.executable).parent / "venvstacks"
        command = [str(expected_entry_point), "--help"]
        result = run_python_command_unchecked(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.stdout is not None:
            # Usage message should suggest direct execution
            assert "Usage: venvstacks [" in result.stdout
            # Top-level callback docstring is used as the overall CLI help text
            cli_help = cli.handle_app_options.__doc__
            assert cli_help is not None
            assert cli_help.strip() in result.stdout
        # Check operation result last to ensure test results are as informative as possible
        assert result.returncode == 0
        assert result.stdout
        assert not result.stderr

    def test_module_execution(self) -> None:
        # TODO: `coverage.py` isn't picking this up as executing `venvstacks/__main__.py`
        #       (even an indirect invocation via the runpy module doesn't get detected)
        command = [sys.executable, "-m", "venvstacks", "--help"]
        result = run_python_command_unchecked(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        if result.stdout:
            # Usage message should suggest indirect execution
            assert "Usage: python -m venvstacks [" in result.stdout
            # Top-level callback docstring is used as the overall CLI help text
            cli_help = cli.handle_app_options.__doc__
            assert cli_help is not None
            assert cli_help.strip() in result.stdout
        # Check operation result last to ensure test results are as informative as possible
        assert result.returncode == 0
        assert result.stdout
        assert not result.stderr


EXPECTED_USAGE_PREFIX = "Usage: python -m venvstacks "
EXPECTED_SUBCOMMANDS = ["show", "lock", "build", "local-export", "publish"]
NO_SPEC_PATH: list[str] = []
NEEDS_SPEC_PATH = sorted(set(EXPECTED_SUBCOMMANDS) - set(NO_SPEC_PATH))
ACCEPTS_BUILD_DIR = ["show", "lock", "build", "local-export", "publish"]
ACCEPTS_OUTPUT_DIR = ["build", "local-export", "publish"]
ACCEPTS_INDEX_CONFIG = ["lock", "build"]
ACCEPTS_RESET_LOCK = ["lock", "build"]
ACCEPTS_SHOW_ONLY = ["lock", "build", "local-export", "publish"]


def _get_default_index_config(command: str) -> PackageIndexConfig:
    if command in ACCEPTS_INDEX_CONFIG:
        return PackageIndexConfig()
    # Commands that don't support index access should turn it off in their config
    return PackageIndexConfig.disabled()


ARGUMENT_PREFIX = "_CLI_ARG"
OPTION_PREFIXES = {
    bool: "_CLI_OPT_FLAG",
    bool | None: "_CLI_OPT_TRISTATE",
    list[str] | None: "_CLI_OPT_STRLIST",
    str: "_CLI_OPT_STR",
}


class TestSubcommands:
    @pytest.mark.parametrize("command", EXPECTED_SUBCOMMANDS)
    def test_internal_consistency(self, command: str) -> None:
        # Check all CLI annotations are internally consistent:
        #   * ensures all used _CLI prefixes are consistent with their types
        #   * ensures all arg names are consistent with annotation suffixes
        command_impl_name = command.replace("-", "_")
        command_impl = getattr(cli, command_impl_name)
        annotations = get_type_hints(command_impl, include_extras=True)
        for arg_name, arg_annotation in annotations.items():
            if arg_name == "return":
                assert arg_annotation is type(None)
                continue
            arg_kind = type(arg_annotation.__metadata__[0])
            assert arg_kind is ArgumentInfo or arg_kind is OptionInfo
            arg_type = arg_annotation.__origin__
            if arg_kind is ArgumentInfo:
                expected_text_prefix = ARGUMENT_PREFIX
            else:
                option_prefix = OPTION_PREFIXES.get(arg_type)
                if option_prefix is None:
                    assert False, f"No CLI option prefix defined for {arg_type!r}"
                expected_text_prefix = option_prefix
            expected_annotation_name = f"{expected_text_prefix}_{arg_name}"
            named_annotation = getattr(cli, expected_annotation_name)
            assert named_annotation == arg_annotation

    @pytest.mark.parametrize("command", EXPECTED_SUBCOMMANDS)
    def test_help_option(self, mocked_runner: MockedRunner, command: str) -> None:
        result = mocked_runner.invoke([command, "--help"])
        # Command implementation docstring is used as the subcommand help text
        command_impl_name = command.replace("-", "_")
        command_impl = getattr(cli, command_impl_name)
        cli_help = command_impl.__doc__
        assert cli_help is not None
        assert cli_help.strip() in result.stdout
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        mocked_stack_spec.define_build_environment.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0
        assert not result.stderr

    @pytest.mark.parametrize("command", NEEDS_SPEC_PATH)
    def test_usage_error(self, mocked_runner: MockedRunner, command: str) -> None:
        result = mocked_runner.invoke([command])
        # No overall help in a usage error
        command_impl_name = command.replace("-", "_")
        command_impl = getattr(cli, command_impl_name)
        cli_help = command_impl.__doc__
        assert cli_help is not None
        assert cli_help.strip() not in result.stderr
        # Should complain about the missing required argument
        assert result.stderr[: len(EXPECTED_USAGE_PREFIX)] == EXPECTED_USAGE_PREFIX
        assert "Missing argument 'SPEC_PATH'" in result.stderr
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        mocked_stack_spec.define_build_environment.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert isinstance(result.exception, SystemExit), report_traceback(
            result.exception
        )
        assert result.exit_code == 2
        assert not result.stdout

    @pytest.mark.parametrize("command", ACCEPTS_BUILD_DIR)
    def test_build_dir_configuration(
        self, mocked_runner: MockedRunner, command: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(
            [command, "--build-dir", "custom", spec_path_to_mock]
        )
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "custom"
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        if command in ACCEPTS_OUTPUT_DIR:
            # Only check the output path (other tests check the other parameters)
            output_method = mocked_runner.get_output_method(command)
            expected_output_dir = mocked_runner.get_default_output_dir(command)
            output_method.assert_called_once()
            assert output_method.call_args.args == (expected_output_dir,)
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @pytest.mark.parametrize("command", ACCEPTS_OUTPUT_DIR)
    def test_output_dir_configuration(
        self, mocked_runner: MockedRunner, command: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(
            [command, "--output-dir", "custom", spec_path_to_mock]
        )
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_output_dir = "custom"
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Only check the output path (other tests check the other parameters)
        output_method = mocked_runner.get_output_method(command)
        output_method.assert_called_once()
        assert output_method.call_args.args == (expected_output_dir,)
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    # All commands that accept --build-dir should also accept --include
    @pytest.mark.parametrize("command", ACCEPTS_BUILD_DIR)
    def test_layer_selection(self, mocked_runner: MockedRunner, command: str) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(
            [command, "--include", "app-*", spec_path_to_mock]
        )
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Only check the layer selection invocation
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_not_called()
        mocked_build_env.filter_layers.assert_called_once_with(
            ["app-*"],
        )
        layer_selection = mocked_build_env.select_layers
        layer_selection.assert_called_once()
        expected_layers = set(env for env in MOCK_LAYERS if env.startswith("app-"))
        assert layer_selection.call_args.args == (expected_layers,)
        assert layer_selection.call_args.kwargs["reset_locks"] == ()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @pytest.mark.parametrize("command", ACCEPTS_RESET_LOCK)
    def test_lock_reset_selection(
        self, mocked_runner: MockedRunner, command: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(
            [command, "--reset-lock", "app-*", spec_path_to_mock]
        )
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Only check the layer selection invocation
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_not_called()
        mocked_build_env.filter_layers.assert_called_once_with(
            ["app-*"],
        )
        layer_selection = mocked_build_env.select_layers
        layer_selection.assert_called_once()
        assert layer_selection.call_args.args == (MOCK_LAYERS,)
        expected_layers = set(env for env in MOCK_LAYERS if env.startswith("app-"))
        assert layer_selection.call_args.kwargs["reset_locks"] == expected_layers
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @pytest.mark.parametrize("command", ACCEPTS_RESET_LOCK)
    def test_layer_selection_with_lock_reset(
        self, mocked_runner: MockedRunner, command: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(
            [command, "--include", "app-*", "--reset-lock", "*", spec_path_to_mock]
        )
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Only check the layer selection invocation
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_not_called()
        mocked_build_env.filter_layers.assert_has_calls(
            (
                mock_call(["app-*"]),
                mock_call(["*"]),
            )
        )
        layer_selection = mocked_build_env.select_layers
        layer_selection.assert_called_once()
        expected_layers = set(env for env in MOCK_LAYERS if env.startswith("app-"))
        assert layer_selection.call_args.args == (expected_layers,)
        assert layer_selection.call_args.kwargs["reset_locks"] == set(MOCK_LAYERS)
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @staticmethod
    def _cli_args_case_id(cli_args_test_case: tuple[Any, ...]) -> str:
        extra_cli_args: tuple[str, ...] = cli_args_test_case[0]
        return f"({' '.join(extra_cli_args)})"

    # CLI option handling test cases for package index access configuration
    IndexConfigCase = tuple[tuple[str, ...], PackageIndexConfig]
    _INDEX_CONFIG_ARGS = (
        # Define how the relevant CLI options map to build environment config settings
        (
            (),
            PackageIndexConfig(
                query_default_index=True,
                local_wheel_dirs=None,
            ),
        ),
        (
            ("--no-index",),
            PackageIndexConfig(
                query_default_index=False,
                local_wheel_dirs=None,
            ),
        ),
        (
            ("--local-wheels", "/some_dir", "--local-wheels", "some/other/dir"),
            PackageIndexConfig(
                query_default_index=True,
                local_wheel_dirs=["/some_dir", "some/other/dir"],
            ),
        ),
    )

    @pytest.mark.parametrize("cli_test_case", _INDEX_CONFIG_ARGS, ids=_cli_args_case_id)
    @pytest.mark.parametrize("command", ACCEPTS_INDEX_CONFIG)
    def test_index_options(
        self, mocked_runner: MockedRunner, command: str, cli_test_case: IndexConfigCase
    ) -> None:
        extra_cli_args, expected_index_config = cli_test_case
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke([command, *extra_cli_args, spec_path_to_mock])
        # Always loads the stack spec
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        # Check build environment is created with the expected options
        mocked_runner.assert_build_config(expected_build_dir)
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @pytest.mark.parametrize("command", ACCEPTS_SHOW_ONLY)
    def test_show_only_option(self, mocked_runner: MockedRunner, command: str) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke([command, "--show-only", spec_path_to_mock])
        if result.exception is not None:
            print(report_traceback(result.exception))
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_index_config = _get_default_index_config(command)
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        # Op selection details are checked elsewhere
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once()
        mocked_build_env.select_layers.assert_not_called()
        mocked_build_env.get_stack_status.assert_called_once_with(
            report_ops=True, include_deps=False
        )
        # Doesn't perform any actual operations on the environment
        mocked_build_env.lock_environments.assert_not_called()
        mocked_build_env.create_environments.assert_not_called()
        mocked_build_env.publish_artifacts.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    def test_mock_show(self, mocked_runner: MockedRunner) -> None:
        # Note: unmocked `show` invocation is checked in test_minimal_project
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["show", spec_path_to_mock])
        if result.exception is not None:
            print(report_traceback(result.exception))
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_index_config = PackageIndexConfig.disabled()
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        # Op selection details are checked elsewhere
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once()
        mocked_build_env.select_layers.assert_not_called()
        mocked_build_env.get_stack_status.assert_called_once_with(
            report_ops=False, include_deps=True
        )
        # Doesn't perform any actual operations on the environment
        mocked_build_env.lock_environments.assert_not_called()
        mocked_build_env.create_environments.assert_not_called()
        mocked_build_env.publish_artifacts.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    # Specific CLI option handling test cases for the "build" subcommand
    BuildFlagCase = tuple[
        tuple[str, ...], dict[str, bool], dict[str, bool], dict[str, bool]
    ]
    _BUILD_OPTIONS = (
        # Define how the various flags in the CLI build subcommand map to API method options
        # CLI vs API distinction: `--[no-]publish` controls the `dry_run` publication flag
        #                         rather than controlling the `publish` operation selection
        # `--include` and its related options are tested separately
        (
            (),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--show",),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--show", "--json"),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--lock-if-needed",),
            dict(lock=None, build=True, publish=True),  # select_operations
            dict(clean=False, lock=None),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--lock",),  # Check legacy option name for --lock-if-needed
            dict(lock=None, build=True, publish=True),  # select_operations
            dict(clean=False, lock=None),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--publish",),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(force=False, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--clean",),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=True, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--publish", "--clean"),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=True, lock=False),  # create_environments
            dict(force=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--tag-outputs",),
            dict(lock=False, build=True, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=True),  # publish_artifacts
        ),
        (
            ("--lock-if-needed", "--build", "--publish", "--clean", "--tag-outputs"),
            dict(lock=None, build=True, publish=True),  # select_operations
            dict(clean=True, lock=None),  # create_environments
            dict(force=True, tag_outputs=True),  # publish_artifacts
        ),
        (
            # Check legacy option name for --lock-if-needed
            ("--lock", "--build", "--publish", "--clean", "--tag-outputs"),
            dict(lock=None, build=True, publish=True),  # select_operations
            dict(clean=True, lock=None),  # create_environments
            dict(force=True, tag_outputs=True),  # publish_artifacts
        ),
        (
            (
                "--no-lock-if-needed",
                "--no-build",
                "--no-publish",
                "--no-clean",
                "--no-tag-outputs",
            ),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            (
                "--no-lock",  # Check legacy option name for --no-lock-if-needed
                "--no-build",
                "--no-publish",
                "--no-clean",
                "--no-tag-outputs",
            ),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(clean=False, lock=False),  # create_environments
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
    )

    @pytest.mark.parametrize("cli_test_case", _BUILD_OPTIONS, ids=_cli_args_case_id)
    def test_mock_build_op_selection(
        self, mocked_runner: MockedRunner, cli_test_case: BuildFlagCase
    ) -> None:
        cli_flags, expected_select_args, expected_create_args, expected_publish_args = (
            cli_test_case
        )
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["build", *cli_flags, spec_path_to_mock])
        if result.exception is not None:
            print(report_traceback(result.exception))
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_output_dir = "_artifacts"
        expected_index_config = PackageIndexConfig()
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Defaults to selecting operations rather than layers
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once_with(
            **expected_select_args
        )
        mocked_build_env.select_layers.assert_not_called()
        if "--show" in cli_flags or "--json" in cli_flags:
            mocked_build_env.get_stack_status.assert_called_once_with(
                report_ops=True, include_deps=False
            )
        else:
            mocked_build_env.get_stack_status.assert_not_called()
        # Always creates the environments to perform the requested operations
        mocked_build_env.create_environments.assert_called_once_with(
            **expected_create_args
        )
        # "Disabling" artifact publication triggers a dry run rather than skipping it completely
        mocked_build_env.publish_artifacts.assert_called_once_with(
            expected_output_dir, **expected_publish_args
        )
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None
        assert result.exit_code == 0

    # Specific CLI option handling test cases for the "lock" subcommand
    LockFlagCase = tuple[tuple[str, ...], dict[str, bool], dict[str, bool]]
    _LOCK_OPTIONS = (
        # Define how the various flags in the CLI lock subcommand map to API method options
        # `--include` and its related options are tested separately
        (
            (),
            dict(lock=True, build=False, publish=False),  # select_operations
            dict(clean=False),  # lock_environments
        ),
        (
            ("--show",),
            dict(lock=True, build=False, publish=False),  # select_operations
            dict(clean=False),  # lock_environments
        ),
        (
            ("--show", "--json"),
            dict(lock=True, build=False, publish=False),  # select_operations
            dict(clean=False),  # lock_environments
        ),
        (
            ("--clean",),
            dict(lock=True, build=False, publish=False),  # select_operations
            dict(clean=True),  # lock_environments
        ),
        (
            ("--if-needed",),
            dict(lock=None, build=False, publish=False),  # select_operations
            dict(clean=False),  # lock_environments
        ),
        (
            (
                "--no-clean",
                "--no-if-needed",
            ),
            dict(lock=True, build=False, publish=False),  # select_operations
            dict(clean=False),  # lock_environments
        ),
    )

    @pytest.mark.parametrize("cli_test_case", _LOCK_OPTIONS, ids=_cli_args_case_id)
    def test_mock_lock_op_selection(
        self, mocked_runner: MockedRunner, cli_test_case: LockFlagCase
    ) -> None:
        cli_flags, expected_select_args, expected_lock_args = cli_test_case
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["lock", *cli_flags, spec_path_to_mock])
        if result.exception is not None:
            print(report_traceback(result.exception))
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_index_config = PackageIndexConfig()
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Defaults to selecting operations rather than layers
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once_with(
            **expected_select_args
        )
        mocked_build_env.select_layers.assert_not_called()
        if "--show" in cli_flags or "--json" in cli_flags:
            mocked_build_env.get_stack_status.assert_called_once_with(
                report_ops=True, include_deps=False
            )
        else:
            mocked_build_env.get_stack_status.assert_not_called()
        # Only locks the environments without fully building them
        mocked_build_env.lock_environments.assert_called_once_with(**expected_lock_args)
        mocked_build_env.create_environments.assert_not_called()
        # The lock subcommand doesn't even attempt the publication step
        mocked_build_env.publish_artifacts.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @staticmethod
    def get_invalid_lock_options() -> Generator[str, None, None]:
        # List of flags to check was defined when 'lock' was extracted from 'build'
        invalid_flag_names = ("lock", "build", "publish", "tag-outputs")
        for name in invalid_flag_names:
            yield f"--{name}"
            yield f"--no-{name}"

    @pytest.mark.parametrize("invalid_flag", list(get_invalid_lock_options()))
    def test_mock_lock_usage_error(
        self, mocked_runner: MockedRunner, invalid_flag: str
    ) -> None:
        mocked_spec_path = "/no/such/path/spec"
        result = mocked_runner.invoke(["lock", invalid_flag, mocked_spec_path])
        # Should complain about the invalid flag
        assert result.stderr[: len(EXPECTED_USAGE_PREFIX)] == EXPECTED_USAGE_PREFIX
        assert "Try 'python -m venvstacks lock --help' for help." in result.stderr
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        mocked_stack_spec.define_build_environment.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert isinstance(result.exception, SystemExit), report_traceback(
            result.exception
        )
        assert result.exit_code == 2
        assert not result.stdout

    # Specific CLI option handling test cases for the "publish" subcommand
    PublishFlagCase = tuple[tuple[str, ...], dict[str, bool], dict[str, bool]]
    _PUBLISH_OPTIONS = (
        # Define how the various flags in the CLI lock subcommand map to API method options
        # `--include` and its related options are tested separately
        (
            (),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--show",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--show", "--json"),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--force",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--dry-run",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(dry_run=True, tag_outputs=False),  # publish_artifacts
        ),
        (
            ("--tag-outputs",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False, tag_outputs=True),  # publish_artifacts
        ),
        (
            (
                "--no-force",
                "--no-dry-run",
                "--no-tag-outputs",
            ),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False, tag_outputs=False),  # publish_artifacts
        ),
    )

    @pytest.mark.parametrize("cli_test_case", _PUBLISH_OPTIONS, ids=_cli_args_case_id)
    def test_mock_publish_op_selection(
        self, mocked_runner: MockedRunner, cli_test_case: PublishFlagCase
    ) -> None:
        cli_flags, expected_select_args, expected_publish_args = cli_test_case
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["publish", *cli_flags, spec_path_to_mock])
        if result.exception is not None:
            print(report_traceback(result.exception))
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_output_dir = "_artifacts"
        expected_index_config = PackageIndexConfig.disabled()
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Defaults to selecting operations rather than layers
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once_with(
            **expected_select_args
        )
        mocked_build_env.select_layers.assert_not_called()
        if "--show" in cli_flags or "--json" in cli_flags:
            mocked_build_env.get_stack_status.assert_called_once_with(
                report_ops=True, include_deps=False
            )
        else:
            mocked_build_env.get_stack_status.assert_not_called()
        # The publish subcommand assumes the environments are already created
        mocked_build_env.create_environments.assert_not_called()
        # The publish subcommand always attempts to publish the artifacts
        mocked_build_env.publish_artifacts.assert_called_once_with(
            expected_output_dir, **expected_publish_args
        )
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @staticmethod
    def get_invalid_publish_options() -> Generator[str, None, None]:
        # List of flags to check was defined when 'publish' was extracted from 'build'
        invalid_flag_names = ("lock", "build", "publish", "clean")
        for name in invalid_flag_names:
            yield f"--{name}"
            yield f"--no-{name}"

    @pytest.mark.parametrize("invalid_flag", list(get_invalid_publish_options()))
    def test_mock_publish_usage_error(
        self, mocked_runner: MockedRunner, invalid_flag: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["publish", invalid_flag, spec_path_to_mock])
        # Should complain about the invalid flag
        assert result.stderr[: len(EXPECTED_USAGE_PREFIX)] == EXPECTED_USAGE_PREFIX
        assert "Try 'python -m venvstacks publish --help' for help." in result.stderr
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        mocked_stack_spec.define_build_environment.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert isinstance(result.exception, SystemExit), report_traceback(
            result.exception
        )
        assert result.exit_code == 2
        assert not result.stdout

    # Specific CLI option handling test cases for the "publish" subcommand
    ExportFlagCase = tuple[tuple[str, ...], dict[str, bool], dict[str, bool]]
    _EXPORT_OPTIONS = (
        # Define how the various flags in the CLI lock subcommand map to API method options
        # `--include` and its related options are tested separately
        (
            (),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False),  # export_environments
        ),
        (
            ("--force",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=True),  # export_environments
        ),
        (
            ("--dry-run",),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(dry_run=True),  # export_environments
        ),
        (
            (
                "--no-force",
                "--no-dry-run",
            ),
            dict(lock=False, build=False, publish=True),  # select_operations
            dict(force=False),  # export_environments
        ),
    )

    @pytest.mark.parametrize("cli_test_case", _EXPORT_OPTIONS, ids=_cli_args_case_id)
    def test_mock_export_op_selection(
        self, mocked_runner: MockedRunner, cli_test_case: ExportFlagCase
    ) -> None:
        cli_flags, expected_select_args, expected_publish_args = cli_test_case
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["local-export", *cli_flags, spec_path_to_mock])
        # Always loads the stack spec and creates the build environment
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        expected_build_dir = "_build"
        expected_output_dir = "_export"
        expected_index_config = PackageIndexConfig.disabled()
        mocked_stack_spec.load.assert_called_once_with(
            spec_path_to_mock, expected_index_config
        )
        mocked_runner.assert_build_config(expected_build_dir)
        # Defaults to selecting operations rather than stacks
        mocked_build_env = mocked_runner.mocked_build_env
        mocked_build_env.select_operations.assert_called_once_with(
            **expected_select_args
        )
        mocked_build_env.select_layers.assert_not_called()
        # The publish subcommand assumes the environments are already created
        mocked_build_env.create_environments.assert_not_called()
        # The publish subcommand always attempts to publish the artifacts
        mocked_build_env.export_environments.assert_called_once_with(
            expected_output_dir, **expected_publish_args
        )
        # Check operation result last to ensure test results are as informative as possible
        assert result.exception is None, report_traceback(result.exception)
        assert result.exit_code == 0

    @staticmethod
    def get_invalid_export_options() -> Generator[str, None, None]:
        # List of flags to check was defined when 'local-export' was derived from 'publish'
        invalid_flag_names = ("lock", "build", "publish", "clean", "tag-outputs")
        for name in invalid_flag_names:
            yield f"--{name}"
            yield f"--no-{name}"

    @pytest.mark.parametrize("invalid_flag", list(get_invalid_export_options()))
    def test_mock_export_usage_error(
        self, mocked_runner: MockedRunner, invalid_flag: str
    ) -> None:
        spec_path_to_mock = "/no/such/path/spec"
        result = mocked_runner.invoke(["local-export", invalid_flag, spec_path_to_mock])
        # Should complain about the invalid flag
        assert result.stderr[: len(EXPECTED_USAGE_PREFIX)] == EXPECTED_USAGE_PREFIX
        assert (
            "Try 'python -m venvstacks local-export --help' for help." in result.stderr
        )
        # No stack spec should be created
        mocked_stack_spec = mocked_runner.mocked_stack_spec
        mocked_stack_spec.assert_not_called()
        mocked_stack_spec.load.assert_not_called()
        mocked_stack_spec.define_build_environment.assert_not_called()
        # Check operation result last to ensure test results are as informative as possible
        assert isinstance(result.exception, SystemExit), report_traceback(
            result.exception
        )
        assert result.exit_code == 2
        assert not result.stdout
