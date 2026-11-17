# Source timing reconciliation — 2026-11-17

The collector now runs source vehicle-time refresh independently from the
workload polling cycle, matching the production source-timing deployment
captured on 2026-11-14. The change removes per-item detail requests from the
poll cycle and starts a bounded sequential refresh worker during collector
startup. No production service was modified by this repository change.
