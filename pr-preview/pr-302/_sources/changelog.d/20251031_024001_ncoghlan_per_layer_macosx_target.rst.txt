Added
-----

- Added `macosx_target` to support per-layer configuration of `MACOSX_DEPLOYMENT_TARGET`.
  Also resolved an issue that meant layers already built locally would not be updated
  correctly if the macOS deployment target changed (resolved in :issue:`292`).
