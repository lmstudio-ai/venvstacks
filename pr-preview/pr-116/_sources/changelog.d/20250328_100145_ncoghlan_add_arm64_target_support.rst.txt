Added
-----

- `"win_arm64"` and `"linux_aarch64"` are now accepted as target platforms.
  ARM64/Aarch64 refer to the same CPU architecture, but Python reports it differently
  depending on the OS, and this is reflected in their respective platform tags
  (added in :issue:`107`).
