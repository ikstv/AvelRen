# A signal has a date

Three habits that share one root. In each case the thing you read was **true when
it was captured and stopped being true silently.** So the check is never the
claim itself — it is whether the world moved under it.

## Search for a PR before trusting an issue's state

Run `gh pr list --search ...` before taking an open issue. An open issue does not
mean the work is undone — the board does not show PRs.

*What it cost:* #18 looked unstarted because its issue was open; the work was
already sitting in PR #52. A day lost before we looked.

## A pre-measurement goes stale the moment the base moves

A number you measured against `main` (or a live database) is valid only for that
state. Re-measure after anything moves the base.

*What it cost:* a gate was measured, then #115 merged and `main` was a different
tree; the earlier number described a world that no longer existed.

## Read a dead artifact by its date

An exited container, an old log line, a past reading — check *when* it was
captured and *what happened since*, and never read it as the current state.

*What it cost:* the `avelren-migrate-1` container died on 14 Aug
(`InsufficientPrivilege`). Read on 22 Aug as a current diagnosis, it reversed the
direction of the risk — the 3B.2 adoption (17 Aug) had granted the role in
between, so the failure it "showed" could no longer happen.

## The common rule

**Verify the world, not the statement.** In all three the fact was true at
capture and expired without a sound — so what you check is not whether the claim
reads true, but whether something moved underneath it.
