Changed
-------

- All build environment manipulation is now handled with `uv` (part of resolving :issue:`144`).
  Previously, requirements compilation was handled with `uv`, while actually adding and removing
  packages was handled with `pip`. Due to related differences in package installation metadata
  (e.g. `INSTALLER` containing `uv` rather than `pip`), layer archive hash values will change.
- Hidden files and folders (those with names starting with `.`) created at the top level of layer
  build environments are no longer included in the corresponding deployed environments (whether
  exported locally or published as a deployable layer archive).
