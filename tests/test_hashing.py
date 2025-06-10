"""Test cases for hashing and content filtering utility functions."""

import hashlib
import shutil
import tempfile

from dulwich.repo import Repo
import pytest

from contextlib import closing
from pathlib import Path
from typing import Generator, Mapping

from venvstacks._hash_content import (
    hash_directory,
    hash_file_contents,
    hash_file_name_and_contents,
    hash_strings,
)
from venvstacks._source_tree import (
    SourceTreeIgnorePycache,
    SourceTreeGit,
    get_default_source_filter,
)

##################################
# Hash testing helpers
##################################

_THIS_PATH = Path(__file__)
HASH_FODDER_PATH = _THIS_PATH.parent / "hash_fodder"

# Expected content hashes generated with `sha256sum` rather than Python
# Examples ensure that file names don't affect the hash, but the file contents do
# Combined hashes are checked for consistency against their initial implementation
SHA256_ALGORITHM = "sha256"
EXPECTED_CONTENT_HASHES_SHA256: Mapping[str, str] = {
    "file.txt": "84dae841773532dcc56da3a65a4c992534c385649645bf0340873da2e2ce7d6a",
    "file_duplicate.txt": "84dae841773532dcc56da3a65a4c992534c385649645bf0340873da2e2ce7d6a",
    "different_file.txt": "43691ae21f1fd9540bb5b9a6f2ab07fd5be4c2a0545231dc505a5f33a1619337",
}
EXPECTED_COMBINED_HASHES_SHA256: Mapping[str, str] = {
    "file.txt": "6f0923fd3e132d2a05f0ee67b906d10af52e5993454ef38d024820a6fa3b2a12",
    "file_duplicate.txt": "a6d265b49ae38e1539d613d194befa0984bc0d6dcad66f46082e3e532dafc0e1",
    "different_file.txt": "4a23fc5657c4c15fce3f99c22af471a7432ac96e74ea3ca2ab7720da6b892756",
}

# Expected content hashes generated with `b2sum` rather than Python
# Examples ensure that file names don't affect the hash, but the file contents do
# Combined hashes are checked for consistency against their initial implementation
BLAKE2_ALGORITHM = "blake2b"
EXPECTED_CONTENT_HASHES_BLAKE2: Mapping[str, str] = {
    "file.txt": "bf4d9de4092670662fe8985f38880ce2d1b34ee74a4a110ea6dde23903388bc4fb18b233cc5fb027a2b374731ed6cc9274e244af5605040aa59882a7d6b68b0d",
    "file_duplicate.txt": "bf4d9de4092670662fe8985f38880ce2d1b34ee74a4a110ea6dde23903388bc4fb18b233cc5fb027a2b374731ed6cc9274e244af5605040aa59882a7d6b68b0d",
    "different_file.txt": "4783a95cdf9b6d0ebc4fe0d553ed6424b0a55400d9ead89b7c5b2dff26fb210aa1f7f9f8b809e58c7f2c79b4e046eea1b52c3a19032d2b861e792814b4ad0782",
}
EXPECTED_COMBINED_HASHES_BLAKE2: Mapping[str, str] = {
    "file.txt": "6308aff6e73bac77a1cc5d7669eedee59174040c674b2304dd73236c5ea5a3881d8ed4095700d9a22f68c84a73cee71cb965a6ba84efe546707fcea09fb150f0",
    "file_duplicate.txt": "3686fb1772e99186bc7b10ca8728d0e2d0496d6eebc9b2fda8b24a9030a0e627bbc4e119b5b8edb64caab5a9acb1b6f7aa85b79c2508562f3314dd97fb51ce7c",
    "different_file.txt": "702163efe664584b88b9a28e254c655d873bebbea4b1963bc5fdc7137dd209e8d2f743f9403563fddc3b7b27aa60f4f7a6ce87f8a6bc14971a09e4594f122bf8",
}

