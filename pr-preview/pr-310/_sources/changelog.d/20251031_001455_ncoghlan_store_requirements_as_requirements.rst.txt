Changed
-------

- Layer dependency declarations are now eagerly parsed and stored as structured
  requirements. Invalid requirements are now reported as specification errors
  rather than as cryptic locking command failures (resolved in :issue:`101`).
