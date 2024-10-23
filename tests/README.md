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

    tox -m static

Skip slow tests (`-m "not slow"` is passed to `pytest` by default):

    tox -m test

Full test run (options after `--` are passed to `pytest`):

    tox -m test -- -m ""

Specific tests (using `--` *replaces* the default `pytest` args):

    tox -m test -- -k test_minimal_project -m "not slow"

Refer to https://docs.pytest.org/en/stable/how-to/usage.html#specifying-which-tests-to-run
for additional details on how to select which tests to run.


Marking slow tests
------------------

Tests which take more than a few seconds to run should be marked as slow:

    @pytest.mark.slow
    def test_locking_and_publishing(self) -> None:
        ...


Marking tests with committed output files
-----------------------------------------

Some tests work by comparing freshly generated outputs with expected outputs
committed to the repository (usually locked requirements files and expected
artifact metadata files).

Tests which work this way must be marked as relying on expected outputs:

    @pytest.mark.slow
    @pytest.mark.expected_output
    def test_build_is_reproducible(self) -> None:
        ...


Updating metadata and examining built artifacts
-----------------------------------------------

To generate a full local sample project build to help debug failures:

    $ cd /path/to/repo/
    $ pdm run python -m venvstacks build --publish \
        tests/sample_project/venvstacks.toml ~/path/to/output/folder

This assumes `pdm sync --dev` has been used to set up a local development venv.

Alternatively, the following CI export variables may be set locally to export metadata and
built artifacts from the running test suite:

    VENVSTACKS_EXPORT_TEST_ARTIFACTS="~/path/to/output/folder"
    VENVSTACKS_FORCE_TEST_EXPORT=1

The test suite can then be executed via `tox --m test -- -m "expected_output"`
(the generated metadata and artifacts should be identical regardless of which
version of Python is used to run `venvstacks`).

If the forced export env var is not set or is set to the empty string, artifacts will only be
exported when test cases fail. Forcing exports can be useful for generating reference
artifacts and metadata when tests are passing locally but failing in pre-merge CI.

If the target export directory doesn't exist, the artifact exports will be skipped.

The `misc/export_test_artifacts.sh` script can be used to simplify the creation of
reference artifacts for debugging purposes.


Debugging test suite failures related to artifact reproducibility
-----------------------------------------------------------------

[`diffoscope`](https://pypi.org/project/diffoscope/) is a very helpful utility
when trying to track down artifact discrepancies.

While it is only available for non-Windows systems, it can be used in WSL or
another non-Windows environment to examine artifacts produced on Windows.
