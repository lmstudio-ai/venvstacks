Fixed
-----

- Using `pbs-installer` 2025.8.27 or later ensures that the smaller CPython base runtime
  installations that omit debug symbols are consistently preferred (reported in :issue:`242`).
  No explicit lower bound is set on the dependency declaration to allow `venvstacks` to be updated
  without causing conflicts with existing `pbs-installer` pins to older versions.
