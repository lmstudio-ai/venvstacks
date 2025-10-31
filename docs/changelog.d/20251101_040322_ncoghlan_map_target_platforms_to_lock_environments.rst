Changed
-------

- Layer target platforms are now inferred from the layers they depend on.
  An exception is raised if the layer specifies targets that are not
  provided for all related lower layers (changed in :issue:`303`).
