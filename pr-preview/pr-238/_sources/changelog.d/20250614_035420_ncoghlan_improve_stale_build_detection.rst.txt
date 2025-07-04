Fixed
-----

- When using the `--include` filtering option for layer builds, existing "build if needed"
  environments are now correctly updated if they have not previously been successfully
  built with the current layer specification and environment lock details
  (reported in :issue:`222`).
