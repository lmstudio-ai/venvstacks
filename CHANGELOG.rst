.. Included in published docs via docs/changelog.rst

.. Temporary link target for next release
.. _changelog-0.5.0:

Unreleased
==========

See the fragment files in the `changelog.d directory`_.

.. _changelog.d directory: https://github.com/lmstudio-ai/venvstacks/tree/main/docs/changelog.d

.. scriv-insert-here

.. _changelog-0.4.0:

0.4.0 — 2025-04-11
==================

Added
-----

- Framework layers may now specify `frameworks` to depend on one or more
  framework layers instead of depending directly on a runtime layer.
  Framework dependencies must form a directed acyclic graph (DAG), and
  framework layers must be defined *after* any framework layers they
  depend on (proposed in :issue:`18`, implemented in :pr:`119`).
- Application layers may now specify `runtime` to depend directly on a
  a runtime layer with no intervening framework layers
  (added as part of resolving :issue:`18`).
- All layers may now specify `dynlib_exclude` to indicate dynamic
  libraries which should not be symbolically linked into the
  `share/venv/dynlib/` environment subfolder on Linux and macOS
  (added as part of resolving :issue:`38`).

Changed
-------

- To enable loading of shared objects from other environment layers,
  framework and application environments on Linux and macOS now run
  Python via a suitably capable shell environment (`bash` on Linux,
  `zsh` on macOS) that can be expected to be consistently installed
  (changed in :issue:`38`).

Fixed
-----

- Extension modules on Linux and macOS that rely on shared objects
  published by their dependencies (for example, PyTorch depending
  on CUDA libraries) now work correctly even if those dependencies
  are installed in a lower environment layer. See :ref:`dynamic-linking`
  for additional details (resolved in :issue:`38`).

.. _changelog-0.3.0:

0.3.0 — 2025-03-28
==================

Added
-----

- The `build` and `lock` subcommands accept a new `--reset-lock`
  CLI option. This multi-use option requests that any previously
  created layer lock file be removed before locking the selected
  layers (thus ignoring any previous version pins or artifact
  hashes). This option uses the same wildcard pattern matching as
  the `--include` option. Only layers that are locked by the given
  command will have their previous lock files removed, as excluded
  layers will be excluded from both locking and having their lock
  files reset (added in :issue:`22`).
- `"win_arm64"` and `"linux_aarch64"` are now accepted as target platforms.
  ARM64/Aarch64 refer to the same CPU architecture, but Python reports it differently
  depending on the OS, and this is reflected in their respective platform tags
  (added in :issue:`107`).

Changed
-------

- A Python API instability `FutureWarning` is now emitted at runtime (added while resolving :issue:`22`).
- The previous :func:`!BuildEnvironment.get_unmatched_patterns` method has been replaced
  by the new :func:`BuildEnvironment.filter_layers` method, which returns both the
  matching layer names and the unmatched patterns (changed in :issue:`22`).
- :func:`BuildEnvironment.select_layers` now accepts an iterable of environment names
  rather than an iterable of filter patterns to be matched (changed in :issue:`22`).

Fixed
-----

- `--only-binary ":all:"` is now passed when locking the layers in addition
  to being passed when creating the layer environments. This avoids emitting
  requirements that can't be installed (resolved in :issue:`102`).
- Remove directories from /bin when building layers (resolved in :pr:`103`)


.. _changelog-0.2.1:

0.2.1 — 2024-12-05
==================

Fixed
-----

- Fix Typer 0.14.0+ incompatibility when setting app name (reported by Rugved Somwanshi in :issue:`96`).

.. _changelog-0.2.0:

0.2.0 — 2024-11-14
==================

Added
-----

- Setting ``versioned = True`` in a layer definition will now append a
  lock version number to the layer name that automatically increments
  each time the locked requirements change for that layer (``layer@1``,
  ``layer@2``, etc). Refer to :ref:`layer-names` for details on when the
  versioned and unversioned layer names are used (implemented in :issue:`24`).
- Added documentation for the :ref:`stack-specification-format` (part of :issue:`78`).
- Added ``python_implementation`` to the published layer metadata (part of :issue:`78`).
- Added ``bound_to_implementation`` to the published layer metadata (part of :issue:`78`).

Changed
-------

- Enabled rendered previews for documentation PRs (requested in :issue:`43`).
- Enabled link validity checks when rendering documentation (requested in :issue:`62`).
- Renamed :class:`!EnvironmentExportRequest` to :class:`LayerExportRequest` (part of :issue:`33`).
- Exposed :class:`LayerSpecBase`, :class:`LayeredSpecBase` as public classes (part of :issue:`33`).
- Exposed :class:`LayerEnvBase`, :class:`LayeredEnvBase` as public classes (part of :issue:`33`).
- Added leading underscores to several private functions and methods (part of :issue:`33`).
- Added docstrings to all remaining public functions and methods (part of :issue:`33`).
- Updated docs to actively discourage using ``@`` in layers names (part of :issue:`78`).
- Renamed ``fully_versioned_name`` runtime layer specification field to ``python_implementation`` (part of :issue:`78`).
- Renamed ``runtime_name`` to ``runtime_layer`` in the layer metadata (to align with the ``required_layers`` field),
  and simplified it to always refer to the runtime layer's install target name (part of :issue:`78`).

Fixed
-----

- Post-installation scripts for layered environments now work
  correctly even when run with a Python installation other
  than the expected base runtime (resolved in :issue:`66`)

.. _changelog-0.1.1:

0.1.1 — 2024-11-01
==================

Changed
-------

- Update docs URL to
  `https://venvstacks.lmstudio.ai <https://venvstacks.lmstudio.ai>`__

- Add OpenGraph metadata to docs landing page

- Resolved several broken links in the documentation

- Documentation is now marked as being unversioned
  (it is published directly from the main branch)

.. _changelog-0.1.0:

0.1.0 — 2024-10-31
==================

Changed
-------

- Further documentation fixes and improvements

.. _changelog-0.1.0rc1.post0:

0.1.0rc1.post0 — 2024-10-30
===========================

Changed
-------

- Included project URLs in project metadata

- Added installation instructions to README.md

- Linked to main documentation from README.md

- Improved the content split between the project
  overview page and the top level docs landing page

.. _changelog-0.1.0rc1:

0.1.0rc1 — 2024-10-29
=====================

Added
-----

- Initial export of ``venvstacks`` from Project Amphibian.

- Adopted ``scriv`` for ``CHANGELOG`` management.
