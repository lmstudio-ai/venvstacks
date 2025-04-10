Changed
-------

- Extension modules on Linux and macOS that rely on shared objects
  published by their dependencies (for example, PyTorch depending
  on CUDA libraries) now work correctly even if those dependencies
  are installed in a lower environment layer. See :ref:`dynamic-linking`
  for additional details (resolved in :issue:`38`).
- To enable loading of shared objects from other environment layers,
  framework and application environments on Linux and macOS now run
  Python via a suitably capable shell environment (`bash` on Linux,
  `zsh` on macOS) that can be expected to be consistently installed
  (changed in :issue:`38`).
