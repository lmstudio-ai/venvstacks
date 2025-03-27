Changed
-------

- The previous :func:`!BuildEnvironment.get_unmatched_patterns` method has been replaced
  by the new :func:`BuildEnvironment.filter_layers` method, which returns both the
  matching layer names and the unmatched patterns (changed in :issue:`22`).
- :func:`BuildEnvironment.select_layers` now accepts an iterable of environment names
  rather than an iterable of filter patterns to be matched (changed in :issue:`22`).
