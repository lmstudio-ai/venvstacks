Changed
-------

- Added a `--lock-if-needed` option to the `build` subcommand that ensures layers
  are only locked if they don't already have valid transitive environment locks.
  `--lock` is now a deprecated alias for this option rather than being equivalent
  to running the `lock` subcommand (proposed in :issue:`196`).

