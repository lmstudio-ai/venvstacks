"""Test loading assorted stack specifications."""

from pathlib import Path
from typing import Generator

import shutil
import tempfile

import pytest

from venvstacks.stacks import LayerLockError, LayerSpecError, StackSpec

##################################
# Stack spec loading test helpers
##################################


_THIS_PATH = Path(__file__)
TEST_SPEC_PATH = _THIS_PATH.parent / "stack_specs"


def _load_stack_spec(spec_name: str, *, working_path: Path | None = None) -> StackSpec:
    """Load the named stack specification."""
    source_spec_path = TEST_SPEC_PATH / spec_name
    if working_path is None:
        spec_path = source_spec_path
    else:
        spec_path = working_path / spec_name
        shutil.copyfile(source_spec_path, spec_path)
    return StackSpec.load(spec_path)


##########################
# Test cases
##########################


def test_at_symbol_in_layer_names() -> None:
    stack_spec = _load_stack_spec("at_symbol.toml")
    runtimes = list(stack_spec.all_environment_specs())
    assert len(runtimes) == 2
    unversioned, versioned = runtimes
    # Check the unversioned layer
    assert unversioned.name == "cpython@3.11"
    assert not unversioned.versioned
    # Check the versioned layer
    assert versioned.name == "cpython@3.12"
    assert versioned.versioned


def test_future_warning_for_fully_versioned_name() -> None:
    expected_msg = (
        "Converting legacy.*'fully_versioned_name'.*'python_implementation'.*'runtime'"
    )
    with pytest.warns(FutureWarning, match=expected_msg):
        stack_spec = _load_stack_spec("warning_fully_versioned.toml")
    runtimes = list(stack_spec.all_environment_specs())
    assert len(runtimes) == 1
    (runtime,) = runtimes


def test_future_warning_for_build_requirements() -> None:
    # This actually emits the warning 3 times, but we don't check for that
    # (the fact the spec loads indicates the field is dropped for all layers)
    expected_msg = "Dropping legacy.*'build_requirements'.*'(runtime|fw|app)'"
    with pytest.warns(FutureWarning, match=expected_msg):
        stack_spec = _load_stack_spec("warning_build_requirements.toml")
    layers = list(stack_spec.all_environment_specs())
    assert len(layers) == 3
    for layer in layers:
        assert not hasattr(layer, "build_requirements")


EXPECTED_STACK_SPEC_ERRORS = {
    "error_inconsistent_runtimes.toml": "inconsistent frameworks",
    "error_inconsistent_app_indexes.toml": 'invalid.*inconsistent package index override.*index_overrides = {pytorch-cpu = "pytorch-cu128"}',
    "error_inconsistent_framework_indexes.toml": 'invalid.*inconsistent package index override.*index_overrides = {pytorch-cpu = "pytorch-cu128"}',
    "error_inconsistent_runtime_indexes.toml": 'invalid.*inconsistent package index override.*index_overrides = {pytorch-cpu = "pytorch-cu128"}',
    "error_invalid_requirement_syntax.toml": "invalid requirement syntax",
    "error_launch_support_conflict.toml": "'name'.*conflicts with.*'layer'",
    "error_layer_dep_C3_conflict.toml": "linearization failed.*['layerC', 'layerD'].*['layerD', 'layerC']",
    "error_layer_dep_cycle.toml": "unknown framework",
    "error_layer_dep_forward_reference.toml": "unknown framework",
    "error_missing_launch_module.toml": "launch module.*does not exist",
    "error_missing_support_modules.toml": "support modules do not exist",
    "error_support_modules_conflict.toml": "Conflicting support module names.*'layer'",
    "error_unknown_framework.toml": "unknown framework",
    "error_unknown_runtime.toml": "unknown runtime",
    "error_unknown_package_index.toml": "unknown package index",
    "error_unknown_priority_index.toml": "unknown package index",
}


def test_stack_spec_error_case_results_are_defined() -> None:
    # Ensure any new error cases that are added have expected errors defined
    spec_error_cases = sorted(p.name for p in TEST_SPEC_PATH.glob("error_*"))
    assert spec_error_cases == sorted(EXPECTED_STACK_SPEC_ERRORS)


@pytest.mark.parametrize("spec_fname", EXPECTED_STACK_SPEC_ERRORS)
def test_stack_spec_error_case(spec_fname: str) -> None:
    expected_match = EXPECTED_STACK_SPEC_ERRORS[spec_fname]
    with pytest.raises(LayerSpecError, match=expected_match):
        _load_stack_spec(spec_fname)


EXPECTED_LOCK_FAILURES = {
    "lock_failure_conflict_between_layers.toml": "Failed to lock layer 'framework-numpy'",
    "lock_failure_conflict_within_layer.toml": "Failed to lock layer 'cpython-3.11'",
}


@pytest.fixture
def temp_dir_path() -> Generator[Path, None, None]:
    with tempfile.TemporaryDirectory() as dir_name:
        yield Path(dir_name)


def test_lock_failure_case_results_are_defined() -> None:
    # Ensure any new op failure cases that are added have expected errors defined
    lock_failure_cases = sorted(p.name for p in TEST_SPEC_PATH.glob("lock_failure_*"))
    assert lock_failure_cases == sorted(EXPECTED_LOCK_FAILURES)


@pytest.mark.parametrize("spec_fname", EXPECTED_LOCK_FAILURES)
def test_lock_failure_case(temp_dir_path: Path, spec_fname: str) -> None:
    expected_match = EXPECTED_LOCK_FAILURES[spec_fname]
    with pytest.raises(LayerLockError, match=expected_match):
        stack_spec = _load_stack_spec(spec_fname, working_path=temp_dir_path)
        build_env = stack_spec.define_build_environment()
        build_env.lock_environments()
