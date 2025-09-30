"""Test for package index access configuration."""

import os

from pathlib import Path

import pytest

from venvstacks.stacks import PackageIndexConfig, _IndexDetails

# Use the sample project as an example project with no custom index config
_THIS_PATH = Path(__file__)
SAMPLE_PROJECT_PATH = _THIS_PATH.parent / "sample_project"
SAMPLE_PROJECT_STACK_SPEC_PATH = SAMPLE_PROJECT_PATH / "venvstacks.toml"


class _CommonTestDetails:
    BUILD_PATH = Path("/build_dir")
    CONFIG_FILE = os.fspath(BUILD_PATH / "uv.toml")


class TestDefaultOptions(_CommonTestDetails):
    TEST_CONFIG = PackageIndexConfig()

    def test_uv_lock(self) -> None:
        # There are currently no locking specific args
        assert self.TEST_CONFIG._get_uv_lock_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_export(self) -> None:
        # There are currently no export specific args
        assert self.TEST_CONFIG._get_uv_export_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_pip_install(self) -> None:
        # There are currently no installation specific args
        assert self.TEST_CONFIG._get_uv_pip_install_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_local_wheel_indexes(self) -> None:
        assert list(self.TEST_CONFIG._define_local_wheel_locations()) == []

    def test_common_config(self) -> None:
        index_config = self.TEST_CONFIG.copy()
        index_config._load_common_tool_config(SAMPLE_PROJECT_STACK_SPEC_PATH)
        common_config_uv = index_config._common_config_uv
        assert common_config_uv is not None
        assert common_config_uv["no-build"] is True
        assert "no-index" not in common_config_uv
        assert "find-links" not in common_config_uv
        assert "index" not in common_config_uv


class TestConfiguredOptions(_CommonTestDetails):
    TEST_CONFIG = PackageIndexConfig(
        query_default_index=False,
        local_wheel_dirs=("/some_dir",),
    )
    INITIAL_WHEEL_DIR = f"{os.sep}some_dir"
    RESOLVED_WHEEL_DIR = f"{SAMPLE_PROJECT_STACK_SPEC_PATH.anchor}some_dir"

    def test_uv_lock(self) -> None:
        # There are currently no locking specific args
        assert self.TEST_CONFIG._get_uv_lock_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_export(self) -> None:
        # There are currently no export specific args
        assert self.TEST_CONFIG._get_uv_export_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_pip_install(self) -> None:
        # There are currently no installation specific args
        assert self.TEST_CONFIG._get_uv_pip_install_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_local_wheel_indexes(self) -> None:
        index_config = self.TEST_CONFIG.copy()
        assert list(index_config._define_local_wheel_locations()) == [
            self.INITIAL_WHEEL_DIR
        ]
        index_config._resolve_lexical_paths(SAMPLE_PROJECT_STACK_SPEC_PATH.parent)
        assert list(index_config._define_local_wheel_locations()) == [
            self.RESOLVED_WHEEL_DIR
        ]

    def test_common_config(self) -> None:
        index_config = self.TEST_CONFIG.copy()
        index_config._load_common_tool_config(SAMPLE_PROJECT_STACK_SPEC_PATH)
        common_config_uv = index_config._common_config_uv
        assert common_config_uv is not None
        assert common_config_uv["no-build"] is True
        assert common_config_uv["no-index"] is True
        assert common_config_uv["find-links"] == [self.RESOLVED_WHEEL_DIR]
        assert "index" not in common_config_uv


_EXAMPLE_UV_CONFIG = """\
# Custom uv config
no-build = true

[[index]]
# explicit -> only used when specified in priority_indexes
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128/"
explicit = true

[[index]]
# implicit -> used by default for all layers
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu/"

[[index]]
# anonymous (and implicit) -> used by default for all layers, priority cannot be increased
url = "https://pypi.org/simple/"
"""

_EXAMPLE_UV_CONFIG_TABLE = """\
[tool.uv]
no-build = true

[[tool.uv.index]]
# explicit -> only used when specified in priority_indexes
name = "pytorch-cu128"
url = "https://download.pytorch.org/whl/cu128/"
explicit = true

[[tool.uv.index]]
# implicit -> used by default for all layers
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu/"

[[tool.uv.index]]
# anonymous (and implicit) -> used by default for all layers, priority cannot be increased
url = "https://pypi.org/simple/"
"""

