Fixed
-----

- Implicit versioning of runtime layers no longer breaks deployed
  layered environments using that layer (reported in :issue:`188`).
- Implicit versioning of framework layers no longer breaks loading
  dynamic libraries from those layers on non-Windows systems
  (reported in :issue:`189`)
- Layer locks are now marked as valid if the lock is successfully
  regenerated without changes after being marked as invalid due
  to a lower layer having an invalid lock (resolved in :pr:`227`)

