"""Test for package index access configuration."""

import os

from pathlib import Path

import pytest

from venvstacks.stacks import PackageIndexConfig


class TestDefaultOptions:
    TEST_CONFIG = PackageIndexConfig()

    def test_uv_pip_compile(self) -> None:
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == [
            "--only-binary",
            ":all:",
        ]

    def test_uv_pip_install(self) -> None:
        assert self.TEST_CONFIG._get_uv_pip_install_args() == [
            "--only-binary",
            ":all:",
        ]


class TestConfiguredOptions:
    TEST_CONFIG = PackageIndexConfig(
        query_default_index=False,
        local_wheel_dirs=["/some_dir"],
    )
    WHEEL_DIR = f"{os.sep}some_dir"

    def test_uv_pip_compile(self) -> None:
        # There are currently no locking specific args
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == [
            "--only-binary",
            ":all:",
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]

    def test_uv_pip_install(self) -> None:
        # There are currently no installation specific args
        assert self.TEST_CONFIG._get_uv_pip_install_args() == [
            "--only-binary",
            ":all:",
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]


class TestBaselineToolConfig:
    TEST_CONFIG = PackageIndexConfig()

    def test_default_tool_config(self, temp_dir_path: Path) -> None:
        # Test tool config with no user supplied baseline config
        spec_path = temp_dir_path / "venvstacks.toml"
        output_dir_path = temp_dir_path
        self.TEST_CONFIG._write_tool_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        assert "# No baseline uv tool config\n" == output_config_path.read_text(
            encoding="utf-8"
        )

    def test_custom_tool_config(self, temp_dir_path: Path) -> None:
        # Test tool config with no user supplied baseline config
        spec_path = temp_dir_path / "venvstacks.toml"
        baseline_config_path = temp_dir_path / "uv.toml"
        baseline_config_path.write_text("# Custom uv config\n", encoding="utf-8")
        output_dir_path = temp_dir_path / "_output"
        output_dir_path.mkdir()
        self.TEST_CONFIG._write_tool_config_files(spec_path, output_dir_path)
        output_config_path = output_dir_path / "uv.toml"
        assert output_config_path.exists()
        assert "# Custom uv config\n" == output_config_path.read_text(
            encoding="utf-8"
        )


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
    config.resolve_lexical_paths("/base_path")
    assert config.local_wheel_paths == expected_paths
