Changed
-------

- Layer requirements locking is now cross-platform, with environment markers
  now retained for platform specific dependencies (proposed in :issue:`254`).
  While not part of the published tool, an example script is available in
  the `venvstacks` source repository to remove platform tags from lock files
  generated with older versions (this allows for easier review of the *actual*
  changes introduced by the migration to platform independent lock file names)
