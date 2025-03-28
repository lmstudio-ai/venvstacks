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

- `"win_arm64"` and `"linux_aarch64"` are now accepted as target platforms.
  ARM64/Aarch64 refer to the same CPU architecture, but Python reports it differently
  depending on the OS, and this is reflected in their respective platform tags
  (added in :issue:`107`).
