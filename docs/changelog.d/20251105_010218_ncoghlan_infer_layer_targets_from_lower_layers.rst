Changed
-------

- Layer target platforms are now inferred from the layers they depend on.
  An exception is raised if a layer specifies targets that are not also
  targets for the lower layers it depends on (changed in :issue:`244`).