# Default algorithm is SHA256
DEFAULT_ALGORITHM = SHA256_ALGORITHM
EXPECTED_CONTENT_HASHES_DEFAULT = EXPECTED_CONTENT_HASHES_SHA256
EXPECTED_COMBINED_HASHES_DEFAULT = EXPECTED_COMBINED_HASHES_SHA256

# Flatten the content hash mappings into 3-tuples for easier test parameterisation
ALGORITHMS_TO_EXPECTED_CONTENT_HASHES = {
    SHA256_ALGORITHM: EXPECTED_CONTENT_HASHES_SHA256,
    BLAKE2_ALGORITHM: EXPECTED_CONTENT_HASHES_BLAKE2,
}
ALGORITHMS_TO_EXPECTED_COMBINED_HASHES = {
    SHA256_ALGORITHM: EXPECTED_COMBINED_HASHES_SHA256,
    BLAKE2_ALGORITHM: EXPECTED_COMBINED_HASHES_BLAKE2,
}


def _flatten_expected_file_hashes(
    algorithms_to_hashes: Mapping[str, Mapping[str, str]],
) -> Generator[tuple[str, str, str], None, None]:
    for algorithm, expected_hashes in algorithms_to_hashes.items():
        for fname, expected_hash in expected_hashes.items():
            yield algorithm, fname, expected_hash


EXPECTED_CONTENT_HASHES = [
    *_flatten_expected_file_hashes(ALGORITHMS_TO_EXPECTED_CONTENT_HASHES)
]
EXPECTED_COMBINED_HASHES = [
    *_flatten_expected_file_hashes(ALGORITHMS_TO_EXPECTED_COMBINED_HASHES)
]

STRINGS_TO_HASH = (
    "A string",
    "Another string",
    "A string with non-ASCII characters: 🦎🐸🦎",
)
EXPECTED_STRING_ITERABLE_HASHES = {
    SHA256_ALGORITHM: "30ad29063127d5e45ade75380df47dbbcee1246c55e138b0d42419ecb3a8635a",
    BLAKE2_ALGORITHM: "cc67ce2ed4b3b8da567de50312ea33f9207b4fcd34be07476198e7e9a20422e5c2795ef3f3c955581b53bcf715dab5945b687ef3f1e8e6a8ef1bc9bf327f72e4",
}


##########################
# Test cases
##########################


