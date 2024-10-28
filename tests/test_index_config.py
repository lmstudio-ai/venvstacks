"""Test for package index access configuration"""

import os

from pathlib import Path

import pytest

from venvstacks.stacks import PackageIndexConfig


class TestDefaultOptions:
    TEST_CONFIG = PackageIndexConfig()

    def test_uv_pip_compile(self) -> None:
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == []

    def test_pip_install(self) -> None:
        assert self.TEST_CONFIG._get_pip_install_args() == []


class TestConfiguredOptions:
    TEST_CONFIG = PackageIndexConfig(
        query_default_index=False,
        local_wheel_dirs=["/some_dir"],
    )
    WHEEL_DIR = f"{os.sep}some_dir"

    def test_uv_pip_compile(self) -> None:
        # There are currently no locking specific args
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == [
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]

    def test_pip_install(self) -> None:
        # There are currently no installation specific args
        assert self.TEST_CONFIG._get_pip_install_args() == [
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]


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
