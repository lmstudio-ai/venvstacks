"""Test cases for environment lock management."""

import shutil
import tempfile
import tomllib

import pytest

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, cast

from pytest_subtests import SubTests

from venvstacks.stacks import (
    BuildEnvError,
    BuildEnvironment,
    EnvironmentLock,
    LayerBaseName,
    LayerEnvBase,
    LayerVariants,
    StackSpec,
    _hash_strings,
)


@pytest.fixture
def temp_dir_path() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as dir_name:
        yield Path(dir_name)


##############################
# EnvironmentLock test cases
##############################


def test_default_state(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, (), ())
    # Declared requirements file is only written when requested
    assert env_lock.declared_requirements == ()
    assert env_lock._lock_input_path == temp_dir_path / "requirements.in"
    assert not env_lock.locked_requirements_path.exists()
    no_dependencies_hash = env_lock._lock_input_hash
    assert no_dependencies_hash is not None
    env_lock.prepare_lock_inputs()
    assert env_lock._lock_input_path.read_text() != ""
    assert env_lock._lock_input_hash == no_dependencies_hash
    # Locked requirements file must be written externally
    assert env_lock.locked_requirements_path == req_path
    assert not env_lock.locked_requirements_path.exists()
    assert env_lock._requirements_hash is None
    # Metadata file is only written when requested
    assert env_lock._lock_metadata_path == temp_dir_path / "requirements.txt.json"
    assert not env_lock._lock_metadata_path.exists()
    assert env_lock.load_valid_metadata() is None


