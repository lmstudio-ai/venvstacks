Python layered environments test suite
======================================

Currently mostly a monolothic functional test suite checking that the `sample_project`
folder builds as expected on all supported platforms.

Individual test cases can be written using either `pytest` or `unittest` based on which
makes the most sense for a given test case (managing the lifecycle of complex resources can
get confusing with `pytest`, so explicit class-based lifecycle management with `unittest`
may be easier in situations where `pytest` fixtures get annoying).

Regardless of the specific framework used, the convention for binary assertions that can be
written in either order is to use `assert actual == expected` (pytest) or
`self.assertEqual(actual, expected)` (unittest) such that the actual value is on the left
and the expected value is on the right.


Running checks locally
----------------------

Static analysis:

    tox -e lint,typecheck

Full test suite (py3.11 testing is also defined):

    tox -e py3.12

Skip slow tests (options after `--` are passed to `pytest`):

    tox -e py3.12 -- -m "not slow"

Specific tests (options after `--` are passed to `pytest`):

    tox -e py3.12 -- -k test_minimal_project

Refer to https://docs.pytest.org/en/6.2.x/usage.html#specifying-tests-selecting-tests for
additional details on how to select which tests to run.


Marking slow tests
------------------

Tests which take more than a few seconds to run should be marked as slow:

    @pytest.mark.slow
    def test_locking_and_publishing(self) -> None:
        ...


Updating metadata and examining built artifacts
-----------------------------------------------

To generate a full local build to update metadata or to debug failures:

    $ cd /path/to/repo/src/
    $ ../.venv/bin/python -m venvstacks build --publish ../tests/sample_project/venvstacks.toml ~/path/to/output/folder

(use `../.venv/Scripts/python` on Windows)

This assumes `pdm sync --no-self --dev` has been used to set up a local development venv.

Alternatively, the following CI export variables may be set locally to export metadata and
built artifacts from the running test suite:

    VENVSTACKS_EXPORT_TEST_ARTIFACTS="~/path/to/output/folder"
    VENVSTACKS_FORCE_TEST_EXPORT=1

The test suite can then be executed via `tox -e py3.11` or `tox -e py3.12` (the generated
metadata and artifacts should be identical regardless of which version of Python is used
to run `venvstacks`).

If the forced export env var is not set or is set to the empty string, artifacts will only be
exported when test cases fail. Forcing exports can be useful for generating reference
artifacts and metadata when tests are passing locally but failing in pre-merge CI.

The `misc/export_test_artifacts.sh` script can be used to simplify the creation of
reference artifacts for debugging purposes.


Debugging test suite failures related to artifact reproducibility
-----------------------------------------------------------------

`diffoscope` is a very helpful utility when trying to track down artifact discrepancies
(only available for non-Windows systems, but can be used in WSL or another Linux environment
to examine artifacts produced on Windows).
