"""Test loading assorted stack specifications."""

from pathlib import Path

import pytest

from venvstacks.stacks import StackSpec

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


# TODO: the sample project is intentionally well-formed, there should be additional
#       test cases for the assorted incorrect layer specs that StackSpec rejects (e.g.
#       missing launch modules, applications depending on frameworks with inconsistent
#       runtime requirements)
