Added
-----

- A `venvstacks.uv.toml` file located alongside the stack definition file is now
  incorporated into the configuration passed to `uv` when locking and
  building environments (added in :issue:`144`). This configuration may alternatively
  be supplied via the `[tool.uv]` table in the stack definition file.
- Each layer definition may now contain a `sources` section that is used to add to or
  override the shared `uv` `sources` configuration when locking or building that layer,
  or any layer that depends on it (added in :issue:`144`).
