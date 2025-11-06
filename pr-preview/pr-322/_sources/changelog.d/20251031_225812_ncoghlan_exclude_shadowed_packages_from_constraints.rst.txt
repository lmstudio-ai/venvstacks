Changed
-------

- The handling of shadowed packages across framework layers has changed,
  so unconditionally shadowed packages are no longer treated as constraints
  by higher layers. Environment marker conditions are also listed for
  shared packages from lower layers in layer summaries (resolved in :issue:`292`).
