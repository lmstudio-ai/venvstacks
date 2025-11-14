---------------------
Concepts of Operation
---------------------

.. meta::
   :og:title: venvstacks Concepts - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/concepts/
   :og:description: venvstacks Concepts of Operation - venvstacks Documentation

Expected Usage Model
====================

``venvstacks`` is designed to decompose Python dependency trees into separately
deployable and updatable :term:`layers <layer>`, without having to distribute
either individual package archives, or entire monolithic application execution
environments.

This process starts with a :term:`stack definition` file, conventionally
named ``venvstacks.toml`` (and sometimes referred to as a stack specification).
The exact format of this file is described in :ref:`stack-specification-format`,
but the key aspect for understanding the expected usage model is that it is used
to define multiple stack :term:`layers <layer>`, broken down into the following
categories:

* Runtimes: Python runtimes used as the basis for other environment layers
* Frameworks: common Python packages used across multiple applications
* Applications: Python modules and packages to implement specific functionality

Each application layer may depend (directly or indirectly) on multiple framework
layers, but will always depend on exactly one runtime layer. Similarly, each
framework layer will depend on exactly one runtime layer, but may also depend
on other framework layers.

As forward references to subsequently defined layers are NOT permitted, the
declaration of dependencies between layers forms a directed acyclic graph of
separately deployable components.

Stack definition & deployment flow
----------------------------------

The overall process for defining, building, and deploying environment stacks is
as follows:

* Define environment stack in `venvstacks.toml`

  * ⮩ `venvstacks lock ...` 🠪 locked layer requirements & metadata files

    * ⮩ `venvstacks build ...` 🠪 built layer environments with installed packages

      * ⮩ `venvstacks local-export ...` 🠪 locally deployed environments
      * ⮩ `venvstacks publish ...` 🠪 layer archives & metadata files

        * ⮩ (use case dependent layer archive distribution mechanism)

          * ⮩ (deploy layer archives - unpack and run post-installation scripts)

            *  ⮩ remotely deployed environments

The :ref:`overview` provides examples of executing the listed commands,
while the sections below go into more detail regarding each of the steps.

The :ref:`example-stacks` shows gives a number of example stacks illustrating
various features that stack definitions support.

The :ref:`stack-specification-format` format page provides details of the
layer specification format to be used in a stack definition file, as well
as some information on the fields that are included in the layer lock,
published artifact, and deployed environment metadata files.

Locking layer dependencies
--------------------------

The layer specifications only declare the top-level packages that are to be
available when using that layer. If these requirements were used directly
to build the environments, the exact set of packages installed would potentially
vary depending on exactly when and where the layer was built.

Instead, ``uv`` is used to resolve the declared set of dependencies, generating
a lock file that describes the full transitive dependency tree for that layer.
By default, these layer lock files are stored in a ``requirements`` folder
adjacent to the stack definition file.

The layer lock files use the standardised
`Python packaging lock format <https://packaging.python.org/en/latest/specifications/pylock-toml/>`__
(more commonly known as the ``pylock.toml`` format). The lock file contents
are adjusted such that only installation from binary packages is permitted,
and so upper layers don't attempt to install packages that will be provided
at runtime by lower layers.

Alongside each layer lock file, the locking step also generates a layer lock
metadata file. This metadata file records the combined hash of the transitively
locked requirement set, together with three separate input hashes:

* Requirements: a combined hash of the declared dependencies for the layer
* Other validity inputs: a combined hash of other inputs that affect whether
  or not the previously generated layer lock is still considered valid
  (for example, the runtime Python version, the target Linux libc version, or
  the target macOS version)
* Layer version inputs: a combined hash of other inputs that affect whether or
  not the layer version should be updated for implicitly versioned layers
  (for example, the name and content hash of the launch module in app layers)

An easier to read summary of the included
packages and their versions and summaries is generated alongside each layer
lock file. These summary files also list which packages are expected to
be imported from lower layers rather than being included directly in the
layer's own environment.

As the layer lock files are cross-platform, the entire stack can be locked
anywhere, and the resulting lock files committed to source control alongside
the stack definition file, ready to be built. The :ref:`example-stacks` page
includes links to the version control folders containing the generated layer
lock files, layer lock metadata files, and layer package summaries for
each example stack.

.. versionchanged:: 0.8.0

   Layer lock files are now cross-platform (using the ``pylock.toml`` format)
   and only need to be locked once on any supported platform.
   Previous versions needed to be locked separately on each platform, and
   emitted separate per-layer ``requirements.txt`` files for each platform
   (:ref:`release details <changelog-0.8.0>`).

Building layer environments
---------------------------

The locking step defines which Python packages will be installed into each
environment. The build step actually creates those environments and installs
the specified packages. As the build step runs some post-installation checks
inside the built environments, it must be executed separately on
each target platform (cross-builds are not currently supported).

Building an environment primarily consists of creating it with the standard
library's ``venv`` module, and then installing the specified packages with
``uv pip compile``. However, some additional adjustments are also made:

* a ``sitecustomize.py`` file is injected into the layer's ``site-packages``
  folder that allows code running in the build environment to import packages
  from the build environments of the layers that it depends on.
