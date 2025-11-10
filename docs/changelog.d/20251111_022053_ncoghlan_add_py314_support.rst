Added
-----

- Running on CPython 3.14 is now tested in CI. Note that due to changes in the
  ``zlib`` standard library module implementation, Windows layer archives built
  using CPython 3.14 to run the build will typically be smaller than those
  produced by previous versions (added in :pr:`247`).
