.. _dev-guide:

-----------
Development
-----------

.. meta::
   :og:title: venvstacks Development - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/development/
   :og:description: venvstacks Developer Guide - venvstacks Documentation


Getting Started
===============

(With thanks to pip's `Getting Started`_ guide for the general structure here!)

This document aims to get you setup to work on venvstacks and to act as a guide
and reference to the development setup. If you face any issues during this
process, please :issue:`open an issue <new?title=Trouble+with+development+environment>`
about it on the issue tracker.


Get the source code
-------------------

To work on venvstacks, you first need to get the source code. The source code is
available on `GitHub`_.

.. code-block:: console

    $ git clone https://github.com/lmstudio-ai/venvstacks
    $ cd venvstacks


Development Environment
-----------------------

In order to work on venvstacks, you need to install
:pypi:`pdm`, :pypi:`tox`, :pypi:`tox-pdm`, and :pypi:`scriv`
(everything else can be executed via ``tox`` environments).

Given these tools, the default development environment can be set up
and other commands executed as described below.


Running from the source tree
----------------------------

To run venvstacks from your source tree during development, use pdm
to set up an editable install in the default venv:

.. code-block:: console

    $ pdm sync --dev

venvstacks can then be executed with ``pdm run``:

.. code-block:: console

    $ pdm run venvstacks --help

     Usage: venvstacks [OPTIONS] COMMAND [ARGS]...

     Lock, build, and publish Python virtual environment stacks.

    ╭─ Options ───────────────────────────────────────────────────────────────────────╮
    │ --help          Show this message and exit.                                     │
    ╰─────────────────────────────────────────────────────────────────────────────────╯
    ╭─ Commands ──────────────────────────────────────────────────────────────────────╮
    │ build          Build (/lock/publish) Python virtual environment stacks.         │
    │ local-export   Export layer environments for Python virtual environment stacks. │
    │ lock           Lock layer requirements for Python virtual environment stacks.   │
    │ publish        Publish layer archives for Python virtual environment stacks.    │
    ╰─────────────────────────────────────────────────────────────────────────────────╯


Building Documentation
----------------------

pip's documentation is built using :pypi:`Sphinx`. The documentation is written
in reStructuredText.

To build it locally, run:

.. code-block:: console

    $ tox -e docs

The built documentation can be found in the ``docs/_build`` folder.


Changelog Entries
-----------------

The ``venvstacks`` changelog is managed with :pypi:`scriv`.

All changes which may affect ``venvstacks`` users should be
given a user facing changelog entry with ``scriv create``.

Entries are written in ``.rst`` format by default, so they
can use semantic references to the rest of the documentation.
However, ``.md`` fragments are entirely fine if internal
semantic links aren't needed.

Refer to the
`"per-user" settings <https://scriv.readthedocs.io/en/1.5.1/configuration.html#per-user-git-settings>`__
in the ``scriv`` documentation for details on how to customise the
local behaviour of ``scriv create``.

The project level ``scriv`` settings are stored in
``pyproject.toml`` (but the project largely relies on the default
settings)


Automated Testing
=================

Code consistency checks
-----------------------

The project source code is autoformatted and linted using :pypi:`ruff`.
It also uses :pypi:`mypy` in strict mode to statically check that Python APIs
are being accessed as expected.

All of these commands can be invoked via tox:

.. code-block:: console

    $ tox -e format

.. code-block:: console

    $ tox -e lint

.. code-block:: console

    $ tox -e typecheck

.. note::

    Avoid using ``# noqa`` comments to suppress these warnings - wherever
    possible, warnings should be fixed instead. ``# noqa`` comments are
    reserved for rare cases where the recommended style causes severe
    readability problems, and there isn't a more explicit mechanism
    (such as ``typing.cast``) to indicate which check is being skipped.

    ``# fmt: off/on`` and ``# fmt: skip`` comments may be used as needed
    when the autoformatter makes readability worse instead of better
    (for example, collapsing lists to a single line when they intentionally
    cover multiple lines, or breaking alignment of end-of-line comments).


Running tests locally
---------------------

The project's tests are written using the :pypi:`pytest` test framework and the
standard library's :mod:`unittest` module. :pypi:`tox` is used to automate the
setup and execution of these tests across multiple Python versions.

Some of the tests build and deploy full environment stacks, which makes them
take a long time to run (5+ minutes for the sample project build and export,
even with fully cached dependencies).

Local test runs skip these slow tests by default, but they can be specifically
requested by overriding the default positional arguments in the ``tox`` command.

For example, this will run *just* the slow tests using the default testing
environment:

.. code-block:: console

    $ tox -m test -- -m "slow"

The example above runs tests against the default Python version configured in
``tox.ini``. You can also use other defined versions by specifying the target
environment directly:

.. code-block:: console

    $ tox -e py3.11

There are additional labels defined for running the oldest test environment,
the latest test environment, and all test environments:

.. code-block:: console

    $ tox -m test_oldest
    $ tox -m test_latest
    $ tox -m test_all

``tox`` has been configured to forward any additional arguments it is given to
``pytest`` (as shown in the slow test example).
This enables the use of pytest's `rich CLI`_.
In particular, you can select tests using all the options that pytest provides:

.. code-block:: console

    $ # Using file name
    $ tox -m test -- tests/test_basics.py
    $ # Using markers
    $ tox -m test -- -m "slow"
    $ # Using keyword text search
    $ tox -m test -- -k "lock and not publish"

Keep in mind when doing this that the arguments given will *replace* the
default ``-m "not slow"`` test marker filtering, so remember to include
that explicitly when it is still desired.

Additional notes on running and updating the tests can be found in the
`testing README file`_.


Tests with committed expected output
''''''''''''''''''''''''''''''''''''

The "sample project" test cases primarily work by checking that relocking and
rebuilding the sample project produces the same locked requirements
files and the same publication metadata.

This means those test cases will fail when the expected output is changed
intentionally, such as choosing a new baseline date for the sample project
lockfiles, adding new fields to the expected metadata, or changing the
expected contents of the defined environment layers.

PRs that modify the ``tests/expected-output-config.yml`` file will trigger
a GitHub workflows that checks all other tests pass, and then generates a
new PR targeting the triggering PR branch. The changes to the expected
output files can then be reviewed to confirm they match the expected
impact of the changes that were (for example, launch module changes
should only affect the hashes and sizes of the application layer
archives that include those launch modules).

If the original PR is not correct, then it can be retriggered by
closing and reopening the PR once the relevant fixes have been
implemented.


Project Management
==================

The project is primarily managed with ``pdm``, together with some additional
supporting scripts.

To update the locked CI dependencies, run the ``./lock_dev_venv.sh`` script in
root of the repository. In addition to updating ``pdm``'s lockfile, this also
runs the export processes for the flat constraints files used when installing
packages with something other than ``pdm``, as well as the flat requirements
file used for the documentation build process.

In some cases, dependency entries in ``pyproject.toml`` may need to be updated
without needing to update the locked CI dependencies (for example, adding a
minimum version requirement that is lower than the already locked version).
When this is the case, the expected input requirements hash in ``pdm.lock`` can
be updated with the command ``pdm lock --dev --update-reuse``. If this makes
any actual changes to the pinned dependencies, then the relevant exported files
can be updated with ``./lock_dev_venv.sh --skip-lock``.

Note: While ``uv`` is used as a runtime dependency of ``venvstacks`` to lock
and build the defined layers, it is *not* used as the project management tool
for the project itself.


Release Management
==================

.. _version-numbering:

Version Numbering
-----------------

Until the Python API has stabilised, ``venvstacks`` is using
`ZeroVer <https://0ver.org/>`__ (starting from 0.1.0).

The versioning scheme to be used after the leading zero is
dropped has not yet been decided (see
:external+packaging:ref:`versioning`
for some of the options being considered).

Except for when a release is being prepared, the nominal version on
``main`` will have ``.dev0`` appended to indicate it is not a
release build.

Most releases are expected to be published directly without a prior
release candidate build, but one may be used if it is deemed
necessary (for example, ``0.1.0rc1`` was published in order to
test the release pipeline prior to publishing ``0.1.0``).


Preparing New Releases
----------------------

Prior to release:

* Update the version in ``pyproject.toml`` to remove the pre-release suffix
* Run ``scriv collect`` to update ``CHANGELOG.rst``
* Review and edit the contents of ``CHANGELOG.rst``, including updating the
  Sphinx anchor labels as appropriate for the release
* Commit and push the updated version number and collected change log updates
* Check the updated docs after the PR has been merged

Release (requires ``pandoc`` and a GitHub access token with release permissions):

* Use `misc/tag-release.sh`_ to create an annotated tag for the current version
* Push the tag to the remote repo
* Run ``scriv github-release --dry-run`` to check what would be published
* Run ``scriv github-release`` to make the release from the annotated tag
  (alternatively: create the GitHub release interactively in the web UI,
  using the debug output from the ``scriv`` dry run as a starting point for
  the GitHub release notes)

After release:

* Check the release-triggered GitHub Action has published to PyPI correctly
* Bump the version in ``pyproject.toml`` and add a ``.dev0`` suffix

.. _`Getting Started`: https://pip.pypa.io/en/stable/development/getting-started/
.. _`rich CLI`: https://docs.pytest.org/en/stable/how-to/usage.html#specifying-which-tests-to-run
.. _`GitHub`: https://github.com/lmstudio-ai/venvstacks
.. _`testing README file`: https://github.com/lmstudio-ai/venvstacks/blob/main/tests/README.md
.. _`misc/tag-release.sh`: https://github.com/lmstudio-ai/venvstacks/blob/main/misc/tag-release.sh