class TestStringIterableHashing:
    def test_default_hash(self) -> None:
        hash_fodder = STRINGS_TO_HASH
        expected_hash = EXPECTED_STRING_ITERABLE_HASHES[DEFAULT_ALGORITHM]
        assert hash_strings(hash_fodder) == f"{DEFAULT_ALGORITHM}:{expected_hash}"
        assert hash_strings(hash_fodder, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm", ALGORITHMS_TO_EXPECTED_CONTENT_HASHES)
    def test_algorithm_selection(self, algorithm: str) -> None:
        hash_fodder = STRINGS_TO_HASH
        expected_hash = EXPECTED_STRING_ITERABLE_HASHES[algorithm]
        assert hash_strings(hash_fodder, algorithm) == f"{algorithm}:{expected_hash}"
        assert hash_strings(hash_fodder, algorithm, omit_prefix=True) == expected_hash


class TestFileContentHashing:
    @pytest.mark.parametrize(
        "fname,expected_hash", EXPECTED_CONTENT_HASHES_DEFAULT.items()
    )
    def test_default_hash(self, fname: str, expected_hash: str) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert hash_file_contents(file_path) == f"{DEFAULT_ALGORITHM}:{expected_hash}"
        assert hash_file_contents(file_path, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm,fname,expected_hash", EXPECTED_CONTENT_HASHES)
    def test_algorithm_selection(
        self, algorithm: str, fname: str, expected_hash: str
    ) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert (
            hash_file_contents(file_path, algorithm) == f"{algorithm}:{expected_hash}"
        )
        assert (
            hash_file_contents(file_path, algorithm, omit_prefix=True) == expected_hash
        )


class TestFileNameAndContentHashing:
    @pytest.mark.parametrize(
        "fname,expected_hash", EXPECTED_COMBINED_HASHES_DEFAULT.items()
    )
    def test_default_hash(self, fname: str, expected_hash: str) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert (
            hash_file_name_and_contents(file_path)
            == f"{DEFAULT_ALGORITHM}:{expected_hash}"
        )
        assert hash_file_name_and_contents(file_path, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm,fname,expected_hash", EXPECTED_COMBINED_HASHES)
    def test_algorithm_selection(
        self, algorithm: str, fname: str, expected_hash: str
    ) -> None:
        file_path = HASH_FODDER_PATH / fname
        assert (
            hash_file_name_and_contents(file_path, algorithm)
            == f"{algorithm}:{expected_hash}"
        )
        assert (
            hash_file_name_and_contents(file_path, algorithm, omit_prefix=True)
            == expected_hash
        )


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
        # print(component_text, hash_component)
        incremental_hash.update(hash_component)
    return incremental_hash.hexdigest()


EXPECTED_DIR_HASHES = {
    algorithm: _make_expected_dir_hash(algorithm, expected_content_hashes)
    for algorithm, expected_content_hashes in ALGORITHMS_TO_EXPECTED_CONTENT_HASHES.items()
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
        assert hash_directory(dir_path) == f"{DEFAULT_ALGORITHM}/{expected_hash}"
        assert hash_directory(dir_path, omit_prefix=True) == expected_hash

    @pytest.mark.parametrize("algorithm,expected_hash", EXPECTED_DIR_HASHES.items())
    def test_algorithm_selection(self, algorithm: str, expected_hash: str) -> None:
        dir_path = HASH_FODDER_PATH
        assert hash_directory(dir_path, algorithm) == f"{algorithm}/{expected_hash}"
        assert hash_directory(dir_path, algorithm, omit_prefix=True) == expected_hash

    def test_root_dir_name_change_detected(self, cloned_dir_path: Path) -> None:
        renamed_dir_path = cloned_dir_path.with_name("something_completely_different")
        cloned_dir_path.rename(renamed_dir_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert hash_directory(renamed_dir_path, omit_prefix=True) != unmodified_hash

    def test_subdir_name_change_detected(self, cloned_dir_path: Path) -> None:
        subfolder_path = cloned_dir_path / "folder1"
        renamed_dir_path = subfolder_path.with_name("something_completely_different")
        subfolder_path.rename(renamed_dir_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash

    def test_file_name_change_detected(self, cloned_dir_path: Path) -> None:
        file_path = cloned_dir_path / "folder1/subfolder/file.txt"
        renamed_file_path = file_path.with_name("something_completely_different")
        file_path.rename(renamed_file_path)
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash

    def test_file_contents_change_detected(self, cloned_dir_path: Path) -> None:
        file_path = cloned_dir_path / "folder1/subfolder/file.txt"
        file_path.write_text("This changes the directory hash")
        unmodified_hash = EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]
        assert hash_directory(cloned_dir_path, omit_prefix=True) != unmodified_hash


class TestSourceTreeContentFiltering:
    def _make_subdir(self, dir_path: Path) -> Path:
        subdir_path = dir_path / "__pycache__/nested/subdir"
        subdir_path.mkdir(parents=True)
        return subdir_path

    def test_pycache_filter(self, cloned_dir_path: Path) -> None:
        dir_path = cloned_dir_path
        subdir_path = self._make_subdir(dir_path)
        # Default filter just returns the given path when queried
        assert SourceTreeIgnorePycache.get_source_path(dir_path) == dir_path
        assert SourceTreeIgnorePycache.get_source_path(subdir_path) == subdir_path
        # No git metadata -> stateless default filter
        source_filter = get_default_source_filter(subdir_path)
        assert source_filter is SourceTreeIgnorePycache
        # Check __pycache__ is ignored as both a dir name and dir entry name
        entries = ["a", "b", "c"]
        with_pycache = ["a", "b", "__pycache__"]
        assert source_filter.ignore("", entries) == []
        assert source_filter.ignore("__pycache__", entries) == entries
        assert source_filter.ignore("/absolute/__pycache__", entries) == entries
        assert source_filter.ignore("", with_pycache) == ["__pycache__"]
        assert source_filter.ignore(str(dir_path), entries) == []
        assert source_filter.ignore(str(dir_path), with_pycache) == ["__pycache__"]
        assert source_filter.ignore(str(subdir_path), entries) == entries
        assert source_filter.ignore(str(subdir_path), with_pycache) == with_pycache
        # Subdir starts with __pycache__ and should be ignored
        expected_hash = f"{DEFAULT_ALGORITHM}/{EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]}"
        assert hash_directory(dir_path, walk_iter=source_filter.walk) == expected_hash

    def test_gitignore_filter(self, cloned_dir_path: Path) -> None:
        dir_path = cloned_dir_path
        subdir_path = self._make_subdir(dir_path)
        # Git filter reports None when there is no containing repository
        assert SourceTreeGit.get_source_path(dir_path) is None
        assert SourceTreeGit.get_source_path(subdir_path) is None
        with closing(Repo.init(dir_path.as_posix())):
            # Git filter finds the containing repository when queried
            assert SourceTreeGit.get_source_path(dir_path) == dir_path
            assert SourceTreeGit.get_source_path(subdir_path) == dir_path
            # Git metadata -> git based filter
            source_filter = get_default_source_filter(subdir_path)
            assert isinstance(source_filter, SourceTreeGit)
            assert source_filter.repo_path == dir_path
            # __pycache__ isn't ignored yet, but paths outside the tree are
            # Git metadata files are also all ignored by default
            entries = ["a", "b", "c"]
            with_pycache = ["a", "b", "__pycache__"]
            git_meta = [".git", ".gitignore"]
            assert source_filter.ignore("", entries) == entries
            assert source_filter.ignore("__pycache__", entries) == entries
            assert source_filter.ignore("/absolute/__pycache__", entries) == entries
            assert source_filter.ignore("", with_pycache) == with_pycache
            assert source_filter.ignore(str(dir_path), entries) == []
            assert source_filter.ignore(str(dir_path), with_pycache) == []
            assert source_filter.ignore(str(dir_path), git_meta) == git_meta
            assert source_filter.ignore(str(subdir_path), entries) == []
            assert source_filter.ignore(str(subdir_path), with_pycache) == []
            assert source_filter.ignore(str(subdir_path), git_meta) == git_meta
            # Subdir starts with __pycache__, but isn't ignored yet
            expected_hash = (
                f"{DEFAULT_ALGORITHM}/{EXPECTED_DIR_HASHES[DEFAULT_ALGORITHM]}"
            )
            assert (
                hash_directory(dir_path, walk_iter=source_filter.walk) != expected_hash
            )
            # Updating .gitignore updates the filtering
            ignore_path = dir_path / ".gitignore"
            ignore_path.write_text("__pycache__")
            # Check __pycache__ is ignored as both a dir name and dir entry name
            assert source_filter.ignore("", entries) == entries
            assert source_filter.ignore("__pycache__", entries) == entries
            assert source_filter.ignore("/absolute/__pycache__", entries) == entries
            assert source_filter.ignore("", with_pycache) == with_pycache
            assert source_filter.ignore(str(dir_path), entries) == []
            assert source_filter.ignore(str(dir_path), with_pycache) == ["__pycache__"]
            assert source_filter.ignore(str(dir_path), git_meta) == git_meta
            assert source_filter.ignore(str(subdir_path), entries) == entries
            assert source_filter.ignore(str(subdir_path), with_pycache) == with_pycache
            assert source_filter.ignore(str(subdir_path), git_meta) == git_meta
            # Subdir should now be ignored when hashing
            assert (
                hash_directory(dir_path, walk_iter=source_filter.walk) == expected_hash
            )
