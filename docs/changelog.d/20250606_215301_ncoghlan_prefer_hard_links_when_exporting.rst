Changed
-------

- Prefer the creation of hardlinks over full copies when locally exporting environments.
  Depending on the filesystem, this can make local exports significantly faster when
  the installed packages contain large files (proposed in :issue:`205`).
