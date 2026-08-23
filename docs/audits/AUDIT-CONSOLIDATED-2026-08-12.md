# AvelRen — Consolidated Audit (2026-08-12)

Five parallel reviews: Python backend, Security, DB/DevOps, Test/CI, Android.
Read-only analysis. No files modified.

## Overall verdict

AvelRen is a mature, security-conscious codebase that has clearly absorbed prior
audits (findings referenced by ID throughout). No critical issues found. Two
high-severity items in the app tiers plus one high durability gap in ops. Dominant
theme: strong safety engineering (fail-closed migrations/restore, constant-time
auth, least-privilege DB roles, encrypted Android storage) paired with a few
resilience/proportionality gaps.

## Top priorities (cross-cutting)

| # | Severity | Area | Issue | Fix |
|---|----------|------|-------|-----|
| 1 | HIGH | Backend | Blocking sync `requests` call in async loop — FCM OAuth refresh `fcm.py:119-120` stalls event loop hourly | `await asyncio.to_thread(_credentials.refresh, Request())` |
| 2 | HIGH | Ops | 24h RPO, dump-only, no WAL/PITR for irreplaceable data (`avelren-backup.timer:6`, `001_init.sql:18`) | Add WAL archiving; state approved RPO |
| 3 | HIGH | Android | Only credential stored via alpha+deprecated `security-crypto 1.1.0-alpha06` (`DeviceStore.kt:45`) | Move off alpha; decrypt-failure fallback |
| 4 | HIGH | Android build | Release APK unsigned, no R8, empty ProGuard (`app/build.gradle.kts:26-30`) | Add signingConfig; enable R8 with keep rules |
| 5 | HIGH | Test/CI | No type checking, no dep/security scanning, actions on floating tags | Add mypy, pip-audit, Dependabot, SHA-pin actions |
| 6 | MED | Security/DoS | Public reads (`/forecast`,`/history`,`/workload`) unauth + unthrottled; `"read"` bucket in `ratelimit.py:18` never wired | Apply `rate_check(request,"read")` |
| 7 | MED | Security | In-memory rate limiter unbounded under many source IPs (`ratelimit.py:58-62`) | LRU with hard ceiling |

## Backend correctness

- MED `subscriptions_api.py:96` — `last_seen` UPDATE on every authenticated GET → write amplification. Throttle to ~1h.
- MED `forecast.py:105` — seasonality bucketed in UTC for a Kyiv-local DST phenomenon; smears slots by an hour. Use `AT TIME ZONE 'Europe/Kyiv'`.
- MED `forecast.py:59-70` — readiness span-based not sample-based; conflates `MIN_SAMPLES_READY` with a weeks threshold.
- LOW `telemetry.py` reads snapshot 4×/request (blocking IO); `notifier.py:88` whole cycle in one implicit txn → possible duplicate sends; `collector.py:38` empty upstream payload can trip watchdog falsely.

## Database / DevOps

- MED No resource limits on any Compose service — one OOM can kill Postgres.
- MED No healthchecks on app containers; `caddy` depends on unchecked `api`.
- MED Unbounded growth of `alerts`, `eta_alerts`, `collector_runs` (~525k rows/yr).
- MED Role DSN passwords as plain env vars (`docker inspect`-readable). Use Docker secrets.
- MED Adoption/ownership subsystem disproportionate: `postgres-ownership.lib.sh` 1,815 lines + 2,208-line test ≈ 63% of app size; all disposable-only, never prod. Deploy+tests ≈ 2.9× app.
- LOW Backup key escrow "not externally verified" (issue #14); `001` cagg created inside migrate.py txn (version-coupled); `avelren_admin` LOGIN SUPERUSER used for routine restore.

## Security — verified clean

No SQL injection (backend parameterized; shell `%I`/`%L` + identifier validation);
secrets hashed + constant-time compared; no enumeration oracle; correct 400/401/503;
trusted-proxy enforced at Caddy, no published API host port; 7-role least privilege
(API cannot set `is_admin`); Android exported surface minimal, TLS-only, allowBackup off.

Remaining: LOW no HSTS/security headers; LOW no request-body cap; LOW FCM-token
reassignment availability attack (documented, needs FCM challenge); LOW `avelren_admin`
superuser blast radius.

## Test / CI

- Untested high-risk: `collector.run_cycle` (core ingestion, R-06 txn split), `echerha.fetch_workload` (sole network boundary).
- Untested API: `/thresholds`, `/forecast/{id}`, `/forecast/{id}/quality`, `PUT /devices/token` success.
- Android thinnest: `AvelRenMessagingService`, `DeviceStore`, `NotificationReconciler`, all Compose UI.
- CI: up to 240 min, no caching.
- Strength: real-TimescaleDB tests with fail-closed prod guard; frozen least-privilege ACLs asserted column-by-column.

## Android

No contract drift — endpoints, JSON fields, FCM payload keys, thresholds all match backend.
Correct coroutine hygiene, 401→re-register recovery, fail-safe reconciliation.
Beyond H1/M1: LOW no cleartext-traffic hardening; LOW `/api` prefix assumes unseen proxy
rewrite; LOW telemetry `null`/raw-double UI polish; LOW status `note` never auto-cleared.

## Genuine strengths (consensus)

1. Failure-mode discipline — durable derived-phase status, transactional cancel enqueue, fail-closed migrations and restore, physical schema verification.
2. Auth done right — 256-bit secret, SHA-256 + `hmac.compare_digest`, no enumeration oracle, clean error taxonomy with regression tests.
3. Real-Postgres testing with production-safety guard; exhaustively frozen least-privilege ACLs.
4. Self-documenting — comments cite the specific audit finding each fix closes.
