Added
-----

- Framework layers may now specify `frameworks` to depend on one or more
  framework layers instead of depending directly on a runtime layer.
  Framework dependencies must form a directed acyclic graph (DAG), and
  framework layers must be defined *after* any framework layers they
  depend on (proposed in :issue:`18`, implemented in :pr:`119`).
- Application layers may now specify `runtime` to depend directly on a
  a runtime layer with no intervening framework layers
  (added as part of resolving :issue:`18`).

