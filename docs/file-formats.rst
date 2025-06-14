
.. _stack-specification-format:

------------------------------
Environment Stack File Formats
------------------------------

.. meta::
   :og:title: venvstacks File Formats - venvstacks Documentation
   :og:type: website
   :og:url: https://venvstacks.lmstudio.ai/stack-format/
   :og:description: venvstacks Specification and Metadata File Formats - venvstacks Documentation

File naming and formats
=======================

By convention, virtual environment stacks are specified in a file named ``venvstacks.toml``.

The default output folder for layer metadata when publishing artifacts and locally exporting
environments is called ``__venvstacks__``. The platform-specific layer summary metadata
files are called ``venvstacks.json`` and each is written to a folder named after the target
platform in the parent metadata folder. The per-layer metadata files are written to an
``env_metadata`` folder within the platform folders.
Refer to :ref:`layer-metadata` for additional details.

The layer configuration metadata within deployed environments is written to
``share/venv/metadata/venvstacks_layer.json``.
Refer to :ref:`deployed-layer-config` for additional details.

All human-edited input files are written using `TOML <https://toml.io/>`__, as this is a file
format that combines the runtime simplicity and Unicode text compatibility of JSON with the
line-oriented human friendliness of the classic ``.ini`` format. It is the same config file
syntax used to define ``pyproject.toml`` when
:external+packaging:ref:`publishing Python packages <writing-pyproject-toml>`.

All output metadata files generated by the build process are emitted as `JSON <https://www.json.org/>`__.

Defining virtual environment stacks
===================================

Virtual environment stacks are defined using the following top-level fields, which are all TOML
:toml:`arrays of tables <array-of-tables>`:

* ``[[runtimes]]``
* ``[[frameworks]]``
* ``[[applications]]``

Common layer specification fields
---------------------------------

All layer specifications must contain the following two fields:

* ``name`` (:toml:`string`): the name of the layer being specified
* ``requirements`` (:toml:`array` of :toml:`strings <string>`):
  the top-level Python distribution packages to be installed as part of this layer.
  Dependencies are declared using the standard Python
  :external+packaging:ref:`dependency specifier <dependency-specifiers>` format.
  These declared dependencies will be transitively locked when locking the layer.
  The list of requirements must be present, but is permitted to be empty.

While there are no formal restrictions on the symbols permitted in layer names,
the ``@`` symbol is used to separate the layer name from the lock version for
implicitly versioned layers, so using it as part of a layer name may cause
confusion when attempting to determine whether a published artifact or
exported environment is using implicit lock versioning or is referring
to an external version number.

All layer specifications may also contain the following optional fields:

* ``platforms`` (:toml:`array` of :toml:`strings <string>`):
  by default, all layers are built for all target platforms. Setting this field
  allows the layer build to be narrowed to a subset of the supported targets.
  Setting this field to an empty list also allows a layer build to be disabled
  without having to delete it entirely.
  Permitted entries in the ``platforms`` list are:

  * ``"win_amd64"``: Windows on x86-64
  * ``"win_arm64"``: Windows on ARM64/Aarch64 (not currently tested in CI)
  * ``"linux_x86_64"``: Linux on x86_64
  * ``"linux_aarch64"``: Linux on ARM64/Aarch64 (not currently tested in CI)
  * ``"macosx_arm64"``: macOS on Apple (ARM64/Aarch64) silicon
  * ``"macosx_x86_64"``: macOS on Intel silicon (not currently tested in CI)

  .. versionchanged:: 0.3.0
     Added ``win_arm64`` and ``linux_aarch64`` as permitted target platforms
     (:ref:`release details <changelog-0.3.0>`).

* ``dynlib_exclude`` (:toml:`array` of :toml:`strings <string>`):
  by default, dynamic library (also known as shared object) files on Linux
  and macOS that do not appear to be Python extension modules will be symbolically
  linked from a ``share/venv/dynlib/`` folder within the virtual environment
  (see :ref:`dynamic-linking` for additional details).
  Setting this field allows files to be excluded from the linking process based
  on filename glob patterns. These patterns are checked against the *end* of the
  full path to the files using the equivalent of :func:`glob.translate`.

  .. versionadded:: 0.4.0
     Added support for dynamic linking across layers on Linux and macOS
     (:ref:`release details <changelog-0.4.0>`).

* ``versioned`` (:toml:`boolean`): by default, and when this setting is ``false``,
  the layer is considered unversioned (even if an ``@`` symbol appears in the
  layer name). The layer metadata will always report the lock version for these
  layers as ``1`` and the lock version is never implicitly included when deriving
  other names from the layer name.
  When this setting is ``true``, the layer is implicitly versioned.
  For implicitly versioned layers, a lock version number is stored as part of
  the environment lock metadata, and automatically incremented when the
  environment lock file changes as the result of a layer locking request.
  The layer metadata will report the saved lock version for implicitly versioned
  layers and this value is automatically included when deriving some other names
  from the layer name.

