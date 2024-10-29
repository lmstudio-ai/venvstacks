----------------------------------
Layered Virtual Environment Stacks
----------------------------------

``venvstacks`` uses Python's ``sitecustomize.py`` environment setup feature
to chain together three layers of Python virtual environments:

* "Runtime" layers: environments containing the desired version of a specific Python interpreter
* "Framework" layers: environments containing desired versions of key Python frameworks
* "Application" layers: environments containing components to be launched directly

While the layers are archived and published separately, their dependency locking is integrated,
allowing the application layers to share dependencies installed in the framework layers,
and the framework layers to share dependencies installed in the runtime layers.


Installing
==========

``venvstacks`` is available from the :pypi:`Python Package Index <venvstacks>`,
and can be installed with :pypi:`pipx` (or similar tools):

.. code-block:: console

   $ pipx install venvstacks

Alternatively, it can be installed as a user level package (although this may
make future Python version upgrades more irritating):

.. code-block:: console

   $ pip install --user venvstacks

The command line help also provides additional usage information:

.. code-block:: console

   $ venvstacks --help

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

.. note::

   The ``venvstacks`` command is currently only available via the Python interpreter's
   :py:option:`-m` switch, so Python command execution utilities like ``pipx run``
   and ``uvx`` don't work yet.
   However, direct execution as ``venvstacks`` is expected to be
   :issue:`supported in a future release <26>`.


Working with environment stacks
===============================

Defining environment stacks
---------------------------

The environment layers to be published are defined in a ``venvstacks.toml`` stack specification,
with a separate array of tables for each kind of layer definition.

For example, the following specification defines a pair of applications which use
`scikit-learn <https://scikit-learn.org/>`__` as a shared framework layer with
`numpy <https://numpy.org/>`__ preinstalled in the runtime layer,
all running in a controlled Python 3.11 base runtime:

.. code-block:: toml

   [[runtimes]]
   name = "cpython@3.11"
   fully_versioned_name = "cpython@3.11.10"
   requirements = [
       "numpy",
   ]

   [[frameworks]]
   name = "sklearn"
   runtime = "cpython@3.11"
   requirements = [
       "scikit-learn",
   ]

   [[applications]]
   name = "classification-demo"
   launch_module = "launch_modules/sklearn_classification.py"
   frameworks = ["sklearn"]
   requirements = [
       "scikit-learn",
   ]

   [[applications]]
   name = "clustering-demo"
   launch_module = "launch_modules/sklearn_clustering.py"
   frameworks = ["sklearn"]
   requirements = [
       "scikit-learn",
   ]

Locking environment stacks
--------------------------

.. code-block:: console

   $ venvstacks lock sklearn_demo/venvstacks.toml

The ``lock`` subcommand takes the defined layer requirements from the specification,
and uses them to perform a complete combined resolution of all of the environment stacks
that ensures the different layers can be published separately,
but still work as expected when deployed to a target system.

The locking mechanism is defined such that only changes to modules a given layer
uses from lower layers affect them,
rather than upper layers needing to be rebuilt for *every* change to a lower layer.

Building environment stacks
---------------------------

.. code-block:: console

   $ venvstacks build sklearn_demo/venvstacks.toml

The ``build`` subcommand performs the step of converting the layer specifications
and their locked requirements into a working Python environment
(either a base runtime environment,
or a layered virtual environment based on one of the defined runtime environments).
If the environments have not already been explicitly locked,
the build step will lock them as necessary.

This command is also a "build pipeline" command that allows locking, building,
and publishing to be performed in a single step (see the command line help for details).

Publishing environment layer archives
-------------------------------------

.. code-block:: console

   $ venvstacks publish --tag-outputs --output-dir demo_artifacts sklearn_demo/venvstacks.toml

Once the environments have been successfully built,
the ``publish`` command allows each layer to be converted to a separate
`reproducible <https://reproducible-builds.org/>`__` binary archive suitable
for transferring to another system, unpacking, and using the unpacked environments
to run the included applications (needing only a small post-installation step using
a Python script embedded in the built layer archives to correctly relink the deployed
environments with each other in their deployed location on the target system).

Metadata regarding the layer definitions and the published artifacts is published
alongside the published archives (to ``demo_artifacts/__venvstacks__/`` in the given example).
This metadata captures both input details (such as the hashes of the locked requirements
and the included launch modules) and output details
(such as the exact size and exact hash of the built layer archive).

Locally exporting environment stacks
------------------------------------

.. code-block:: console

   $ venvstacks local-export --output-dir demo_export sklearn_demo/venvstacks.toml 

Given that even considering the use of ``venvstacks`` implies that some layer archives may be of
significant size (a fully built `pytorch` archive weighs in at multiple gigabytes, for example),
packing and unpacking the layer archives can take a substantial amount of time.

To avoid that overhead when iterating on layer definitions and launch module details,
the ``local-export`` subcommand allows the built environments to be copied to a different
location on the same system, with most of the same filtering steps applied as would be
applied when performing the archive pack-and-unpack steps (the omissions are details
related to reproducible builds, like clamping the maximum file modification times to known values).

Locally exporting environments produces much of the same metadata as publishing layer archives,
but the details related specifically to the published archive (such as its size and expected
contents hash) are necessarily omitted.

Contributing to ``venvstacks`` development
==========================================

``venvstacks`` is MIT Licensed and `developed on GitHub <https://github.com/lmstudio-ai/venvstacks>`__.

If you have a suitable use case,
the easiest way to contribute to ``venvstacks`` development is just to try it out,
and let us know how that goes. What did you like, what did you dislike, what just plain broke?

If anything does break,
then please `open an issue <https://github.com/lmstudio-ai/venvstacks/issues>`__
(if the problem hasn't already been reported).
If you're not sure if some behaviour is a bug or not,
or would just like to provide general feedback rather than file specific issues or suggestions,
the following Discord channels are the best way to get directly in touch with the developers:

* Discuss ``venvstacks`` in general in the ``#venvstacks`` channel on the
  `PyPA Discord Server <https://discord.com/invite/pypa>`__.
* Discuss the use of ``venvstacks`` in LM Studio in the ``#dev-chat`` channel on the
  `LM Studio Discord Server <https://discord.gg/rDk28gC7nv>`__.

The `"Packaging" category <https://discuss.python.org/c/packaging/14>`__ on
`discuss.python.org <https://discuss.python.org/>`__ is also a reasonable place to provide feedback.

For additional information, consult the :ref:`developer documentation <dev-guide>`
