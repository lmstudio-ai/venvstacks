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

Changed
-------

- Default CLI console output has been substantially reduced, with new `-q/--quiet`
  and `-v/--verbose` options added to adjust the message volume (changed in :issue:`5`).
- Library level messages are now emitted via the `logging` module rather than written
  directly to `stdout`. The CLI configures the logging subsystem appropriately based on
  the given verbosity options (changed in :issue:`5`).

