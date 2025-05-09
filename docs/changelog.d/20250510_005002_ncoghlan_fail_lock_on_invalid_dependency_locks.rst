Fixed
-----

- Attempting to lock a layered environment now fails if any layer it depends
  on does not have a currently valid layer lock (reported in :issue:`161`).
