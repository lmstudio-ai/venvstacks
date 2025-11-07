Python layered environments test suite
======================================

Currently mostly a monolithic functional test suite checking that the `sample_project`
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

The slow tests are part of the test suite because the fast tests only
get to just over 60% coverage of `venvstacks.stacks` and less than
20% coverage of `venvstacks.pack_venv`. The combined fast coverage
on a single platform (Linux for these numbers) is just over 60%.

When the slow tests are included, even running on a single platform,
statement coverages rises to nearly 90% coverage of `venvstacks.stacks`,
nearly 70% coverage of `venvstacks.pack_venv`, and just under 90%
combined coverage across the test suite and package source code.

When the results across all platforms are combined, the overall
coverage of `venvstacks.stacks` doesn't improve much, but
`venvstacks.pack_venv` improves to more than 85%, and the overall
test coverage exceeds 90% (as of 0.1.0, CI checks for at least 92%
statement coverage).


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


Updating metadata for expected changes
--------------------------------------

There is an "update expected outputs" CI job that runs when the expected
sample project test output changes. While some changes (updates to the stack
specification, updates to the launch modules, updates to the code injected
into all built layers) are detected automatically, most are triggered by
modifying the `expected-output-config.toml` file with a comment noting the
reason for the update.

If this job triggers, it will check if the test suite passes aside from the
test cases that check the expected output for the sample project, and then
generate a PR against the triggering PR branch to adjust the expected output
under source control to match the actual output from the update job.

The trigger for this job is only checked when a PR is opened, so if it is
determined that an update is needed on an already open PR, the PR will need
to be closed and reopened to get the update job to trigger.

It is import to actually *review* the metadata updates in the generated PR.
In particular, large size changes in artifacts, or layer package summaries
unexpectedly listing packages as directly installed into the layer instead
of being inherited from lower layers are all signs that the difference may
be due to a bug in the PR rather than an intentional or otherwise
expected change.


Examining built artifacts
-------------------------

It's possible to build the sample project stack directly to help debug failures:

    $ cd /path/to/repo/
    $ pdm run venvstacks build --publish \
        tests/sample_project/venvstacks.toml ~/path/to/output/folder

(This assumes `pdm sync --dev` has been used to set up a local development venv).

Alternatively, the following CI export variables may be set locally to export metadata and
built artifacts from the running test suite:

    VENVSTACKS_EXPORT_TEST_ARTIFACTS="~/path/to/output/folder"
    VENVSTACKS_FORCE_TEST_EXPORT=1

The test suite can then be executed via `tox --m test -- -m "expected_output"`
(until Python 3.13, the generated metadata and artifacts should be identical
regardless of which version of Python is used to run `venvstacks`. This
ceased to be true in Python 3.14, as the standard library migrated to a new
zlib implementation with different output details).

If the forced export env var is not set or is set to the empty string, artifacts will only be
exported when test cases fail. Forcing exports can be useful for generating reference
artifacts and metadata when tests are passing locally but failing in pre-merge CI.

If the target export directory doesn't exist, the artifact exports will be skipped.

The `misc/export_test_artifacts.sh` script can be used to simplify the creation of
reference artifacts for debugging purposes.

CI jobs are also set up to export their test artifacts if the tests that check
against the expected output details fail. These archives can be downloaded
from the GitHub Actions details page for affected test runs.


Debugging test suite failures related to artifact reproducibility
-----------------------------------------------------------------

[`diffoscope`](https://pypi.org/project/diffoscope/) is a very helpful utility
to help track down artifact discrepancies when a code review of the
failing branch is unable to resolve the problem.

While it is only available for non-Windows systems, it can be used in WSL or
another non-Windows environment to examine artifacts produced on Windows.

To use `diffoscope` to debug CI failures:

1. run `misc/export_test_artifacts.sh` to generate an expected
   set of artifacts locally on the system of interest (using a known-good branch)
2. either download a set of artifacts from a failing CI job, or else run
   `misc/export_test_artifacts.sh` locally using a known-failing branch
3. on a `diffoscope` compatible system, compare the known-good artifacts to
   the unexpectedly different artifacts. This usually provides a good indication
   as to the nature of the problem causing the discrepancy (timestamps,
   unexpectedly included files, unexpectedly excluded files, etc).

(See the previous section for the underlying commands that would need to be
executed on Windows in order to do this in Powershell instead of a Windows
bash terminal)

Ad hoc stack operations
-----------------------

When the example stacks or the test cases that use full stack definitions
aren't behaving as expected, it can be useful to run up an interactive Python
prompt in the repository and use it to load and introspect a stack's behaviour.

For example, loading the ``mlx`` example stack:

```
~/devel/venvstacks$ pdm run python
Python 3.13.7 (main, Aug 14 2025, 00:00:00) [GCC 15.2.1 20250808 (Red Hat 15.2.1-1)] on linux
Type "help", "copyright", "credits" or "license" for more information.
>>> from venvstacks.stacks import StackSpec
... snip API stability warning ...
>>> stack = StackSpec.load("examples/mlx/venvstacks.toml")
>>> build_env = stack.define_build_environment()
>>> import json
>>> print(json.dumps(build_env.get_stack_status(), indent=2))
{
  "spec_name": "/home/acoghlan/devel/venvstacks/examples/mlx/venvstacks.toml",
  "runtimes": [
    {
      "name": "cpython3.11",
      "install_target": "cpython3.11",
      "has_valid_lock": true,
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    }
  ],
  "frameworks": [
    {
      "name": "framework-mlx",
      "install_target": "framework-mlx",
      "has_valid_lock": true,
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "name": "framework-mlx-cuda",
      "install_target": "framework-mlx-cuda",
      "has_valid_lock": true,
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    }
  ],
  "applications": [
    {
      "name": "app-mlx-example",
      "install_target": "app-mlx-example",
      "has_valid_lock": true,
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    },
    {
      "name": "app-mlx-example-cuda",
      "install_target": "app-mlx-example-cuda",
      "has_valid_lock": true,
      "selected_operations": [
        "lock-if-needed",
        "build",
        "publish"
      ]
    }
  ]
}
```