_EXPECTED_COMMON_UV_CONFIG = """\
no-build = true
"""
_EXPECTED_NAMED_INDEX_DETAILS: dict[str, _IndexDetails] = {
    "pytorch-cu128": {
        "name": "pytorch-cu128",
        "url": "https://download.pytorch.org/whl/cu128/",
        "explicit": True,
    },
    "pytorch-cpu": {
        "name": "pytorch-cpu",
        "url": "https://download.pytorch.org/whl/cpu/",
    },
}
_EXPECTED_INDEX_DETAILS: list[_IndexDetails] = [
    _EXPECTED_NAMED_INDEX_DETAILS["pytorch-cu128"],
    _EXPECTED_NAMED_INDEX_DETAILS["pytorch-cpu"],
    {
        "url": "https://pypi.org/simple/",
    },
]


class TestBaselineToolConfig:
    TEST_CONFIG = PackageIndexConfig()

    @classmethod
    def _write_test_config_files(
        cls, spec_path: Path, output_dir_path: Path
    ) -> PackageIndexConfig:
        index_config = cls.TEST_CONFIG.copy()
        index_config._load_common_tool_config(spec_path)
        index_config._write_common_tool_config_files(output_dir_path)
        return index_config

    def test_default_tool_config(self, temp_dir_path: Path) -> None:
        # Test tool config with no user supplied baseline config
        spec_path = temp_dir_path / "venvstacks.toml"
        spec_path.touch()
        output_dir_path = temp_dir_path
        index_config = self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        output_config = output_config_path.read_text("utf-8")
        assert output_config == _EXPECTED_COMMON_UV_CONFIG
        assert index_config._indexes == []
        assert index_config._named_indexes == {}

    def test_tool_config_overwrite_error(self, temp_dir_path: Path) -> None:
        # Test attempting to use one index config with multiple spec paths fails
        spec_path = temp_dir_path / "venvstacks.toml"
        spec_path.touch()
        output_dir_path = temp_dir_path
        index_config = self._write_test_config_files(spec_path, output_dir_path)
        with pytest.raises(RuntimeError):
            # Even if the same path is given, attempting to load the config again is disallowed
            index_config._load_common_tool_config(spec_path)

    def test_custom_tool_config_from_adjacent_file(self, temp_dir_path: Path) -> None:
        # Test tool config with baseline config supplied via an adjacent config file
        spec_path = temp_dir_path / "venvstacks.toml"
        spec_path.touch()
        baseline_config_path = temp_dir_path / "venvstacks.uv.toml"
        baseline_config_path.write_text(_EXAMPLE_UV_CONFIG, encoding="utf-8")
        output_dir_path = temp_dir_path / "_output"
        output_dir_path.mkdir()
        index_config = self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        # Config file omits the index details
        output_config = output_config_path.read_text("utf-8")
        assert output_config == _EXPECTED_COMMON_UV_CONFIG
        assert index_config._indexes == _EXPECTED_INDEX_DETAILS
        assert index_config._named_indexes == _EXPECTED_NAMED_INDEX_DETAILS

    def test_custom_tool_config_from_inline_table(self, temp_dir_path: Path) -> None:
        # Test tool config with baseline config supplied via the stack definition table
        # Also ensure the adjacent file is ignored in this case
        spec_path = temp_dir_path / "venvstacks.toml"
        spec_path.write_text(_EXAMPLE_UV_CONFIG_TABLE, encoding="utf-8")
        ignored_config_path = temp_dir_path / "venvstacks.uv.toml"
        ignored_config_path.write_text("# This file is ignored\n", encoding="utf-8")
        output_dir_path = temp_dir_path / "_output"
        output_dir_path.mkdir()
        index_config = self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        # Config file omits the index details
        output_config = output_config_path.read_text("utf-8")
        assert output_config == _EXPECTED_COMMON_UV_CONFIG
        assert index_config._indexes == _EXPECTED_INDEX_DETAILS
        assert index_config._named_indexes == _EXPECTED_NAMED_INDEX_DETAILS


# Miscellaneous test cases
def test_wheel_dir_not_in_sequence() -> None:
    with pytest.raises(TypeError):
        PackageIndexConfig(local_wheel_dirs="/some_dir")  # type: ignore[arg-type]


def test_lexical_path_resolution() -> None:
    paths_to_resolve = (
        "/some/path",
        "/some/absolute/../path",
        "some/path",
        "some/relative/../path",
        "~/some/path",
        "~/some/user/../path",
    )
    expected_paths = [
        Path("/some/path").absolute(),
        Path("/some/path").absolute(),
        Path("/base_path/some/path").absolute(),
        Path("/base_path/some/path").absolute(),
        Path.home() / "some/path",
        Path.home() / "some/path",
    ]
    config = PackageIndexConfig(local_wheel_dirs=paths_to_resolve)
    config._resolve_lexical_paths("/base_path")
    assert config.local_wheel_paths == expected_paths