This means the following layer versioning styles are supported:

* *unversioned*: layer name uses a format like ``my-app`` with ``versioned``
  omitted or set to ``false``. Dependencies from other layers (if any) refer to
  the unversioned layer name. Only the latest version of an unversioned
  layer can be built and published, and only one version can be installed
  on any given target system. :ref:`Artifact tagging <layer-metadata>` allows
  multiple versions of unversioned layers to still be distributed in parallel.
  The advantage of unversioned layers is that they allow for low impact security
  updates, where upper layers only need to be rebuilt if they actually depended
  on an updated component.

* *implicitly versioned*: layer name uses a format like ``scipy`` with ``versioned``
  set to ``true``. Dependencies from other layers refer to the unversioned layer name,
  and are automatically updated to depend on the new version of the lower layer when
  the locked requirements change. Some component names derived from the layer name
  will be implicitly rewritten to use ``"{layer_name}@{lock_version}"`` rather than
  using the layer name on its own. Only the latest version of an implicitly versioned
  layer can be built and published, but different versions can be installed in
  parallel on target systems.
  Implicitly versioned layers lose support for low impact security updates (all
  upper layers must be rebuilt for any change to the implicitly versioned lower
  layer), but gain support for parallel installation of multiple versions on
  target systems.

* *externally versioned*: layer name uses a format like ``cpython-3.12``, where
  the external layer "version" is considered part of the layer name.
  Dependencies from other layers must refer to the specific version.
  External versioning allows upper layers to depend on different versions of
  the "same" lower layer, but also requires those layers to be explicitly
  migrated to new versions of the lower layer.
  External versioning always allows multiple versions of the "same" layer to be
  built and published in parallel.
  By default, externally versioned layers are handled in the same way as
  unversioned layers, but external versioning in the layer name may also be
  freely combined with implicit lock versioning in the derived names by
  setting ``versioned`` to ``true``.

Refer to :ref:`layer-names` for additional details on how layer names are used
when building virtual environment stacks.

.. _runtime-layer-spec:

Runtime layer specification fields
----------------------------------

Runtime layer specifications must contain the following additional field:

* ``python_implementation`` (:toml:`string`): the :pypi:`pbs-installer` name
  of the Python runtime to be installed as the base runtime for this layer
  (and any upper layers that depend on this layer). Implementation names
  use the format ``{implementation_name}@{implementation_version}``
  (for example, ``cpython@3.12.7``).

.. _framework-layer-spec:

Framework layer specification fields
------------------------------------

Framework layer specifications must contain one of the following additional fields
(but not both):

* ``runtime`` (:toml:`string`): the name of the runtime layer that this framework layer uses.
* ``frameworks`` (:toml:`array` of :toml:`strings <string>`):
  the names of the other framework layers that this framework layer depends on.

When a framework layer declares a dependency on other framework layers, the ``runtime``
dependency for this layer is not specified directly. Instead, all of the declared
framework dependencies *must* depend on the same runtime layer, and that base
runtime also becomes the base runtime for this framework layer. In order to
support this runtime inference step, and to prevent the declaration of circular
dependencies between layers, forward references are *not* supported (in other
words, layers must be declared *after* the layers they depend on).

Whether the runtime is specified directly or indirectly, the ``install_target``
and ``python_implementation`` attributes of the runtime layer are respectively recorded
in the ``runtime_layer`` and ``python_implementation`` fields of the framework layer's
output metadata.

``bound_to_implementation`` is an additional boolean field in the framework layer
output metadata that indicates how tightly coupled the framework layer is
to the underlying implementation layer.

On platforms which use symlinks between layered environments and their base
environments (any platform other than Windows), ``bound_to_implementation``
will be ``false``.
This allows for transparent security updates of the base runtime layer (for
example, to update to new OpenSSL versions or CPython maintenance releases),
without needing to republish the upper layers that use that base runtime.

On Windows, where some elements of the base runtime are copied into each
layered environment that depends on it, ``bound_to_implementation`` will
be ``true``.
This still allows for transparent security updates of the base runtime layer
in some cases (for example, to update to new OpenSSL versions), but indicates
the upper layers will need to be rebuilt and republished for new CPython
maintenance releases.


.. versionchanged:: 0.4.0
   Added the ability for framework layers to depend on other framework layers
   instead of depending directly on a runtime layer
   (:ref:`release details <changelog-0.4.0>`).


.. _application-layer-spec:

Application layer specification fields
--------------------------------------

