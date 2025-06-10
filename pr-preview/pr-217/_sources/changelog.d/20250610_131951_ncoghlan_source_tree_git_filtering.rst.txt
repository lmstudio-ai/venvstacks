Changed
-------

- Recursive source tree processing now excludes files excluded from version control
  when building from a git repository, and excludes `__pycache__` folders otherwise.
  This exclusion affects both module hash calculations and the inclusion of files
  in built environments (resolves :issue:`203`).

