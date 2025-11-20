"""Test example stacks in repo have valid layer locks."""

from dataclasses import dataclass, replace as dc_replace
from pathlib import Path

from venvstacks.stacks import (
    LayerEnvBase,
    LayerBaseName,
    StackSpec,
    TargetPlatform,
    TargetPlatforms,
    _iter_pylock_packages_from_file,
)

from support import DeploymentTestCase

# These lock files are currently assumed to be too slow to generate in CI
# See https://github.com/lmstudio-ai/venvstacks/issues/273 for details

_TEST_DIR_PATH = Path(__file__).parent
EXAMPLE_STACKS_PATH = _TEST_DIR_PATH.parent / "examples"


@dataclass(frozen=True)
class Package:
    name: str
    marker: str = ""
    version: str | None = None
    shared: bool = False


@dataclass
class LayerDetails:
    expected_platforms: set[TargetPlatform]
    expected_packages: set[Package] | None = None
    expected_versions: dict[str, set[Package]] | None = None


ALL_PLATFORMS = set(TargetPlatforms.get_all_target_platforms())

_LINUX_MARKER = "platform_machine == 'x86_64' and sys_platform == 'linux'"
_MACOS_MARKER = "platform_machine == 'arm64' and sys_platform == 'darwin'"

EXPECTED_MLX_FRAMEWORK_CUDA = LayerDetails(
    expected_packages={
        Package("mlx"),
        Package("mlx-cuda", _LINUX_MARKER),
        Package("mlx-metal", _MACOS_MARKER),
        Package("nvidia-cublas-cu12", _LINUX_MARKER),
        Package("nvidia-cuda-nvrtc-cu12", _LINUX_MARKER),
        Package("nvidia-cudnn-cu12", _LINUX_MARKER),
        Package("nvidia-nccl-cu12", _LINUX_MARKER),
    },
    expected_platforms={
        TargetPlatform.LINUX,
        TargetPlatform.MACOS_APPLE,
    },
)

EXPECTED_MLX_APP_CUDA_LINUX = LayerDetails(
    expected_packages={
        Package("mlx", shared=True),
        Package("mlx-cuda", shared=True),
        Package("nvidia-cublas-cu12", shared=True),
        Package("nvidia-cuda-nvrtc-cu12", shared=True),
        Package("nvidia-cudnn-cu12", shared=True),
        Package("nvidia-nccl-cu12", shared=True),
    },
    expected_platforms={
        TargetPlatform.LINUX,
    },
)

EXPECTED_MLX_APP_CUDA_MACOS = LayerDetails(
    expected_packages={
        Package("mlx", shared=True),
        Package("mlx-metal", shared=True),
    },
    expected_platforms={
        TargetPlatform.MACOS_APPLE,
    },
)

EXPECTED_TORCH_APP_CPU = LayerDetails(
    expected_platforms=ALL_PLATFORMS - {TargetPlatform.MACOS_INTEL},
    expected_versions={
        "torch": {
            Package("torch", "sys_platform == 'darwin'", "2.8.0", shared=True),
            Package("torch", "sys_platform != 'darwin'", "2.8.0+cpu", shared=True),
        },
    },
)

EXPECTED_TORCH_APP_CUDA = LayerDetails(
    expected_platforms={
        # Public CUDA wheels are only available for a subset of platforms
        TargetPlatform.LINUX,
        TargetPlatform.WINDOWS,
    },
    expected_versions={
        "torch": {
            Package("torch", version="2.8.0+cu128", shared=True),
        },
    },
)


