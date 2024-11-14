Changed
-------

- Updated docs to actively discourage using ``@`` in layers names (part of :issue:`78`).
- Renamed ``fully_versioned_name`` runtime layer specification field to ``python_implementation`` (part of :issue:`78`).
- Renamed ``runtime_name`` to ``runtime_layer`` in the layer metadata (to align with the ``required_layers`` field),
  and simplified it to always refer to the runtime layer's install target name (part of :issue:`78`).

