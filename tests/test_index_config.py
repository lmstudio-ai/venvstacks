"""Test for package index access configuration"""

import os

from pathlib import Path

import pytest

from venvstacks.stacks import PackageIndexConfig


class TestDefaultOptions:
    TEST_CONFIG = PackageIndexConfig()

    def test_uv_pip_compile(self) -> None:
        # Nominal config is always used when locking
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == ["--only-binary", ":all:"]

    def test_pip_install(self) -> None:
        # Nominal config can be overridden for package installation commands
        allow_source_config: list[str] = []
        binary_only_config = ["--only-binary", ":all:"]
        assert self.TEST_CONFIG._get_pip_install_args(None) == binary_only_config
        assert self.TEST_CONFIG._get_pip_install_args(False) == allow_source_config
        assert self.TEST_CONFIG._get_pip_install_args(True) == binary_only_config

    def test_pip_sync(self) -> None:
        # Final sync to remove source build dependencies is always binary-only
        assert self.TEST_CONFIG._get_pip_sync_args() == [
            "--pip-args",
            "--only-binary :all:",
        ]


class TestConfiguredOptions:
    TEST_CONFIG = PackageIndexConfig(
        query_default_index=False,
        allow_source_builds=True,
        local_wheel_dirs=["/some_dir"],
    )
    WHEEL_DIR = f"{os.sep}some_dir"

    def test_uv_pip_compile(self) -> None:
        # Nominal config is always used when locking
        assert self.TEST_CONFIG._get_uv_pip_compile_args() == [
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]

    def test_pip_install(self) -> None:
        # Nominal config can be overridden for package installation commands
        allow_source_config: list[str] = [
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
        ]
        binary_only_config = [
            "--no-index",
            "--only-binary",
            ":all:",
            "--find-links",
            self.WHEEL_DIR,
        ]
        assert self.TEST_CONFIG._get_pip_install_args(None) == allow_source_config
        assert self.TEST_CONFIG._get_pip_install_args(False) == allow_source_config
        assert self.TEST_CONFIG._get_pip_install_args(True) == binary_only_config

    def test_pip_sync(self) -> None:
        # Final sync to remove source build dependencies is always binary-only
        assert self.TEST_CONFIG._get_pip_sync_args() == [
            "--no-index",
            "--find-links",
            self.WHEEL_DIR,
            "--pip-args",
            "--only-binary :all:",
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
