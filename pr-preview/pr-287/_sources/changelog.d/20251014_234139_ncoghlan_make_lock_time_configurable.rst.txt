Changed
-------

- If `UV_EXCLUDE_NEWER` is set in the environment, or `exclude-newer` is set
  in the `uv`  tool configuration, the given time is used as the recorded
  lock time for all updated layer locks (proposed in :issue:`10`).
