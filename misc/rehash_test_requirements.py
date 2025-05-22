#!/usr/bin/env python3
"""Helper script to update hashes in layer lock metadata files."""

import itertools
import json
import pathlib
import typing

# Utility script to programmatically rehash the test requirements files for
# cosmetic format changes which don't otherwise affect the lockfile contents.
# This script was added as part of the update that switched to more robust
# semantically aware hashing of layer lock inputs, and may provide inspiration
# in updating stacks where republishing the world because the input hashing
# changed when migrating to a new version isn't desired.

try:
    # Import the CLI module first to avoid the API stability warning
    import venvstacks.cli # noqa
    from venvstacks.stacks import EnvironmentLock, StackSpec
except ImportError as exc:
    exc.add_note("Try 'pdm run migrate-hashes' if direct execution fails")

_THIS_DIR = pathlib.Path(__file__).parent
_REPO_DIR = _THIS_DIR.parent
_SPEC_PATH = _REPO_DIR / "tests/sample_project/venvstacks.toml"

def _rehash_req_file(req_file: pathlib.Path) -> str:
    req_hash = EnvironmentLock._hash_req_file(req_file)
    assert req_hash is not None
    return req_hash

def _rehash_layer_inputs() -> None:
    # Note: this does NOT bump the nominal version for implicit versioning
    # as it is only intended for use when the lock input hashing changes.
    # For *actual* input changes, the full metadata should be updated via a build.
    stack_spec = StackSpec.load(_SPEC_PATH)
    # The script won't actually create or modify any files in the build folder,
    # it's using this as a way to create the environment lock instances
    build_env = stack_spec.define_build_environment("not-populated")
    env_by_name = {str(env.env_name): env for env in build_env.all_environments()}

    updated_locked_hashes: dict[tuple[str, str], str] = {}
    for json_path in stack_spec.requirements_dir_path.rglob("**/*.json"):
        print(f"Updating {json_path.relative_to(_REPO_DIR)}...")
        bundle_name = json_path.parent.name
        target_platform = json_path.name.partition(".txt")[0].rpartition("-")[2]
        # Update the lock metadata file
        lock_metadata: dict[str, typing.Any] = json.loads(json_path.read_text())
        env_lock = env_by_name[bundle_name].env_lock
        lock_metadata["lock_input_hash"] = env_lock._lock_input_hash
        lock_metadata["other_inputs_hash"] = env_lock._other_inputs_hash
        requirements_path = json_path.with_name(json_path.stem)
        requirements_hash = _rehash_req_file(requirements_path)
        lock_metadata["requirements_hash"] = requirements_hash
        json_path.write_text(json.dumps(lock_metadata, indent=2, sort_keys=True) + "\n")
        # Manifests also contain the hash of the fully locked requirements
        updated_locked_hashes[(bundle_name, target_platform)] = requirements_hash

    # Update the related archive manifests
    def manifest_update(metadata: dict[str, typing.Any], target_platform: str) -> bool:
        layer_name = metadata["layer_name"]
        updated_hash = updated_locked_hashes.get((layer_name, target_platform))
        if updated_hash is None:
            return False
        metadata["requirements_hash"] = updated_hash
        return True

    _apply_manifest_update(manifest_update)


def _apply_manifest_update(
    manifest_update: typing.Callable[[dict[str, typing.Any], str], bool],
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
    _rehash_layer_inputs()