Application layer specifications must contain one of the following additional fields (but not both):

* ``runtime`` (:toml:`string`): the name of the runtime layer that this application layer uses.
* ``frameworks`` (:toml:`array` of :toml:`strings <string>`):
  the names of the framework layers that this application layer depends on.

These two fields are handled in the same way as they are for
:ref:`framework layer specifications <framework-layer-spec>`.

Python code running in this application layer will be able to import modules from the specified
base runtime layer, and from any of the framework layers declared as dependencies (whether
directly or indirectly). Refer to :ref:`layer-dependency-linearization` for additional details
on how the relative order of the application layer ``sys.path`` entries is determined.

Application layer specifications must also contain the following additional field:

* ``launch_module`` (:toml:`string`): a relative path (starting from the folder containing
  the stack specification file) that specifies a Python module or import package that will
  be included in the built environment for execution with the :option:`-m` switch.

Application layer specifications may also contain the following optional field:

* ``support_modules`` (:toml:`array` of :toml:`strings <string>`):
  an array of relative paths (each starting from the folder containing the stack specification
  file) that specify Python modules or import packages that will be included in the built
  environment for use by the application launch module.

Refer to :ref:`source-tree-content-filtering` for details on exactly which files will be
included in the application layer from referenced launch modules and support modules.

.. versionchanged:: 0.4.0
   Added the ability for application layers to depend directly on a runtime layer instead
   of declaring that they depend on one or more framework layers
   (:ref:`release details <changelog-0.4.0>`).

.. versionchanged:: 0.5.0
   Updating the name or contents of a launch module also updates the layer version
   for implicitly versioned layers
   (:ref:`release details <changelog-0.5.0>`).

.. versionadded:: 0.6.0
   Added the ``support_modules`` field (:ref:`release details <changelog-0.6.0>`).

.. versionadded:: 0.6.0
   Source tree content filtering for launch modules and support modules
   (:ref:`release details <changelog-0.6.0>`).


.. _layer-dependency-linearization:

Linearizing the Python import path
----------------------------------

The ``venvstacks.toml`` file format allows the declared dependencies between framework
layers to form a directed acyclic graph (DAG). Python's import system requires that
this graph be flattened into a list in order to be able to define the relative order
of application layer ``sys.path`` entries in a consistent fashion.

This linearization problem is similar to the one that Python itself needs to solve when
determining how to resolve attribute lookups on Python classes in the presence of multiple
inheritance, and ``venvstacks`` intentionally uses the same solution: the C3 linearization
algorithm described in this article about the
`Python 2.3 Method Resolution Order <https://www.python.org/download/releases/2.3/mro/>`_.

In simple cases where the only common point in the declared layer dependencies is the base
runtime, this algorithm gives the same result as a depth-first left-to-right resolution of
the declared dependencies.

The benefit of the more complex linearization arises in more complex cases, where the C3
algorithm either ensures that all layers are always listed in a consistent relative import
priority order, or else it raises an exception reporting the relative priority conflict.

The `Wikipedia article on C3 linearization <https://en.wikipedia.org/wiki/C3_linearization>`_
includes additional details on the C3 algorithm and the assurances it provides.

.. versionadded:: 0.4.0
   In previous versions, frameworks were not permitted to declare dependencies on other
   framework layers, so linearization was not required.


.. _layer-names:

Layer names and versioning
--------------------------

Regardless of how a layer is versioned, the layer name is used directly
(with no additional prefix or suffix) when referring to the layer as a
dependency in another layer specification.

The layer name is also used directly (in combination with the :term:`layer type`
prefix) for the following purposes:

* the name of the layer build environment
* the name of the layer requirements file folder
* as part of the name of the transitively locked layer requirements files
* as the base name for the layer environment metadata file emitted when
  publishing or exporting the environment
* as the ``layer_name`` field in the generated layer metadata

Runtime layers do not have a layer type prefix, while framework and application
layers use ``app-*`` and ``framework-*`` respectively.

Layers with implicit lock versioning disabled use their layer name directly
(in combination with their :term:`layer type` prefix) for the following purposes:

* the name of the deployed layer environment when publishing artifacts or
  locally exporting environments
* as the ``install_target`` field in the generated layer metadata
* when referring to the layer as a dependency in another layer's deployment
  configuration and output metadata

Layers with implicit lock versioning enabled will instead use
``"{layer_name}@{lock_version}"`` for these deployment related purposes.


.. _source-tree-content-filtering:

Source tree content filtering
-----------------------------

Application layer launch modules and support modules may be either single
files or directories defining a Python import package. In the latter
case, the contents of the source tree are filtered to exclude unwanted files
rather than including every file in the specified directory.

