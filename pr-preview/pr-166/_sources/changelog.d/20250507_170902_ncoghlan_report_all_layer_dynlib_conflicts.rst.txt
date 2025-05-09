Changed
-------

- The exception raised when reporting dynamic library symlink conflicts in
  a layer now reports all ambiguous library targets in the layer instead of
  only reporting the first ambiguity encountered (resolved in :pr:`158`).
