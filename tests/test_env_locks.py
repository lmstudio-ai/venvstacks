"""Test cases for environment lock management."""

import tempfile
import tomllib

import pytest

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from pytest_subtests import SubTests

from venvstacks.stacks import (
    BuildEnvironment,
    EnvironmentLock,
    LayerBaseName,
    LayerEnvBase,
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
    env_lock = EnvironmentLock(req_path, ())
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
    env_lock = EnvironmentLock(req_path, ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    env_lock_metadata = env_lock.load_valid_metadata()
    assert env_lock_metadata is not None
    # Loading the lock without changes gives the same metadata
    loaded_lock = EnvironmentLock(req_path, ())
    assert loaded_lock._lock_input_hash == env_lock._lock_input_hash
    assert loaded_lock._requirements_hash == env_lock._requirements_hash
    assert loaded_lock.load_valid_metadata() == env_lock_metadata


def test_load_with_inconsistent_input_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with different requirements invalidates the metadata
    loaded_lock = EnvironmentLock(req_path, ("some-requirement",))
    assert loaded_lock._lock_input_hash != env_lock._lock_input_hash
    assert loaded_lock._requirements_hash is None
    assert loaded_lock.load_valid_metadata() is None


def test_load_with_inconsistent_output_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    env_lock.prepare_lock_inputs()
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._lock_input_hash is not None
    assert env_lock._requirements_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with a different lock file invalidates the metadata
    env_lock.locked_requirements_path.write_text("")
    loaded_lock = EnvironmentLock(req_path, ())
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
EXAMPLE_STACK_SPEC = f"""\
[[runtimes]]
name = "cpython-to-be-modified"
python_implementation = "cpython@3.11.11"
requirements = []

[[runtimes]]
name = "cpython-unrelated"
python_implementation = "cpython@3.12.9"
requirements = []

[[frameworks]]
name = "to-be-modified"
runtime = "cpython-to-be-modified"
requirements = []

[[frameworks]]
name = "dependent"
frameworks = ["to-be-modified"]
requirements = []

[[frameworks]]
name = "other-app-dependency"
runtime = "cpython-to-be-modified"
requirements = []

[[frameworks]]
name = "unrelated"
runtime = "cpython-unrelated"
requirements = []

[[applications]]
name = "to-be-modified"
launch_module = "{EMPTY_SCRIPT_PATH}"
frameworks = ["other-app-dependency", "dependent"]
requirements = []

[[applications]]
name = "unrelated"
launch_module = "{EMPTY_SCRIPT_PATH}"
frameworks = ["unrelated"]
requirements = []
"""

EXPECTED_LAYER_NAMES = (
    "cpython-to-be-modified",
    "cpython-unrelated",
    "framework-to-be-modified",
    "framework-dependent",
    "framework-other-app-dependency",
    "framework-unrelated",
    "app-to-be-modified",
    "app-unrelated",
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
        backup_path.rename(file_path)


def test_build_env_layer_locks(temp_dir_path: Path, subtests: SubTests) -> None:
    # Built as a monolithic tests with subtests for performance reasons
    # (initial setup takes ~10 seconds, subsequent checks are fractions of a second)
    spec_path = temp_dir_path / "venvstacks.toml"
    updated_spec_path = temp_dir_path / "venvstacks_updated.toml"
    spec_data = tomllib.loads(EXAMPLE_STACK_SPEC)
    build_env_to_lock = _define_lock_testing_env(spec_path, spec_data)
    # Check for divergence between stack spec and the expected results
    layer_names = tuple(env.env_name for env in build_env_to_lock.all_environments())
    assert layer_names == EXPECTED_LAYER_NAMES
    # Preliminary checks that locking the stack updates the state as expected
    assert build_env_to_lock._needs_lock()
    all_layer_names = {*EXPECTED_LAYER_NAMES}
    valid_locks, invalid_locks = _partition_envs(build_env_to_lock)
    assert valid_locks == set()
    assert invalid_locks == all_layer_names
    assert all(env.needs_lock() for env in build_env_to_lock.all_environments())
    build_env_to_lock.lock_environments()
    assert not build_env_to_lock._needs_lock()
    valid_locks, invalid_locks = _partition_envs(build_env_to_lock)
    assert valid_locks == all_layer_names
    assert invalid_locks == set()

    # Now check various modified stacks in the same folder as the locked stack
    # Ensure the expected layers are detected as no longer having valid locks
    # Note: modified stacks are never locked, so the nominal deps don't really matter
    unrelated_layer_names = {
        name for name in EXPECTED_LAYER_NAMES if name.endswith("-unrelated")
    }
    subtests_started = subtests_passed = 0  # Track subtest failures
    with subtests.test("Already locked stack with no changes"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        assert not build_env._needs_lock()
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == all_layer_names
        assert invalid_locks == set()
        subtests_passed += 1
    with subtests.test("Changed declared requirements at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["runtimes"][0]
        assert env_spec_to_modify["name"] == "cpython-to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        assert build_env._needs_lock()
        expected_valid_locks = unrelated_layer_names
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        subtests_passed += 1
    with subtests.test("Changed declared requirements at framework layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["frameworks"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        assert build_env._needs_lock()
        expected_valid_locks = unrelated_layer_names | {
            "cpython-to-be-modified",
            "framework-other-app-dependency",
        }
        expected_invalid_locks = all_layer_names - expected_valid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        subtests_passed += 1
    with subtests.test("Changed declared requirements at application layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_spec_to_modify = spec_data_to_check["applications"][0]
        assert env_spec_to_modify["name"] == "to-be-modified"
        env_spec_to_modify["requirements"] = ["pip==25.1"]
        build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
        assert build_env._needs_lock()
        expected_invalid_locks = {"app-to-be-modified"}
        expected_valid_locks = all_layer_names - expected_invalid_locks
        valid_locks, invalid_locks = _partition_envs(build_env)
        assert valid_locks == expected_valid_locks
        assert invalid_locks == expected_invalid_locks
        subtests_passed += 1
    env_to_modify: LayerEnvBase
    with subtests.test("Changed locked requirements at runtime layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.runtimes[
            LayerBaseName("cpython-to-be-modified")
        ]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            assert build_env._needs_lock()
            expected_valid_locks = unrelated_layer_names
            expected_invalid_locks = all_layer_names - expected_valid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
        subtests_passed += 1
    with subtests.test("Changed locked requirements at framework layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.frameworks[LayerBaseName("to-be-modified")]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            assert build_env._needs_lock()
            expected_valid_locks = unrelated_layer_names | {
                "cpython-to-be-modified",
                "framework-other-app-dependency",
            }
            expected_invalid_locks = all_layer_names - expected_valid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
        subtests_passed += 1
    with subtests.test("Changed locked requirements at application layer"):
        subtests_started += 1
        spec_data_to_check = tomllib.loads(EXAMPLE_STACK_SPEC)
        env_to_modify = build_env_to_lock.applications[LayerBaseName("to-be-modified")]
        with _modified_file(
            env_to_modify.env_lock.locked_requirements_path, "pip==25.1"
        ):
            build_env = _define_lock_testing_env(updated_spec_path, spec_data_to_check)
            assert build_env._needs_lock()
            expected_invalid_locks = {"app-to-be-modified"}
            expected_valid_locks = all_layer_names - expected_invalid_locks
            valid_locks, invalid_locks = _partition_envs(build_env)
            assert valid_locks == expected_valid_locks
            assert invalid_locks == expected_invalid_locks
        subtests_passed += 1

    # Work around pytest-subtests not failing the test case when subtests fail
    # https://github.com/pytest-dev/pytest-subtests/issues/76
    assert subtests_passed == subtests_started, (
        f"Fail due to failed subtest(s) ({subtests_passed} < {subtests_started})"
    )