When git source control information is available, any files explicitly
excluded from source control will also be omitted from the application
layers (that is, the exclusions are based on `.gitignore` patterns).
Any files or folders with names starting with `.git` are also excluded.

If no recognised source control information is found, the source tree
content filtering defaults to simply excluding ``__pycache__`` folders
(as these may be generated if the launch modules or support modules are
imported for testing purposes from their source tree location).


Deprecated fields
-----------------

The following field names were previously supported and now emit :exc:`FutureWarning`
when used in a loaded stack specification:

* ``build_requirements``: no longer has any effect (rendered non-functional before
  :ref:`0.1.0rc1 <changelog-0.1.0rc1>`, warning emitted from :ref:`0.2.0 <changelog-0.2.0>`)
* ``fully_versioned_name``: renamed to ``python_implementation`` in :ref:`0.2.0 <changelog-0.2.0>`


.. _layer-requirements:

Locked layer requirements
=========================

Environment lock metadata files saved alongside the layer's transitively locked requirements file:

.. code-block:: python

   requirements_hash: str   # Uses "algorithm:hexdigest" format
   lock_input_hash: str     # Uses "algorithm:hexdigest" format
   other_inputs_hash: str   # Uses "algorithm:hexdigest" format
   version_inputs_hash: str # Uses "algorithm:hexdigest" format
   lock_version: int        # Auto-incremented from previous lock metadata
   locked_at: str           # ISO formatted date/time value

Note: A future documentation update will cover these ``venvstacks lock`` output files in additional detail.


.. _deployed-layer-config:

Deployed layer configuration
============================

Deployed layer configuration files saved as ``share/venv/metadata/venvstacks_layer.json`` in the layer
environments:

.. code-block:: python

   python: str                      # Relative path to this layer's Python executable
   py_version: str                  # Expected X.Y.Z Python version for this environment
   base_python: str                 # Relative path from layer dir to base Python executable
   site_dir: str                    # Relative path to site-packages within this layer
   pylib_dirs: Sequence[str]        # Relative paths to additional sys.path entries
   dynlib_dirs: Sequence[str]       # Relative paths to additional Windows DLL directories
   launch_module: NotRequired[str]  # Module to run with `-m` to launch the application

Primarily used by the post-installation script to finish setting up the environment after deployment.
May also be used by the containing application to find the Python executable location for that platform.

All relative paths are relative to the layer folder (and may refer to peer folders).
Base runtime layers will have ``python`` and ``base_python`` set to the same value.
Application layers will have ``launch_module`` set.

Note: A future documentation update will cover these ``venvstacks build`` output files in additional detail.


.. _layer-metadata:

Published layer metadata
========================

Layer output metadata files saved to the ``__venvstacks__`` metadata folder when publishing
layer archives or locally exporting layer environments:

.. code-block:: python

    # Common fields defined for all layers, whether archived or exported
    layer_name: EnvNameBuild       # Prefixed layer name without lock version info
    install_target: EnvNameDeploy  # Target installation folder when unpacked
    requirements_hash: str         # Uses "algorithm:hexdigest" format
    lock_version: int              # Monotonically increasing version identifier
    locked_at: str                 # ISO formatted date/time value

    # Fields that are populated after the layer metadata has initially been defined
    # "runtime_layer" is set to the underlying runtime's deployed environment name
    # "python_implementation" is set to the underlying runtime's implementation name
    # "bound_to_implementation" means that the layered environment includes
    # copies of some files from the runtime implementation, and hence will
    # need updating even for runtime maintenance releases
    runtime_layer: NotRequired[str]
    python_implementation: NotRequired[str]
    bound_to_implementation: NotRequired[bool]

    # Extra fields only defined for framework and application environments
    required_layers: NotRequired[Sequence[EnvNameDeploy]]

    # Extra fields only defined for application environments
    app_launch_module: NotRequired[str]
    app_launch_module_hash: NotRequired[str]

Additional metadata fields only included when publishing layer archives:

.. code-block:: python

    archive_build: int    # Auto-incremented from previous build metadata
    archive_name: str     # Adds archive file extension to layer name
    target_platform: str  # Target platform identifier
    archive_size: int
    archive_hashes: ArchiveHashes # Mapping from hash algorithm names to hashes


Hashes of layered environment dependencies are intentionally NOT incorporated
into the published metadata. This allows an "only if needed" approach to
rebuilding app and framework layers when the layers they depend on are
updated (app layers will usually only depend on some of the components in the
underlying environment, and such dependencies are picked up as version changes
when regenerating the transitive dependency specifications for each environment).

Note: A future documentation update will cover the ``venvstacks publish`` and
      ``venvstacks local-export`` output metadata files in additional detail,
      including the effects of the ``--tag-outputs`` option when publishing.
