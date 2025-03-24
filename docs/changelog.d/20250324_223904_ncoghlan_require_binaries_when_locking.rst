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

Fixed
-----

- `--only-binary ":all:"` is now passed when locking the layers in addition
  to being passed when creating the layer environments. This avoids emitting
  requirements that can't be installed (resolved in :issue:`102`).
