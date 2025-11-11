"""Test environment marker calculations."""

import pytest

from venvstacks.stacks import RuntimeSpec, TargetPlatform, TargetPlatforms


# Check inference of platform_python_implementation from pbs-installer names
def test_runtime_cpython() -> None:
    spec = RuntimeSpec.from_dict(
        {
            "name": "cpython-3.13",
            "python_implementation": "cpython@3.13.7",
            "requirements": [],
        }
    )
    assert spec.py_implementation == "CPython"
    assert spec.py_version == "3.13.7"


def test_runtime_pypy() -> None:
    spec = RuntimeSpec.from_dict(
        {
            "name": "pypy-3.11",
            "python_implementation": "pypy@3.11.13",
            "requirements": [],
        }
    )
    assert spec.py_implementation == "PyPy"
    assert spec.py_version == "3.11.13"


# Check inference of environment markers from platform and implementation
_EXPECTED_IMPLEMENTATION_MARKERS = {
    "CPython": {
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
    },
    "PyPy": {
        "implementation_name": "pypy",
        "platform_python_implementation": "PyPy",
    },
}
_EXPECTED_PLATFORM_MARKERS = {
    TargetPlatforms.LINUX: {
        "os_name": "posix",
        "sys_platform": "linux",
        "platform_machine": "x86_64",
        "platform_system": "Linux",
    },
    TargetPlatforms.LINUX_AARCH64: {
        "os_name": "posix",
        "sys_platform": "linux",
        "platform_machine": "aarch64",
        "platform_system": "Linux",
    },
    TargetPlatforms.WINDOWS: {
        "os_name": "nt",
        "sys_platform": "win32",
        "platform_machine": "AMD64",
        "platform_system": "Windows",
    },
    TargetPlatforms.WINDOWS_ARM64: {
        "os_name": "nt",
        "sys_platform": "win32",
        "platform_machine": "arm64",
        "platform_system": "Windows",
    },
    TargetPlatforms.MACOS_APPLE: {
        "os_name": "posix",
        "sys_platform": "darwin",
        "platform_machine": "arm64",
        "platform_system": "Darwin",
    },
    TargetPlatforms.MACOS_INTEL: {
        "os_name": "posix",
        "sys_platform": "darwin",
        "platform_machine": "x86_64",
        "platform_system": "Darwin",
    },
}


@pytest.mark.parametrize("platform", TargetPlatforms.get_all_target_platforms())
@pytest.mark.parametrize("impl_name", _EXPECTED_IMPLEMENTATION_MARKERS.keys())
def test_marker_environments(platform: TargetPlatform, impl_name: str) -> None:
    # Ensure pre-release markers in the version are retained
    full_version = "3.14.0b1"
    expected_markers = {
        "python_version": "3.14",
        "python_full_version": "3.14.0b1",
        **_EXPECTED_PLATFORM_MARKERS[platform],
        **_EXPECTED_IMPLEMENTATION_MARKERS[impl_name],
    }
    assert platform._get_marker_environment(full_version, impl_name) == expected_markers