class TestExampleStacks(DeploymentTestCase):
    def test_example_stacks_are_locked(self) -> None:
        all_example_dir_paths = list(EXAMPLE_STACKS_PATH.iterdir())
        expected_examples = len(all_example_dir_paths)
        examples_passed = 0
        for example_dir_path in all_example_dir_paths:
            with self.subTest(example=example_dir_path.name):
                stack_path = example_dir_path / "venvstacks.toml"
                stack_spec = StackSpec.load(stack_path)
                build_env = stack_spec.define_build_environment()
                self.check_layer_locks(build_env.all_environments())
                examples_passed += 1
        self.assertEqual(
            examples_passed, expected_examples, "Fail due to failed subtest(s)"
        )

    def check_layer_details(self, env: LayerEnvBase, details: LayerDetails) -> None:
        self.assertEqual(details.expected_platforms, set(env.env_spec.platforms))
        expected_packages = set(details.expected_packages or ())
        expected_versions = dict(details.expected_versions or {})
        for pkg_name, expected_pkg_versions in expected_versions.items():
            expected_versions[pkg_name] = set(expected_pkg_versions)
        pylock_path = env.requirements_path
        for locked_pkg in _iter_pylock_packages_from_file(pylock_path):
            pkg = Package(
                locked_pkg.name,
                locked_pkg.marker_text,
                shared=locked_pkg.is_shared,
            )
            if expected_packages:
                self.assertIn(pkg, expected_packages)
                expected_packages.remove(pkg)
            if expected_versions:
                pkg_name = pkg.name
                if pkg_name in expected_versions:
                    expected_pkg_versions = expected_versions[pkg_name]
                    versioned_pkg = dc_replace(pkg, version=str(locked_pkg.version))
                    self.assertIn(versioned_pkg, expected_pkg_versions)
                    expected_pkg_versions.remove(versioned_pkg)
        if expected_packages:
            self.fail(f"Expected packages not found: {expected_packages!r}")
        if expected_versions:
            expected_version_status: dict[str, set[Package]] = {
                name: set() for name in expected_versions
            }
            self.assertEqual(expected_versions, expected_version_status)

    def test_example_details_mlx(self) -> None:
        # The MLX example covers details of filtering packages by platform
        stack_path = EXAMPLE_STACKS_PATH / "mlx/venvstacks.toml"
        stack_spec = StackSpec.load(stack_path)
        build_env = stack_spec.define_build_environment()
        fw_cuda = build_env.frameworks[LayerBaseName("mlx-cuda")]
        app_linux = build_env.applications[LayerBaseName("mlx-cuda-linux")]
        app_macos = build_env.applications[LayerBaseName("mlx-cuda-macos")]
        envs_to_check = (
            (fw_cuda, EXPECTED_MLX_FRAMEWORK_CUDA),
            (app_linux, EXPECTED_MLX_APP_CUDA_LINUX),
            (app_macos, EXPECTED_MLX_APP_CUDA_MACOS),
        )
        env_checks_passed = 0
        for env, details in envs_to_check:
            with self.subTest(env=env.env_name):
                self.check_layer_details(env, details)
                env_checks_passed += 1
        self.assertEqual(
            env_checks_passed, len(envs_to_check), "Fail due to failed subtest(s)"
        )

    def test_example_details_torch(self) -> None:
        # The torch example covers details of package index selection
        stack_path = EXAMPLE_STACKS_PATH / "pytorch/venvstacks.toml"
        stack_spec = StackSpec.load(stack_path)
        build_env = stack_spec.define_build_environment()
        app_cpu = build_env.applications[LayerBaseName("cpu")]
        app_cuda = build_env.applications[LayerBaseName("cu128")]
        app_either = build_env.applications[LayerBaseName("cu128-or-cpu")]
        envs_to_check = (
            (app_cpu, EXPECTED_TORCH_APP_CPU),
            (app_cuda, EXPECTED_TORCH_APP_CUDA),
            (app_either, EXPECTED_TORCH_APP_CUDA),  # Locks like the CUDA layer
        )
        env_checks_passed = 0
        for env, details in envs_to_check:
            with self.subTest(env=env.env_name):
                self.check_layer_details(env, details)
                env_checks_passed += 1
        self.assertEqual(
            env_checks_passed, len(envs_to_check), "Fail due to failed subtest(s)"
        )
