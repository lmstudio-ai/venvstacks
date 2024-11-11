Added
-----

- Setting ``versioned = True`` in a layer definition will append a
  lock version number to the layer name that automatically increments
  each time the locked requirements change for that layer (``layer@1``,
  ``layer@2``, etc). Layer dependency declarations and build environments,
  use the unversioned name, but deployed environments and their metadata
  will use the versioned name (implemented in :issue:`24`).
