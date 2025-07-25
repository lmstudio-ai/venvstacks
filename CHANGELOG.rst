.. Included in published docs via docs/changelog.rst

.. Temporary link target for next release
.. _changelog-0.8.0:

Unreleased
==========

See the fragment files in the `changelog.d directory`_.

.. _changelog.d directory: https://github.com/lmstudio-ai/venvstacks/tree/main/docs/changelog.d

.. scriv-insert-here

.. _changelog-0.7.0:

0.7.0 — 2025-07-05
==================

Added
-----

- `show` :ref:`subcommand <command-show>` to display layer definitions (added in :issue:`159`).
- `--show` :ref:`option <option-show>` on subcommands (other than `show`) to display the selected
  layers and operations before executing the command (added in :issue:`159`).
- `--show-only` :ref:`option <option-show-only>` on subcommands (other than `show`) to display the
  selected layers and operations *without* executing the command (added in :issue:`159`).
- `--json` :ref:`option <option-json>` on subcommands to display the selected layers
  and operations as JSON rather than as a human-readable tree. For commands other than `show`,
  implies `--show-only` if `--show` is not passed explicitly (added in :issue:`159`).

Changed
-------

- Recursive source tree processing now excludes files excluded from version control
  when building from a git repository, and excludes `__pycache__` folders otherwise.
  This exclusion affects both module hash calculations and the inclusion of files
  in built environments (resolves :issue:`203`).
- `RECORD` files for installed packages are now largely retained in published
  artifacts and locally exported environments, with only the entries
  corresponding to omitted files removed (resolved in :issue:`28`). This
  allows packages that inspect the metadata for installed packages at runtime
  to work correctly when deployed with `venvstacks`.
- Default CLI console output has been substantially reduced, with new `-q/--quiet`
  and `-v/--verbose` options added to adjust the message volume (changed in :issue:`5`).
- Library level messages are now emitted via the `logging` module rather than being written
  directly to `stdout`. The CLI configures the logging subsystem appropriately based on
  the given verbosity options (changed in :issue:`5`).

Fixed
-----

- When using the `--include` filtering option for layer builds, existing "build if needed"
  environments are now correctly updated if they have not previously been successfully
  built with the current layer specification and environment lock details
  (reported in :issue:`222`).
- Implicit versioning of runtime layers no longer breaks deployed
  layered environments using that layer (reported in :issue:`188`).
- Implicit versioning of framework layers no longer breaks loading
  dynamic libraries from those layers on non-Windows systems
  (reported in :issue:`189`)
- Layer locks are now marked as valid if the lock is successfully
  regenerated without changes after being marked as invalid due
  to a lower layer having an invalid lock (resolved in :pr:`227`)

.. _changelog-0.6.0:

0.6.0 — 2025-06-07
==================

Added
-----

- A new optional field, `support_modules`, has been added to application layer specifications.
  This field allows application layers to embed copies of common unpackaged support libraries
  without needing to duplicate that code in the source tree (proposed in :issue:`202`).
- The `lock` subcommand now accepts an `--if-needed` option that skips locking
  layers that already have a valid layer lock (added in :pr:`200`).

Changed
-------

- Added a `--lock-if-needed` option to the `build` subcommand that ensures layers
  are only locked if they don't already have valid transitive environment locks.
  `--lock` is now a deprecated alias for this option rather than being equivalent
  to running the `lock` subcommand (proposed in :issue:`196`).
- Changes to lock inputs that only affect the implicit layer versioning are now
  tracked separately from changes to the additional inputs that affect the result
  of the transitive dependency lock generation step. These changes are now ignored
  for layers that do not use implicit layer versioning (proposed in :issue:`201`).
- Prefer the creation of hardlinks over full copies when locally exporting environments.
  Depending on the filesystem, this can make local exports significantly faster when
  the installed packages contain large files (proposed in :issue:`205`).

Fixed
-----

- Launch module existence checks are now skipped for layers that will not
  be built for the target build platform (reported in :issue:`204`).

.. _changelog-0.5.1:

0.5.1 — 2025-05-26
==================

Changed
-------

- Build failures for invalid layer locks now provide more details on the discrepancies
  that result in the lock being considered invalid (changed in :pr:`181`).

Fixed
-----

- ``launch_module`` is now correctly set in the internal ``venvstacks_layer.json``
  configuration file shipped as part of application layers (resolved in :pr:`174`).
- Layer locks are no longer incorrectly marked as invalid solely because the lock
  input cache files for the declared requirements are missing (reported in :issue:`175`).
- Layer lock metadata generated by versions prior to 0.5.0 is now accepted as valid
  as long as the locked requirements file hasn't changed (resolved in :pr:`187`).
- Resetting runtime and framework layer locks no longer prevents locking layers that
  depend on the affected layers (resolved in :pr:`187`).
- Repeated local builds for environments using the dynamic library loading wrapper
  scripts no longer corrupt the base Python environment link (reported in :issue:`184`).

.. _changelog-0.5.0:

0.5.0 — 2025-05-12
==================

Changed
-------

- Layer locks are now invalidated for launch module changes. This also means
  that implicit versioning will update the layer version (resolves :issue:`89`).
- The exception raised when reporting dynamic library symlink conflicts in
  a layer now reports all ambiguous library targets in the layer instead of
  only reporting the first ambiguity encountered (resolved in :pr:`158`).

Fixed
-----

- Previously defined layer locks are now correctly invalidated in the following
  cases (resolves :issue:`149`):

   - the layer's declared input requirements have changed
   - the major Python version of the layer's base runtime has changed
   - the layer depends on a layer that does not currently have a valid layer lock
   - the relative paths from the layer to the layers it depends have changed
     (including additions and removals of layer dependencies)
   - implicit layer versioning is enabled or disabled for the layer
- Attempting to lock a layered environment now fails if any layer it depends
  on does not have a currently valid layer lock (resolves :issue:`161`).
- CLI arguments on Windows are no longer unexpectedly resolved as filesystem
  glob patterns (resolved in :pr:`160`).
- Dynamic library symlinks are now correctly removed if the dynamic library is no
  longer included in the built layer (resolved in :pr:`163`).
- As it affects launch module execution, application layer launch module hashes now
  incorporate the file name in addition to the file contents (resolved in :pr:`164`).
- Application layer launch packages are now consistently archived using the layer's
  lock timestamp, even when that is more recent than the file's local modification time
  (resolved in :pr:`148`).

.. _changelog-0.4.1:

0.4.1 — 2025-04-25
==================

Added
-----

- Locking layers now emits package summary files for each layer, which should
  make it easier to see what has changed when locks are updated
  (suggested in :issue:`108`).

Changed
-------

- The exception raised when reporting dynamic library symlink conflicts in
  a layer now suggests using the ``dynlib_exclude`` setting to resolve the
  conflict (changed in :pr:`141`).

Fixed
-----

- The `--reset-lock` option now propagates to derived layers as intended
  (reported in :issue:`137`).


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
