"""Test cases for environment lock management."""

import tempfile

import pytest

from pathlib import Path
from typing import Generator

from venvstacks.stacks import EnvironmentLock


##########################
# Test cases
##########################


@pytest.fixture
def temp_dir_path() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as dir_name:
        yield Path(dir_name)


def test_default_state(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    # Declared requirements file is implicitly created
    assert env_lock.declared_requirements == ()
    assert env_lock.declared_requirements_path == temp_dir_path / "requirements.in"
    assert env_lock.declared_requirements_path.read_text() != ""
    assert env_lock._declared_req_hash is not None
    # Locked requirements file must be written externally
    assert env_lock.locked_requirements_path == req_path
    assert not env_lock.locked_requirements_path.exists()
    assert env_lock._locked_req_hash is None
    # Metadata file is only written when requested
    assert env_lock.lock_metadata_path == temp_dir_path / "requirements.txt.json"
    assert not env_lock.lock_metadata_path.exists()
    assert env_lock.load_valid_metadata() is None


def test_load_with_consistent_file_hashes(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    env_lock.locked_requirements_path.write_text("")
    env_lock.update_lock_metadata()
    assert env_lock._declared_req_hash is not None
    assert env_lock._locked_req_hash is not None
    env_lock_metadata = env_lock.load_valid_metadata()
    assert env_lock_metadata is not None
    # Loading the lock without changes gives the same metadata
    loaded_lock = EnvironmentLock(req_path, ())
    assert loaded_lock._declared_req_hash == env_lock._declared_req_hash
    assert loaded_lock._locked_req_hash == env_lock._locked_req_hash
    assert loaded_lock.load_valid_metadata() == env_lock_metadata


def test_load_with_inconsistent_input_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._declared_req_hash is not None
    assert env_lock._locked_req_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with different requirements invalidates the metadata
    loaded_lock = EnvironmentLock(req_path, ("some-requirement",))
    assert loaded_lock._declared_req_hash != env_lock._declared_req_hash
    assert loaded_lock._locked_req_hash == env_lock._locked_req_hash
    assert loaded_lock.load_valid_metadata() is None


def test_load_with_inconsistent_output_hash(temp_dir_path: Path) -> None:
    req_path = temp_dir_path / "requirements.txt"
    env_lock = EnvironmentLock(req_path, ())
    env_lock.locked_requirements_path.write_text("Hash fodder")
    env_lock.update_lock_metadata()
    assert env_lock._declared_req_hash is not None
    assert env_lock._locked_req_hash is not None
    assert env_lock.load_valid_metadata() is not None
    # Loading the lock with a different lock file invalidates the metadata
    env_lock.locked_requirements_path.write_text("")
    loaded_lock = EnvironmentLock(req_path, ())
    assert loaded_lock._declared_req_hash == env_lock._declared_req_hash
    assert loaded_lock._locked_req_hash != env_lock._locked_req_hash
    assert loaded_lock.load_valid_metadata() is None
