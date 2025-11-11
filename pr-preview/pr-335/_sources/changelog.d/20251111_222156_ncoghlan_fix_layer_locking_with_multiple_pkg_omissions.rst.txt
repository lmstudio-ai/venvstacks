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

- Resolved a number of issues related to incorrect layer dependency filtering
  for different combinations of environment markers, layer target platforms,
  and package provenance details (initial problem reported in :issue:`333`,
  additional issues found when updating the test suite to ensure the example
  stacks are producing the expected layer lock and package summary details).

