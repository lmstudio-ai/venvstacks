Added
-----

- Added :ref:`macosx_target <macosx-target>` to support per-layer configuration
  of `MACOSX_DEPLOYMENT_TARGET` (added in :issue:`292`)
- Setting `MACOSX_DEPLOYMENT_TARGET` in the calling environment now affects the
  way layers that do not specify `macosx_target` are built on macOS. If this
  environment variable is not specified at all, the default macOS version
  target is the default portable target set by `uv` rather than the version
  of the system running `venvstacks` (resolved in :issue:`292`)
- The target GNU libc version for Linux layer builds is now the default portable
  target set by `uv` rather than the libc version of the system running
  `venvstacks` (resolved in :issue:`292`)
