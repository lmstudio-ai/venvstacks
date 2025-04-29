#!/usr/bin/env python3
"""Helper script to update hashes in layer lock metadata files."""

import hashlib
import itertools
import json
import pathlib
import typing

_THIS_DIR = pathlib.Path(__file__).parent
_REPO_DIR = _THIS_DIR.parent

# Utility script to programmatically rehash the test requirements files for
# cosmetic format changes which don't otherwise affect the lockfile contents


def _rehash_file(path: pathlib.Path, algorithm: str = "sha256") -> str:
    # Reimplemented, as script is easier to use if it doesn't depend on the project API
    with path.open("rb", buffering=0) as f:
        file_hash = hashlib.file_digest(f, algorithm).hexdigest()
    return f"{algorithm}:{file_hash}"


def _rehash_lockfiles() -> None:
    requirements_path = _REPO_DIR / "tests/sample_project/requirements"

    updated_hashes: dict[tuple[str, str], str] = {}

    for json_path in requirements_path.rglob("**/*.json"):
        print(f"Updating {json_path.relative_to(_REPO_DIR)}...")
        bundle_name = json_path.parent.name
        target_platform = json_path.name.partition(".txt")[0].rpartition("-")[2]
        lock_metadata: dict[str, typing.Any] = json.loads(json_path.read_text())
        lock_metadata.pop("requirements_hash", None)
        requirements_path = json_path.with_name(json_path.stem)
        locked_req_hash = _rehash_file(requirements_path)
        lock_metadata["locked_req_hash"] = locked_req_hash
        declared_req_hash = _rehash_file(requirements_path.with_suffix(".in"))
        lock_metadata["declared_req_hash"] = declared_req_hash
        updated_hashes[(bundle_name, target_platform)] = locked_req_hash
        # Update the lock metadata file
        json_path.write_text(json.dumps(lock_metadata, indent=2, sort_keys=True) + "\n")

    # Update the related archive manifests
    def manifest_update(metadata: dict[str, typing.Any], target_platform: str) -> None:
        layer_name = metadata["layer_name"]
        updated_hash = updated_hashes[(layer_name, target_platform)]
        metadata["requirements_hash"] = updated_hash

    _apply_manifest_update(manifest_update)


def _apply_manifest_update(
    manifest_update: typing.Callable[[dict[str, typing.Any], str], None],
) -> None:
    metadata_path = _REPO_DIR / "tests/sample_project/expected_manifests"

    for json_path in metadata_path.rglob("**/*.json"):
        print(f"Updating {json_path.relative_to(_REPO_DIR)}...")
        metadata = json.loads(json_path.read_text())
        layer_manifests = metadata.get("layers", None)
        if layer_manifests is not None:
            target_platform = json_path.parent.name
            for archive_metadata in itertools.chain(*layer_manifests.values()):
                manifest_update(archive_metadata, target_platform)
        else:
            target_platform = json_path.parent.parent.name
            manifest_update(metadata, target_platform)
        json_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    _rehash_lockfiles()
