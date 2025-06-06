"""Test loading assorted stack specifications."""

from pathlib import Path

import pytest

from venvstacks.stacks import LayerSpecError, StackSpec

##################################
# Stack spec loading test helpers
##################################


_THIS_PATH = Path(__file__)
TEST_SPEC_PATH = _THIS_PATH.parent / "stack_specs"


def _load_stack_spec(spec_name: str) -> StackSpec:
    """Load the named stack specification."""
    spec_path = TEST_SPEC_PATH / spec_name
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


EXPECTED_ERRORS = {
    "error_inconsistent_runtimes.toml": (LayerSpecError, "inconsistent frameworks"),
    "error_launch_support_conflict.toml": (
        LayerSpecError,
        "'name'.*conflicts with.*'layer'",
    ),
    "error_layer_dep_C3_conflict.toml": (
        LayerSpecError,
        "linearization failed.*['layerC', 'layerD'].*['layerD', 'layerC']",
    ),
    "error_layer_dep_cycle.toml": (LayerSpecError, "unknown framework"),
    "error_layer_dep_forward_reference.toml": (LayerSpecError, "unknown framework"),
    "error_missing_launch_module.toml": (
        LayerSpecError,
        "launch module.*does not exist",
    ),
    "error_missing_support_modules.toml": (
        LayerSpecError,
        "support modules do not exist",
    ),
    "error_support_modules_conflict.toml": (
        LayerSpecError,
        "Conflicting support module names.*'layer'",
    ),
    "error_unknown_framework.toml": (LayerSpecError, "unknown framework"),
    "error_unknown_runtime.toml": (LayerSpecError, "unknown runtime"),
}


def test_error_case_results_are_defined() -> None:
    # Ensure any new error cases that are added have expected errors defined
    defined_error_cases = sorted(p.name for p in TEST_SPEC_PATH.glob("error_*"))
    assert defined_error_cases == sorted(EXPECTED_ERRORS)


@pytest.mark.parametrize("spec_path", EXPECTED_ERRORS)
def test_stack_spec_error_case(spec_path: str) -> None:
    expected_exc, expected_match = EXPECTED_ERRORS[spec_path]
    with pytest.raises(expected_exc, match=expected_match):
        _load_stack_spec(spec_path)
