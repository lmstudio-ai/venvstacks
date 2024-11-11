"""Test cases for hashing utility functions."""

import hashlib
import shutil
import tempfile

import pytest

from pathlib import Path
from typing import Generator, Mapping

from venvstacks.stacks import _hash_directory, _hash_file

_THIS_PATH = Path(__file__)
HASH_FODDER_PATH = _THIS_PATH.parent / "hash_fodder"

# Expected hashes generated with `sha256sum` rather than Python
# Examples ensure that file names don't affect the hash, but the file contents do
SHA256_ALGORITHM = "sha256"
EXPECTED_FILE_HASHES_SHA256: Mapping[str, str] = {
    "file.txt": "84dae841773532dcc56da3a65a4c992534c385649645bf0340873da2e2ce7d6a",
    "file_duplicate.txt": "84dae841773532dcc56da3a65a4c992534c385649645bf0340873da2e2ce7d6a",
    "different_file.txt": "43691ae21f1fd9540bb5b9a6f2ab07fd5be4c2a0545231dc505a5f33a1619337",
}

# Expected hashes generated with `b2sum` rather than Python
# Examples ensure that file names don't affect the hash, but the file contents do
BLAKE2_ALGORITHM = "blake2b"
EXPECTED_FILE_HASHES_BLAKE2: Mapping[str, str] = {
    "file.txt": "bf4d9de4092670662fe8985f38880ce2d1b34ee74a4a110ea6dde23903388bc4fb18b233cc5fb027a2b374731ed6cc9274e244af5605040aa59882a7d6b68b0d",
    "file_duplicate.txt": "bf4d9de4092670662fe8985f38880ce2d1b34ee74a4a110ea6dde23903388bc4fb18b233cc5fb027a2b374731ed6cc9274e244af5605040aa59882a7d6b68b0d",
    "different_file.txt": "4783a95cdf9b6d0ebc4fe0d553ed6424b0a55400d9ead89b7c5b2dff26fb210aa1f7f9f8b809e58c7f2c79b4e046eea1b52c3a19032d2b861e792814b4ad0782",
}

# Default algorithm is SHA256
DEFAULT_ALGORITHM = SHA256_ALGORITHM
EXPECTED_FILE_HASHES_DEFAULT = EXPECTED_FILE_HASHES_SHA256


# Flatten the content hash mappings into 3-tuples for easier test parameterisation
def _all_expected_file_hashes() -> Generator[tuple[str, str, str], None, None]:
    for fname, expected_hash in EXPECTED_FILE_HASHES_SHA256.items():
        yield SHA256_ALGORITHM, fname, expected_hash
    for fname, expected_hash in EXPECTED_FILE_HASHES_BLAKE2.items():
        yield BLAKE2_ALGORITHM, fname, expected_hash


EXPECTED_FILE_HASHES = [*_all_expected_file_hashes()]


class TestFileHashing:
    @pytest.mark.parametrize(
        "fname,expected_hash", EXPECTED_FILE_HASHES_DEFAULT.items()
    )
    def test_default_hash(self, fname: str, expected_hash: str) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert _hash_file(file_path) == f"{DEFAULT_ALGORITHM}:{expected_hash}"
        assert _hash_file(file_path, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm,fname,expected_hash", EXPECTED_FILE_HASHES)
    def test_algorithm_selection(
        self, algorithm: str, fname: str, expected_hash: str
    ) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert _hash_file(file_path, algorithm) == f"{algorithm}:{expected_hash}"
        assert _hash_file(file_path, algorithm, omit_prefix=True) == expected_hash


# Directory hashing uses a custom algorithm (hence the non-standard prefix separator).
# However, the expected hashes for the `hash_fodder` folder can be calculated by specifying
# the expected order that different components of the hash are added to the algorithm:
#
# * directories are visited top down in sorted order
# * directory names are added to the hash when they are visited
# * file content hashes are added to the hash in sorted order after the directory name

EXPECTED_DIR_HASH_SEQUENCE = [
    ("dirname", "hash_fodder"),
    ("filename", "different_file.txt"),
    ("contents_hash", "different_file.txt"),
    ("filename", "file.txt"),
    ("contents_hash", "file.txt"),
    ("filename", "file_duplicate.txt"),
    ("contents_hash", "file_duplicate.txt"),
    ("dirname", "folder1"),
    ("filename", "file.txt"),
    ("contents_hash", "file.txt"),
    ("dirname", "subfolder"),
    ("filename", "file.txt"),
    ("contents_hash", "file.txt"),
    ("dirname", "folder2"),
    ("filename", "file_duplicate.txt"),
    ("contents_hash", "file_duplicate.txt"),
]


def _make_expected_dir_hash(algorithm: str, content_hashes: Mapping[str, str]) -> str:
    incremental_hash = hashlib.new(algorithm)
    for component_kind, component_text in EXPECTED_DIR_HASH_SEQUENCE:
        match component_kind:
            case "dirname" | "filename":
                hash_component = component_text.encode()
            case "contents_hash":
                # Directory hashing includes the algorithm prefix (at least for now)
                hash_component = (
                    f"{algorithm}:{content_hashes[component_text]}".encode()
                )
        print(component_text, hash_component)
        incremental_hash.update(hash_component)
    return incremental_hash.hexdigest()


EXPECTED_DIR_HASHES = {
    "sha256": _make_expected_dir_hash("sha256", EXPECTED_FILE_HASHES_SHA256),
    "blake2b": _make_expected_dir_hash("blake2b", EXPECTED_FILE_HASHES_BLAKE2),
}


@pytest.fixture
def cloned_dir_path() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as dir_name:
        temp_dir_path = Path(dir_name)
        cloned_hash_fodder_path = temp_dir_path / HASH_FODDER_PATH.name
        shutil.copytree(HASH_FODDER_PATH, cloned_hash_fodder_path)
        yield cloned_hash_fodder_path


class TestDirectoryHashing:
    def test_default_hash(self) -> None:
        dir_path = HASH_FODDER_PATH
        expected_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert _hash_directory(dir_path) == f"{DEFAULT_ALGORITHM}/{expected_hash}"
        assert _hash_directory(dir_path, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm,expected_hash", EXPECTED_DIR_HASHES.items())
    def test_algorithm_selection(self, algorithm: str, expected_hash: str) -> None:
        dir_path = HASH_FODDER_PATH
        assert _hash_directory(dir_path, algorithm) == f"{algorithm}/{expected_hash}"
        assert _hash_directory(dir_path, algorithm, omit_prefix=True) == expected_hash

    def test_root_dir_name_change_detected(self, cloned_dir_path: Path) -> None:
        renamed_dir_path = cloned_dir_path.with_name("something_completely_different")
        cloned_dir_path.rename(renamed_dir_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert _hash_directory(renamed_dir_path, omit_prefix=True) != unmodified_hash

    def test_subdir_name_change_detected(self, cloned_dir_path: Path) -> None:
        subfolder_path = cloned_dir_path / "folder1"
        renamed_dir_path = subfolder_path.with_name("something_completely_different")
        subfolder_path.rename(renamed_dir_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert _hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash

    def test_file_name_change_detected(self, cloned_dir_path: Path) -> None:
        file_path = cloned_dir_path / "folder1/subfolder/file.txt"
        renamed_file_path = file_path.with_name("something_completely_different")
        file_path.rename(renamed_file_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert _hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash

    def test_file_contents_change_detected(self, cloned_dir_path: Path) -> None:
        file_path = cloned_dir_path / "folder1/subfolder/file.txt"
        file_path.write_text("This changes the directory hash")
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert _hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash
