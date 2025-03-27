Fixed
-----

- `--only-binary ":all:"` is now passed when locking the layers in addition
  to being passed when creating the layer environments. This avoids emitting
  requirements that can't be installed (resolved in :issue:`102`).
