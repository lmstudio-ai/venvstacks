Changed
-------

- Locking operations are no longer filtered by platform. This means the
  `BuildEnvironment.all_environments` iterator now reports all defined
  layers, not just those for the current platform. Iterate over
  `BuildEnvironment.environments_to_build` without any layer filtering
  configured to obtain a list of layers specific to the current platform
  (resolved in :issue:`265`).
