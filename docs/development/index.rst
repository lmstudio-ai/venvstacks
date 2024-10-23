.. _dev-guide:

Development
===========

(With thanks to pip's `Getting Started`_ guide for the general structure here!)

This document aims to get you setup to work on venvstacks and to act as a guide
and reference to the development setup. If you face any issues during this
process, please `open an issue`_ about it on the issue tracker.


Get the source code
-------------------

To work on venvstacks, you first need to get the source code. The source code is
available on `GitHub`_.

.. code-block:: console

    $ git clone https://github.com/lmstudio/venvstacks
    $ cd venvstacks


Development Environment
-----------------------

In order to work on venvstacks, you need to install
:pypi:`pdm`, :pypi:`tox`, and :pypi:`tox-pdm`.

Given these tools, the default development environment can be set up
and other commands executed as described below.


Running from the source tree
----------------------------

To run venvstacks from your source tree during development, use pdm
to set up an editable install in the default venv:

.. code-block:: console

    $ pdm sync --dev

venvstacks can then be executed via the ``-m`` switch:

.. code-block:: console

    $ .venv/bin/venvstacks --help

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
    cover multiple lines, or )


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

There are also additional labels defined for running the oldest test environment,
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
closing and reopening the PR once the relevants fixes have been
implemented.


Building Documentation
----------------------

pip's documentation is built using :pypi:`Sphinx`. The documentation is written
in reStructuredText.

To build it locally, run:

.. code-block:: console

    $ tox -e docs

The built documentation can be found in the ``docs/_build`` folder.

.. _`Getting Started`: https://pip.pypa.io/en/stable/development/getting-started/
.. _`open an issue`: https://github.com/lmstudio/venvstacks/issues/new?title=Trouble+with+development+environment
.. _`rich CLI`: https://docs.pytest.org/en/stable/how-to/usage.html#specifying-which-tests-to-run
.. _`GitHub`: https://github.com/lmstudio/venvstacks
.. _`testing README file`: https://github.com/lmstudio-ai/venvstacks/blob/main/tests/README.md