def test_load_with_consistent_file_hashes(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, (), ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    env_lock_metadata = env_lock.load_valid_metadata()
    assert env_lock_metadata is not None
    # Loading the lock without changes gives the same metadata
    loaded_lock = EnvironmentLock(req_path, (), ())
    assert loaded_lock._lock_input_hash == env_lock._lock_input_hash
    assert loaded_lock._requirements_hash == env_lock._requirements_hash
    assert loaded_lock.load_valid_metadata() == env_lock_metadata


def test_load_with_inconsistent_input_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, (), ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with different requirements invalidates the metadata
    loaded_lock = EnvironmentLock(req_path, ("some-requirement",), ())
    assert loaded_lock._lock_input_hash != env_lock._lock_input_hash
    assert loaded_lock._requirements_hash is None
    assert loaded_lock.load_valid_metadata() is None


def test_load_with_inconsistent_output_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, (), ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with a different lock file invalidates the metadata
    env_lock.locked_requirements_path.write_text("")
    loaded_lock = EnvironmentLock(req_path, (), ())
    assert loaded_lock._lock_input_hash == env_lock._lock_input_hash
    assert loaded_lock._requirements_hash != env_lock._requirements_hash
    assert loaded_lock.load_valid_metadata() is None


def test_requirements_file_hashing(temp_dir_path: Path) -> None:
    messy_requirements = [
        "# File header comment",
        "b==2.3.4  # Trailing comment",
        "    c==3.4.5  # Leading whitespace",
        "a==1.2.3  # Entry out of order",
        "",
        "# Preceding line intentionally blank",
        "d==4.5.6",
    ]
    clean_requirements = EnvironmentLock._clean_reqs(messy_requirements)
    expected_requirements = [
        "a==1.2.3",
        "b==2.3.4",
        "c==3.4.5",
        "d==4.5.6",
    ]
    assert clean_requirements == expected_requirements
    expected_hash = _hash_strings(expected_requirements)
    assert EnvironmentLock._hash_reqs(messy_requirements) == expected_hash
    req_input_path = temp_dir_path / "requirements.in"
    req_input_path.write_text("\n".join(messy_requirements))
    req_file_hash = EnvironmentLock._hash_req_file(req_input_path)
    assert req_file_hash == expected_hash


##################################
# Layer specification test cases
##################################

EMPTY_SCRIPT_PATH = Path(__file__).parent / "minimal_project/empty.py"
EXAMPLE_STACK_SPEC = """\
[[runtimes]]
name = "cpython-to-be-modified"
python_implementation = "cpython@3.11.11"
requirements = []

[[runtimes]]
name = "cpython-same-major-version-unaffected"
python_implementation = "cpython@3.11.9"
requirements = []

[[runtimes]]
name = "cpython-other-version-unaffected"
python_implementation = "cpython@3.12.9"
requirements = []

[[frameworks]]
name = "to-be-modified"
runtime = "cpython-to-be-modified"
requirements = []

[[frameworks]]
name = "other-app-dependency"
runtime = "cpython-to-be-modified"
requirements = []

[[frameworks]]
# Must be after "other-app-dependency" to allow the declared
# dependency to be switched without reordering the list
name = "dependent"
frameworks = ["to-be-modified"]
requirements = []

[[frameworks]]
name = "unaffected"
runtime = "cpython-other-version-unaffected"
requirements = []

[[applications]]
name = "to-be-modified"
launch_module = "launch.py"
# "dependent" must be first here to allow linearisation
# when that layer also depends on "other-app-dependency"
frameworks = ["dependent", "other-app-dependency"]
requirements = []

[[applications]]
name = "runtime-only"
runtime = "cpython-to-be-modified"
launch_module = "launch2.py"
requirements = []

[[applications]]
name = "unaffected"
launch_module = "launch2.py"
frameworks = ["unaffected"]
requirements = []
"""

EXPECTED_LAYER_NAMES = (
    "cpython-to-be-modified",
    "cpython-same-major-version-unaffected",
    "cpython-other-version-unaffected",
    "framework-to-be-modified",
    "framework-other-app-dependency",
    "framework-dependent",
    "framework-unaffected",
    "app-to-be-modified",
    "app-runtime-only",
    "app-unaffected",
)


def _define_lock_testing_env(
    spec_path: Path, spec_data: dict[str, Any]
) -> BuildEnvironment:
    stack_spec = StackSpec.from_dict(spec_path, spec_data)
    return stack_spec.define_build_environment()


def _partition_envs(build_env: BuildEnvironment) -> tuple[set[str], set[str]]:
    valid_locks: set[str] = set()
    invalid_locks: set[str] = set()
    for env in build_env.all_environments():
        set_to_update = invalid_locks if env.needs_lock() else valid_locks
        set_to_update.add(env.env_name)
    return valid_locks, invalid_locks


@contextmanager
def _modified_file(file_path: Path, contents: str) -> Generator[Any, None, None]:
    backup_path = file_path.rename(file_path.with_suffix(".bak"))
    if not contents.endswith("\n"):
        contents += "\n"
    try:
        file_path.write_text(contents)
        yield
    finally:
        file_path.unlink()
        backup_path.rename(file_path)


def test_build_env_layer_locks(temp_dir_path: Path, subtests: SubTests) -> None:
    # Built as a monolithic tests with subtests for performance reasons
    # (initial setup takes ~10 seconds, subsequent checks are fractions of a second)
    launch_module_path = temp_dir_path / "launch.py"
    shutil.copyfile(EMPTY_SCRIPT_PATH, launch_module_path)
    shutil.copyfile(EMPTY_SCRIPT_PATH, temp_dir_path / "launch2.py")
    spec_path = temp_dir_path / "venvstacks.toml"
    updated_spec_path = temp_dir_path / "venvstacks_updated.toml"
    spec_data = tomllib.loads(EXAMPLE_STACK_SPEC)
    build_env_to_lock = _define_lock_testing_env(spec_path, spec_data)
    # Check for divergence between stack spec and the expected results
    # This also keeps the test from trivially passing due to bugs in the iterators
    layer_names = tuple(env.env_name for env in build_env_to_lock.all_environments())
    assert layer_names == EXPECTED_LAYER_NAMES
    # Preliminary checks that locking the stack updates the state as expected
    assert build_env_to_lock._needs_lock()
    all_layer_names = {*EXPECTED_LAYER_NAMES}
    valid_locks, invalid_locks = _partition_envs(build_env_to_lock)
    assert valid_locks == set()
    assert invalid_locks == all_layer_names
    assert all(env.needs_lock() for env in build_env_to_lock.all_environments())

    # Check lock input file determination
    layers_to_lock_names: list[str] = []
    for runtime_env in build_env_to_lock.runtimes_to_lock():
        # Runtime environments are always ready to be locked
        assert runtime_env.kind == LayerVariants.RUNTIME
        layers_to_lock_names.append(runtime_env.env_name)
        runtime_lock_inputs = runtime_env.get_lock_inputs()
        expected_runtime_lock_inputs = (
            runtime_env.requirements_path,
            runtime_env.requirements_path.with_suffix(".in"),
            cast(list[Path], []),
        )
        assert runtime_lock_inputs == expected_runtime_lock_inputs
    for unlocked_env in build_env_to_lock.environments_to_lock():
        if unlocked_env.kind == LayerVariants.RUNTIME:
            continue
        # Layered environments can only be locked after the layers they depend on
        layers_to_lock_names.append(unlocked_env.env_name)
        with pytest.raises(BuildEnvError, match="unlocked dependencies"):
            unlocked_env.get_lock_inputs()
    # Ensure this check can't trivially pass due to bugs in the iterators
    assert tuple(layers_to_lock_names) == EXPECTED_LAYER_NAMES

    # Actually lock the environments
    build_env_to_lock.lock_environments()
    assert not build_env_to_lock._needs_lock()
    valid_locks, invalid_locks = _partition_envs(build_env_to_lock)
    assert valid_locks == all_layer_names
    assert invalid_locks == set()

    # Now check various modified stacks in the same folder as the locked stack
    # Ensure the expected layers are detected as no longer having valid locks
    # Note: modified stacks are never locked, so the nominal deps don't really matter
    unaffected_layer_names = {
        name for name in EXPECTED_LAYER_NAMES if name.endswith("-unaffected")
    }
    subtests_started = subtests_passed = 0  # Track subtest failures
    with subtests.test("Already locked stack with no changes"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == all_layer_names
        assert invalid_locks == set()
        assert not build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Enable implicit layer versioning at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["runtimes"][0]
        assert env_spec_to_modify["name"] == "cpython-to-be-modified"
        env_spec_to_modify["versioned"] = True
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Enable implicit layer versioning at framework layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["frameworks"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["versioned"] = True
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names | {
            "cpython-to-be-modified",
            "framework-other-app-dependency",
            "app-runtime-only",
        }
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Enable implicit layer versioning at application layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["versioned"] = True
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_invalid_locks = {"app-to-be-modified"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change declared requirements at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["runtimes"][0]
        assert env_spec_to_modify["name"] == "cpython-to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change declared requirements at framework layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["frameworks"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names | {
            "cpython-to-be-modified",
            "framework-other-app-dependency",
            "app-runtime-only",
        }
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change declared requirements at application layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_invalid_locks = {"app-to-be-modified"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Switch Python maintenance release at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["runtimes"][0]
        assert env_spec_to_modify["name"] == "cpython-to-be-modified"
        assert env_spec_to_modify["python_implementation"].startswith("cpython@3.11.")
        updated_py_version = "cpython@3.11.5"
        assert env_spec_to_modify["python_implementation"] != updated_py_version
        env_spec_to_modify["python_implementation"] = updated_py_version
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == all_layer_names
        assert invalid_locks == set()
        assert not build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Update to new major Python version at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["runtimes"][0]
        assert env_spec_to_modify["name"] == "cpython-to-be-modified"
        assert env_spec_to_modify["python_implementation"].startswith("cpython@3.11.")
        env_spec_to_modify["python_implementation"] = "cpython@3.12.5"
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change declared runtime at framework layer"):
        # Even if the major Python version doesn't change, the layer needs updating
        # This is due to the relative path to the runtime saved in the deployed layer config
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        for env_spec_to_modify in spec_data_to_check["frameworks"]:
            # Must modify both framework layers, otherwise stack spec is rejected as inconsistent
            if env_spec_to_modify["name"] not in (
                "to-be-modified",
                "other-app-dependency",
            ):
                continue
            env_spec_to_modify["runtime"] = "cpython-same-major-version-unaffected"
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names | {
            "cpython-to-be-modified",
            "app-runtime-only",
        }
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change declared runtime at application layer"):
        # Even if the major Python version doesn't change, the layer needs updating
        # This is due to the relative base runtime path saved in the deployed layer config
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][1]
        assert env_spec_to_modify["name"] == "runtime-only"
        env_spec_to_modify["runtime"] = "cpython-same-major-version-unaffected"
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_invalid_locks = {"app-runtime-only"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change framework dependencies at framework layer"):
        # Even if the locked requirements don't change, the layer needs updating
        # This is due to the relative framework paths saved in the deployed layer config
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["frameworks"][2]
        assert env_spec_to_modify["name"] == "dependent"
        assert env_spec_to_modify["frameworks"] == ["to-be-modified"]
        env_spec_to_modify["frameworks"] = ["other-app-dependency"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_valid_locks = unaffected_layer_names | {
            "cpython-to-be-modified",
            "framework-to-be-modified",
            "framework-other-app-dependency",
            "app-runtime-only",
        }
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change framework dependencies at application layer"):
        # Even if the locked requirements don't change, the layer needs updating
        # This is due to the relative framework paths saved in the deployed layer config
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["frameworks"].remove("dependent")
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_invalid_locks = {"app-to-be-modified"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change launch module name at application layer"):
        # Even if the locked requirements don't change, the layer needs updating
        # This is due to the launch module needing to be invoked differently
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["launch_module"] = "launch2.py"
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        expected_invalid_locks = {"app-to-be-modified"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        assert build_env._needs_lock()
        subtests_passed += 1
    # Remaining subtests need to modify the actual envs, not just the layer specifications
    env_to_modify: LayerEnvBase
    with subtests.test("Change locked requirements at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.runtimes[
            LayerBaseName("cpython-to-be-modified")
        ]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            expected_valid_locks = unaffected_layer_names
            expected_invalid_locks = all_layer_names - expected_valid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
            assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change locked requirements at framework layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.frameworks[LayerBaseName("to-be-modified")]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            expected_valid_locks = unaffected_layer_names | {
                "cpython-to-be-modified",
                "framework-other-app-dependency",
                "app-runtime-only",
            }
            expected_invalid_locks = all_layer_names - expected_valid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
            assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change locked requirements at application layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.applications[LayerBaseName("to-be-modified")]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            expected_invalid_locks = {"app-to-be-modified"}
            expected_valid_locks = all_layer_names - expected_invalid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
            assert build_env._needs_lock()
        subtests_passed += 1
    with subtests.test("Change launch module content at application layer"):
        # Even if the locked requirements don't change, the layer needs updating
        # This is due to the launch module needing to be invoked differently
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        with _modified_file(
            launch_module_path, "# Changed launch module contents"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            expected_invalid_locks = {"app-to-be-modified"}
            expected_valid_locks = all_layer_names - expected_invalid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
            assert build_env._needs_lock()
        subtests_passed += 1

    # Work around pytest-subtests not failing the test case when subtests fail
    # https://github.com/pytest-dev/pytest-subtests/issues/76
    assert subtests_passed == subtests_started, (
        f"Fail due to failed subtest(s) ({subtests_passed} < {subtests_started})"
    )
