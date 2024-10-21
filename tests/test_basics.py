"""Basic tests for venvstacks package components"""

from importlib.metadata import version as pkg_version

import pytest

from support import get_pinned_dev_packages


def test_python_api_import() -> None:
    from venvstacks import stacks

    assert hasattr(stacks, "StackSpec")


PINNED_DEV_PACKAGES = sorted(get_pinned_dev_packages().items())


@pytest.mark.parametrize("pkg_name,version", PINNED_DEV_PACKAGES)
def test_pinned_dev_packages(pkg_name: str, version: str) -> None:
    assert pkg_version(pkg_name) == version


# TODO: The assorted utility classes and functions added to stacks.py when it was
#       a mostly standalone script should be separated out and unit tested

# TODO: the sample project is intentionally well-formed, there should be test cases for the
#       assorted incorrect layer specs that the stack builder detects and rejects (e.g.
#       missing launch modules, applications depending on frameworks with inconsistent
#       runtime requirements)
