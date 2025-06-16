Changed
-------

- `RECORD` files for installed packages are now largely retained in published
  artifacts and locally exported environments, with only the entries
  corresponding to omitted files removed (resolved in :issue:`28`). This
  allows packages that inspect the metadata for installed packages at runtime
  to work correctly when deployed with `venvstacks`.
