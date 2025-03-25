Added
-----

- The `build` and `lock` subcommands accept a new `--reset-lock`
  CLI option. This multi-use option requests that any previously
  created layer lock file be removed before locking the selected
  layers (thus ignoring any previous version pins or artifact
  hashes). This option uses the same wildcard pattern matching as
  the `--include` option. Only layers that are locked by the
  command will have their previous lock files removed.
  (added in :issue:`22`).
