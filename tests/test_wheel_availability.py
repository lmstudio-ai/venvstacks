"""Unit tests for _ensure_wheel_availability and _platform_tags_from_wheels functions."""

from venvstacks.stacks import (
    _ensure_wheel_availability,
    _platform_tags_from_wheels,
    TargetPlatform,
)


# Test fixtures and constants

LINUX_GLIBC_2_17 = ("manylinux", 2, 17)
LINUX_GLIBC_2_28 = ("manylinux", 2, 28)
LINUX_GLIBC_2_35 = ("manylinux", 2, 35)

MACOS_10_14 = (10, 14)
MACOS_12_0 = (12, 0)
MACOS_13_0 = (13, 0)
MACOS_14_0 = (14, 0)


# ============================================================================
# Helper Function Tests: _platform_tags_from_wheels
# ============================================================================


class TestPlatformTagsFromWheels:
    """Tests for _platform_tags_from_wheels helper function."""

    def test_single_wheel_single_tag(self) -> None:
        """Single wheel with one platform tag returns that tag."""
        wheels = ["package-1.0-py3-none-any.whl"]
        result = _platform_tags_from_wheels(wheels)
        assert result == {"any"}

    def test_single_wheel_multiple_tags(self) -> None:
        """Single wheel with multiple platform tags returns all tags."""
        wheels = [
            "scipy-1.16.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl"
        ]
        result = _platform_tags_from_wheels(wheels)
        assert result == {"manylinux2014_x86_64", "manylinux_2_17_x86_64"}

    def test_multiple_wheels_union_of_tags(self) -> None:
        """Multiple wheels returns union of all platform tags."""
        wheels = [
            "package-1.0-cp311-cp311-win_amd64.whl",
            "package-1.0-cp311-cp311-macosx_10_14_x86_64.whl",
        ]
        result = _platform_tags_from_wheels(wheels)
        assert result == {"win_amd64", "macosx_10_14_x86_64"}

    def test_empty_wheel_list(self) -> None:
        """Empty wheel list returns empty set."""
        result = _platform_tags_from_wheels([])
        assert result == set()


# ============================================================================
# Basic Functionality Tests
# ============================================================================


