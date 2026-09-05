# Authorization boundaries

These are the standing limits on what an agent or developer may do in this
repository. They are **boundaries only** — no production state, no host names,
no commit pins. The detailed, volatile operational state lives in the private
ops repo `AvelRen-ops`.

A boundary that is written where the work does not happen is a boundary that is
not enforced. These rules live here, in the public repo, because this is where
the code is edited and the branches are built.

## 1. No production mutation without an explicit GO

No production operation may be performed without a separate, explicit
authorization for that specific operation, in the moment. This covers
production adoption, production restore, deployment, credential generation or
rotation, role changes on the live database, and any command that writes to
production.

A GO is per-operation and does not generalize: authorization for one action is
not authorization for the next one. "Nothing appeared to happen" is not proof
that nothing was authorized to happen — measure the result before proceeding.

## 2. No force-push, no editing an applied migration

- **Never force-push** to shared branches, and never rewrite published history.
- **Never edit an already-applied migration.** The applier compares sha256 and
  will stop with an error. If a fix is needed, write a new migration file
  (`db/migrations/NNN_description.sql`, sequential number).

The migration rule is a code invariant, not a convention: it is enforced at
apply time and cannot be talked around.

## 3. Build the device APK only from a clean `main`

The APK installed on a device must come from the clean tip of `main` — never
from a feature branch. The working tree must be clean before building, and the
build must be recorded (sha256, commit, date) and verified by pulling the
installed APK back off the device and comparing hashes.

Reason: a past design drift began with an APK built from a branch. Keeping the
build tied to `main` keeps that class of drift from recurring.

## Where the detailed state lives

The full operational state — production runbooks, authorization procedures,
bring-up, CI parity, audits, the upstream integration contract, and how far
production trails `main` — is documented in the private ops repo `AvelRen-ops`.
This file names none of it; it states only the limits that hold regardless.
