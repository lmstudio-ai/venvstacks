.. Included in published docs via docs/changelog.rst

.. Temporary link target for next release
.. _changelog-0.3.0:

Unreleased
==========

See the fragment files in the `changelog.d directory`_.

.. _changelog.d directory: https://github.com/lmstudio-ai/venvstacks/tree/main/changelog.d

.. scriv-insert-here

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