class TestBasicFunctionality:
    """Tests for basic functionality and edge cases."""

    def test_all_platforms_covered_returns_empty(self) -> None:
        """When all target platforms have matching wheels, returns empty set."""
        target_platforms = [TargetPlatform.LINUX, TargetPlatform.WINDOWS]
        wheels = [
            "package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            "package-1.0-cp311-cp311-win_amd64.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_some_platforms_missing_returns_those_platforms(self) -> None:
        """When some platforms lack wheels, returns the missing platforms."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.WINDOWS,
            TargetPlatform.MACOS_INTEL,
        ]
        wheels = [
            "package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            "package-1.0-cp311-cp311-win_amd64.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.MACOS_INTEL}

    def test_empty_target_platforms_returns_empty(self) -> None:
        """Empty target platforms list returns empty set."""
        wheels = ["package-1.0-cp311-cp311-win_amd64.whl"]
        result = _ensure_wheel_availability([], wheels, MACOS_13_0, LINUX_GLIBC_2_28)
        assert result == set()

    def test_empty_wheels_returns_all_platforms(self) -> None:
        """Empty wheels list returns all target platforms as missing."""
        target_platforms = [TargetPlatform.LINUX, TargetPlatform.WINDOWS]
        result = _ensure_wheel_availability(
            target_platforms, [], MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.LINUX, TargetPlatform.WINDOWS}

    def test_both_empty_returns_empty(self) -> None:
        """Both empty inputs returns empty set."""
        result = _ensure_wheel_availability([], [], MACOS_13_0, LINUX_GLIBC_2_28)
        assert result == set()

    def test_universal_any_wheel_covers_all_platforms(self) -> None:
        """Pure Python wheel with 'any' platform covers all target platforms."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.WINDOWS,
            TargetPlatform.MACOS_INTEL,
            TargetPlatform.MACOS_APPLE,
        ]
        wheels = ["package-1.0-py3-none-any.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()


# ============================================================================
# Linux Platform Tests
# ============================================================================


class TestLinuxPlatformCompatibility:
    """Tests for Linux platform wheel compatibility checking."""

    def test_exact_glibc_version_match(self) -> None:
        """Wheel with exact glibc version match is compatible."""
        target_platforms = [TargetPlatform.LINUX]
        wheels = ["package-1.0-cp311-cp311-manylinux_2_28_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_lower_glibc_version_compatible(self) -> None:
        """Wheel with lower glibc version is compatible with higher target."""
        target_platforms = [TargetPlatform.LINUX]
        wheels = ["package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_higher_glibc_version_incompatible(self) -> None:
        """Wheel with higher glibc version is incompatible with lower target."""
        target_platforms = [TargetPlatform.LINUX]
        wheels = ["package-1.0-cp311-cp311-manylinux_2_35_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.LINUX}

    def test_manylinux2014_translation(self) -> None:
        """manylinux2014 is translated to manylinux_2_17 and compatible."""
        target_platforms = [TargetPlatform.LINUX]
        wheels = ["package-1.0-cp311-cp311-manylinux2014_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_x86_64_vs_aarch64_separation(self) -> None:
        """x86_64 and aarch64 wheels are not interchangeable."""
        target_platforms = [TargetPlatform.LINUX_AARCH64]
        wheels = ["package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.LINUX_AARCH64}

    def test_multiple_linux_wheels_different_versions(self) -> None:
        """Multiple Linux wheels with different versions finds compatible one."""
        target_platforms = [TargetPlatform.LINUX]
        wheels = [
            "package-1.0-cp311-cp311-manylinux_2_35_x86_64.whl",  # Too new
            "package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl",  # Compatible
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_both_linux_architectures(self) -> None:
        """Both Linux architectures can be satisfied with appropriate wheels."""
        target_platforms = [TargetPlatform.LINUX, TargetPlatform.LINUX_AARCH64]
        wheels = [
            "package-1.0-cp311-cp311-manylinux_2_17_x86_64.whl",
            "package-1.0-cp311-cp311-manylinux_2_17_aarch64.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()


# ============================================================================
# macOS Platform Tests
# ============================================================================


class TestMacOSPlatformCompatibility:
    """Tests for macOS platform wheel compatibility checking."""

    def test_exact_macos_version_match(self) -> None:
        """Wheel with exact macOS version match is compatible."""
        target_platforms = [TargetPlatform.MACOS_INTEL]
        wheels = ["package-1.0-cp311-cp311-macosx_13_0_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_lower_macos_version_compatible(self) -> None:
        """Wheel with lower macOS version is compatible with higher target."""
        target_platforms = [TargetPlatform.MACOS_INTEL]
        wheels = ["package-1.0-cp311-cp311-macosx_10_14_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_higher_macos_version_incompatible(self) -> None:
        """Wheel with higher macOS version is incompatible with lower target."""
        target_platforms = [TargetPlatform.MACOS_INTEL]
        wheels = ["package-1.0-cp311-cp311-macosx_14_0_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.MACOS_INTEL}

    def test_universal2_covers_both_macos_architectures(self) -> None:
        """universal2 wheel is compatible with both Intel and Apple Silicon."""
        target_platforms = [TargetPlatform.MACOS_INTEL, TargetPlatform.MACOS_APPLE]
        wheels = ["package-1.0-cp311-cp311-macosx_12_0_universal2.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_separate_intel_and_apple_silicon_wheels(self) -> None:
        """Separate wheels for Intel and Apple Silicon both work."""
        target_platforms = [TargetPlatform.MACOS_INTEL, TargetPlatform.MACOS_APPLE]
        wheels = [
            "package-1.0-cp311-cp311-macosx_10_14_x86_64.whl",
            "package-1.0-cp311-cp311-macosx_12_0_arm64.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_intel_wheel_does_not_cover_apple_silicon(self) -> None:
        """Intel-specific wheel does not cover Apple Silicon platform."""
        target_platforms = [TargetPlatform.MACOS_APPLE]
        wheels = ["package-1.0-cp311-cp311-macosx_10_14_x86_64.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.MACOS_APPLE}


# ============================================================================
# Real-World Integration Tests
# ============================================================================


class TestRealWorldScenarios:
    """Tests using realistic wheel names from actual packages."""

    def test_scipy_multiplatform_all_covered(self) -> None:
        """scipy-like package with wheels for all major platforms."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.LINUX_AARCH64,
            TargetPlatform.MACOS_INTEL,
            TargetPlatform.MACOS_APPLE,
            TargetPlatform.WINDOWS,
        ]
        wheels = [
            "scipy-1.16.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
            "scipy-1.16.1-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.whl",
            "scipy-1.16.1-cp311-cp311-macosx_10_14_x86_64.whl",
            "scipy-1.16.1-cp311-cp311-macosx_12_0_arm64.whl",
            "scipy-1.16.1-cp311-cp311-win_amd64.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()

    def test_numpy_multiplatform_partially_covered(self) -> None:
        """numpy-like package missing some platform wheels."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.LINUX_AARCH64,
            TargetPlatform.WINDOWS,
            TargetPlatform.WINDOWS_ARM64,
        ]
        wheels = [
            "numpy-2.3.2-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
            "numpy-2.3.2-cp312-cp312-win_amd64.whl",
            # Missing: Linux aarch64 and Windows ARM64
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.LINUX_AARCH64, TargetPlatform.WINDOWS_ARM64}

    def test_platform_specific_package_windows_only(self) -> None:
        """Platform-specific package (e.g., Windows-only) correctly reports missing."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.WINDOWS,
        ]
        wheels = [
            "pywin32-306-cp311-cp311-win_amd64.whl",
            "pywin32-306-cp311-cp311-win32.whl",
        ]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == {TargetPlatform.LINUX}

    def test_pure_python_package_covers_all(self) -> None:
        """Pure Python package with 'any' wheel covers all platforms."""
        target_platforms = [
            TargetPlatform.LINUX,
            TargetPlatform.LINUX_AARCH64,
            TargetPlatform.MACOS_INTEL,
            TargetPlatform.MACOS_APPLE,
            TargetPlatform.WINDOWS,
            TargetPlatform.WINDOWS_ARM64,
        ]
        wheels = ["requests-2.31.0-py3-none-any.whl"]
        result = _ensure_wheel_availability(
            target_platforms, wheels, MACOS_13_0, LINUX_GLIBC_2_28
        )
        assert result == set()
