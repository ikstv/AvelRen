# Privacy, data inventory, and retention

AvelRen accumulates border-checkpoint queue history for trucks. This document is
the authoritative inventory of what data exists, why, how long it is kept, and
how it is deleted. It describes the system as built; where a control is planned
but not yet implemented, that is stated explicitly (not glossed over).

## Design stance: pseudonymous, no accounts

AvelRen has **no user accounts** and collects **no directly identifying data** —
no email, no phone number, no name, no billing data. A client is a *device*,
identified by a server-generated random UUID plus a push token and a device
secret. There is no way, from the data AvelRen holds, to map a device to a
named person without external correlation the system neither performs nor
enables.

The one hard architectural rule (see README) keeps the blast radius small: only
the server talks to the upstream source; clients only ever read AvelRen's own API.

## Data inventory

| Table | Fields of note | Personal? | Purpose | Retention |
|---|---|---|---|---|
| `devices` | `id` (uuid), `fcm_token`, `secret_hash`, `platform`, `is_admin`, `last_seen` | **Pseudonymous** — push token + device secret hash; no real-world identity | Deliver notifications; authenticate the device on state-changing requests | While active; stale devices are **not** yet auto-purged (see #19) |
| `subscriptions` / `eta_targets` | `device_id` → checkpoint + threshold/target | Linked to a device (pseudonymous) | What the device asked to be alerted about | Until deleted by the device; cascades on device delete |
| `alerts` / `eta_alerts` / `subscription_state` | delivery lifecycle | Linked to a subscription | Fire-once + cancel bookkeeping | Lifecycle-bound; cascades |
| `observations` | queue wait time, vehicles in queue, `time` | **Not personal** — public upstream queue data | The core product: queue history | Compressed after 7 days; **kept indefinitely** (historical value) |
| `observations_hourly` | hourly rollups | Not personal | Forecast/readiness inputs | Continuous aggregate over `observations` |
| `checkpoints` / `countries` | reference data + `last_seen` | Not personal | Catalogue of border points | Stale entries drop off via `last_seen` |
| `collector_runs` / `health_alerts` | ingestion + health bookkeeping | Not personal | Operability | Operational |

**Not collected / not stored:** client IP addresses are used only ephemerally
for rate limiting (behind the trusted proxy) and are **never persisted** — there
is no IP column anywhere. No location beyond the checkpoint a device subscribes
to. No message content, no contacts.

## Retention policy

- **Queue observations** — the product's reason to exist — are retained
  indefinitely, compressed after 7 days (`add_compression_policy`). They contain
  no personal data, so indefinite retention carries no privacy cost.
- **Device / subscription data** is kept while the device is in use. `last_seen`
  is updated on activity, which makes stale-device purging *possible*; an
  automatic retention job for inactive devices is **not yet implemented** —
  tracked as part of #19 (FCM token ownership & installation retention).

## Deletion

- **Subscriptions and ETA targets**: a device can delete its own via
  `DELETE /subscriptions/{id}` and `DELETE /eta_targets/{id}` (both require the
  device's `id` + secret headers and scope the delete to that `device_id`).
- **Cascade**: deleting a `devices` row removes all its subscriptions, targets,
  alerts, and state via `ON DELETE CASCADE` — deletion is complete, not partial.
- **Self-service device deletion** (a client erasing its whole installation) is
  **not yet exposed** as an endpoint; today a device delete is an operator
  action. A user-facing delete-installation flow is planned in #19.

## Access (least-privilege)

Runtime access to this data is being split from the single `avelren` role into
seven least-privilege roles (issue #15, rollout in progress). After adoption,
each service reads only what it needs: `avelren_api` gets column-scoped access to
`devices` (never the whole row), `avelren_collector` writes observations,
`avelren_backup` is read-only, etc. See migration `010_postgresql_least_privilege`
and `deploy/postgres-adoption-runbook.md`.

## Related runbooks

- `docs/backup-key-escrow.md` — off-host encrypted backup key handling.
- `docs/disaster-recovery.md` — restore procedure and verification.
- `docs/trusted-proxy.md` — how the real client IP is derived (and not stored).

## Known gaps (honestly)

- Automatic retention/purge of inactive devices — #19.
- Self-service delete-installation endpoint + audit trail — #19.
- Release-signing runbook (Android keystore custody) — remaining part of #25.
