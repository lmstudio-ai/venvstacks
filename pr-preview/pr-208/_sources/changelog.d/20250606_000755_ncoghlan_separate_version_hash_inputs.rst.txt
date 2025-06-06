Changed
-------

- Changes to lock inputs that only affect the implicit layer versioning are now
  tracked separately from changes to the additional inputs that affect the result
  of the transitive dependency lock generation step. These changes are now ignored
  for layers that do not use implicit layer versioning (proposed in :issue:`201`).
