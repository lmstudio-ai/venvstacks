"""Test for package index access configuration."""

import os

from pathlib import Path

import pytest
import tomlkit

from venvstacks.stacks import PackageIndexConfig


class _CommonTestDetails:
    BUILD_PATH = Path("/build_dir")
    CONFIG_FILE = os.fspath(BUILD_PATH / "uv.toml")


class TestDefaultOptions(_CommonTestDetails):
    TEST_CONFIG = PackageIndexConfig()

    def test_uv_lock(self) -> None:
        assert self.TEST_CONFIG._get_uv_lock_args(self.BUILD_PATH) == [
            "--no-build",
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_export(self) -> None:
        assert self.TEST_CONFIG._get_uv_export_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_pip_install(self) -> None:
        assert self.TEST_CONFIG._get_uv_pip_install_args(self.BUILD_PATH) == [
            "--only-binary",
            ":all:",
            "--config-file",
            self.CONFIG_FILE,
        ]


class TestConfiguredOptions(_CommonTestDetails):
    TEST_CONFIG = PackageIndexConfig(
        query_default_index=False,
        local_wheel_dirs=["/some_dir"],
    )
    WHEEL_DIR = f"{os.sep}some_dir"

    def test_uv_lock(self) -> None:
        # There are currently no locking specific args
        assert self.TEST_CONFIG._get_uv_lock_args(self.BUILD_PATH) == [
            "--no-build",
            "--config-file",
            self.CONFIG_FILE,
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]

    def test_uv_export(self) -> None:
        assert self.TEST_CONFIG._get_uv_export_args(self.BUILD_PATH) == [
            "--config-file",
            self.CONFIG_FILE,
        ]

    def test_uv_pip_install(self) -> None:
        # There are currently no installation specific args
        assert self.TEST_CONFIG._get_uv_pip_install_args(self.BUILD_PATH) == [
            "--only-binary",
            ":all:",
            "--config-file",
            self.CONFIG_FILE,
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]


_EXAMPLE_UV_CONFIG = """\
# Custom uv config
[[index]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[sources]
torch = { index = "pytorch" }
"""

_EXAMPLE_UV_CONFIG_TABLE = """\
[[tool.uv.index]]
name = "pytorch"
url = "https://download.pytorch.org/whl/cu128"
explicit = true

[tool.uv.sources]
torch = { index = "pytorch" }
"""


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
        self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        assert "# No baseline uv tool config\n" == output_config_path.read_text(
            encoding="utf-8"
        )

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
        self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        # Comments and formatting should be preserved when using an adjacent config file
        assert _EXAMPLE_UV_CONFIG == output_config_path.read_text(encoding="utf-8")

    def test_custom_tool_config_from_inline_table(self, temp_dir_path: Path) -> None:
        # Test tool config with baseline config supplied via the stack definition table
        # Also ensure the adjacent file is ignored in this case
        spec_path = temp_dir_path / "venvstacks.toml"
        spec_path.write_text(_EXAMPLE_UV_CONFIG_TABLE, encoding="utf-8")
        ignored_config_path = temp_dir_path / "venvstacks.uv.toml"
        ignored_config_path.write_text("# This file is ignored\n", encoding="utf-8")
        output_dir_path = temp_dir_path / "_output"
        output_dir_path.mkdir()
        self._write_test_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        # Extracting an inline table loses comments and specific formatting details
        expected_config = tomlkit.dumps(tomlkit.parse(_EXAMPLE_UV_CONFIG).unwrap())
        assert expected_config == output_config_path.read_text(encoding="utf-8")


# Miscellaneous test cases
def test_wheel_dir_not_in_sequence() -> None:
    with pytest.raises(TypeError):
        PackageIndexConfig(local_wheel_dirs="/some_dir")


def test_lexical_path_resolution() -> None:
    paths_to_resolve = [
        "/some/path",
        "/some/absolute/../path",
        "some/path",
        "some/relative/../path",
        "~/some/path",
        "~/some/user/../path",
    ]
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
