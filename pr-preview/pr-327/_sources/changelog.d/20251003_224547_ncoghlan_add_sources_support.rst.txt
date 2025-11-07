Added
-----

- Each layer definition may now contain a :ref:`package_indexes <package-indexes>`
  section that is used to adjust the `uv` `sources` configuration when locking or
  building that layer, or any layer that depends on it (added in :issue:`270`).
- Each layer definition may now contain a :ref:`index_overrides <index-overrides>`
  section that allows apparent inconsistencies in layer package index configurations
  to be marked as expected and acceptable (added in :issue:`269`).

