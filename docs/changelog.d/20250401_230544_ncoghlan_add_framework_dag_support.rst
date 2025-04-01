.. Defined changelog categories:
..   - Removed
..   - Added
..   - Changed
..   - Deprecated
..   - Fixed
..   - Security
..
.. Replace "Category" below with the relevant category name.
.. Adjust the heading underline to match the chosen category name.
.. For top level release notes, delete the category header entirely.
.. Update the referenced issue number as appropriate.
.. "resolved" works for most categories, but replace the verb as necessary.
.. Use `:pr:`NN` to refer to pull requests. Other Sphinx roles also work here.
..
.. Deleting this header after editing is recommended (it contains 16 lines).

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