* a ``share/venv/metadata/venvstacks_layer.json`` file is injected with details
  about the environment, including the expected relative location of its
  runtime layer and the other layers that it depends on
* a top level ``postinstall.py`` script is injected that allows the creation of
  suitable ``pyvenv.cfg`` and ``sitecustomize.py`` files (based on the contents
  of ``venvstacks_layer.json``) after an environment has been locally exported
  or deployed from a published artifact. The ``pyvenv.cfg`` and
  ``sitecustomize.py`` files used at build time are NOT included when exporting
  or publishing the layer
* on Linux and macOS, the environment is scanned for dynamic libraries as
  described in :ref:`dynamic-linking`, and the symlink to the base Python
  executable potentially replaced with a wrapper script that ensures the
  dynamic libraries from lower layers are available at runtime

Locally exporting layers
------------------------

When iterating on new layer definitions (especially application layers that
directly include complex launch modules rather than developing them as
installable Python packages), it is inconvenient to go through the full
layer publishing and installation process in order to confirm that an
environment is working as expected.

The local export command handles this use case by combining the artifact
publication input filtering step with a local directory copy and execution
of the ``postinstall.py`` environment setup script in the exported environment.

.. _publishing-archives:

Publishing layer archives
-------------------------

Once the stack layers have been locked and built, they may then be published
as distributable layer archives. Depending on the use case, separate layer
specifications may be used for different platforms, with the target platform
information being encoded directly into the layer names, or else common layer
specifications may be used across platforms, with the ``--tag-outputs``
option to the publication command being used to automatically add the
relevant target platform compatibility tag to each built artifact.

As part of the publication process, metadata files describing each artifact
(including the other layers it expects to have available when deployed) are
emitted alongside the generated artifacts. A combined metadata file
describing all of the layers in the entire stack specification is also
published.

These published layer archives are expected to be
`reproducible <https://reproducible-builds.org/>`__: if the same
stack definition is built again later with the same
`build environment <https://reproducible-builds.org/docs/perimeter/>`__,
then the resulting layer archives will be byte-for-byte identical with
those produced by the original stack build.

In general, keeping the versions of ``venvstacks``, ``uv``, and
``pbs-installer`` consistent should produce consistent output artifacts.
Note that changing the Python runtime used to create the layer archives *may*
change the exact archive structure (and hence the artifact hashes) if the
standard library's archiving implementation changes (for example, CPython 3.14
switched to ``zlib-ng`` on Windows, which means most archives generated for
Windows layers will be smaller than previous versions when generated on
CPython 3.14 or later)

The 
`expected manifests <https://github.com/lmstudio-ai/venvstacks/tree/main/tests/sample_project/expected_manifests>`__
for the test suite's sample project provide an example of these artifact
metadata files (they are included in source control as part of a test case that
ensures relocking, rebuilding, and republishing the sample project only changes
the generated files and artifacts when intending to do so).

Distributing layer archives to target platforms
-----------------------------------------------

As ``venvstacks`` is designed to build Python stacks for embedding in larger
applications, it doesn't make any assumptions regarding the distribution
mechanism used to upload the layer archives and their metadata, nor the
mechanism used to determine which archives to download and install at
runtime.

The published metadata files contain sufficient information to allow these
selections to be made dynamically based on the information recorded there,
but it may also make sense in some use cases for the embedding application to
be tightly coupled to the defined set of available layers and maintain its
own records of which layers should be installed on each target platform for
various purposes.

Deploying layer archives
------------------------

Once layer archives have been downloaded to the relevant target platform,
they need to be unpacked and then configured using their included
post-installation scripts.

To run an application from an application layer:

* the application layer and the layers it depends must all be unpacked into a
  common destination directory on the target system
* starting from the runtime layer, the post-installation scripts for each
  deployed environment must be executed to ensure it is ready to run from its
  deployed location
* once all of the environments in the stack have been installed, the
  application may be executed from the application environment use the Python
  interpeter's ``-m`` switch with the name of the layer's launch module

The general process for running the post-installation script when unpacking
each layer is to:

* Read the layer config from ``{env_path}share/venv/metadata/venvstacks_layer.json``
* Resolve ``base_python`` from the layer config relative to the environment folder
* Use that resolved path to run ``{base_python_path} {env_path}/postinstall.py``

Using the general process avoids having to directly account for the differences
in virtual environment layouts across operating systems (for example, Windows
virtual environments contain a ``Scripts/python.exe`` stub executable, while
POSIX virtual environments contain a ``bin/python`` symlink or wrapper script.
Base runtime environments may not necessarily put the Python executable in
either of those locations)

Executing deployed applications
-------------------------------

The general process to running the launch module for application layers is to:

* Read the layer config from ``{env_path}share/venv/metadata/venvstacks_layer.json``
* Read ``launch_module`` from the layer config
* Resolve ``python`` from the layer config relative to the environment folder
* Use that resolved path to run ``{python_path} -m {launch_module}``
  (potentially with CLI arguments, depending on the use case)

As for running the post-installation scripts, using the general process avoids
having to directly account for the differences in virtual environment layouts
across operating systems.

Reading the launch module name from the configuration means avoids tightly
coupling the software running the deployed stack to the exact launch module
name used in the layer definition.
