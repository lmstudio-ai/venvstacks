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
# cosmetic format changes which don't otherwise affect the lockfile contents.
# This script was added as part of the update that switched to at least somewhat
# semantically aware hashing of the layer requirements files, so it should be less
# necessary in the future)


def _rehash_req_file(req_path: pathlib.Path, algorithm: str = "sha256") -> str:
    # Reimplemented, as script is easier to use if it doesn't depend on the project API
    reqs: list[str] = []
    for req_line in req_path.read_text().splitlines():
        req, _sep, _comment = req_line.strip().partition("#")
        req = req.strip()
        if req:
            reqs.append(req)
    reqs.sort()
    incremental_hash = hashlib.new(algorithm)
    for req in reqs:
        incremental_hash.update(req.encode())
    reqs_hash = incremental_hash.hexdigest()
    return f"{algorithm}:{reqs_hash}"


def _rehash_lockfiles() -> None:
    requirements_path = _REPO_DIR / "tests/sample_project/requirements"

    updated_hashes: dict[tuple[str, str], str] = {}

    for json_path in requirements_path.rglob("**/*.json"):
        print(f"Updating {json_path.relative_to(_REPO_DIR)}...")
        bundle_name = json_path.parent.name
        target_platform = json_path.name.partition(".txt")[0].rpartition("-")[2]
        lock_metadata: dict[str, typing.Any] = json.loads(json_path.read_text())
        requirements_path = json_path.with_name(json_path.stem)
        requirements_hash = _rehash_req_file(requirements_path)
        lock_metadata["requirements_hash"] = requirements_hash
        lock_input_hash = _rehash_req_file(requirements_path.with_suffix(".in"))
        lock_metadata["lock_input_hash"] = lock_input_hash
        updated_hashes[(bundle_name, target_platform)] = requirements_hash
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
