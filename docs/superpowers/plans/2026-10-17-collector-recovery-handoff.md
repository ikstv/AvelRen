# Безпечний collector recovery handoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Реалізувати й локально прийняти вихід з recovery_required із заміною legacy collector без втрати spool/SQL.
**Architecture:** Окремий staged operator handoff поверх наявних backup/control leases; durable journal блокує звичайні операції до завершення. Native collector ACK/replay і штатний paired publication/restore залишаються доказом роботи.
**Tech Stack:** Python, Linux flock/proc, SQLite, Docker/Compose, PostgreSQL/TimescaleDB.
**Spec:** [дизайн recovery handoff](../specs/2026-10-17-collector-recovery-handoff-design.md).

## Global Constraints

- Жодних SSH або production mutations; лише local disposable resources з ownership labels.
- Один collector, постійний Device ID, інтервал 60 секунд; upstream тільки синтетичний.
- Зберігати SQL/spool/state/audit; не підробляти receipt/stamp і не розширювати legacy restore allowlist.
- Звичайний backup/control має відмовляти при активному handoff, включно з crash windows.

## Review Focus

- Stale/reused PID та reboot — fail closed, без автоматичного ownership takeover.
- Неповний children[] — незалежна перевірка Docker jobs і foreign ownership.
- Crash між manifest/recreate/state writes — journal та повторна ідентифікація, без другого producer.
- Legacy ACK змішані з modern pending/started — SQL збережено, strict restore не послаблено.
- Rollback з pending/started — відмова від legacy start, volume збережено.

## Tasks / ledger

- [x] Task 1: ops/collector-recovery-handoff.py, контрактні тести, мінімальний journal interlock paired_backup_state.py. RED → GREEN, guards/drift/crash/rollback.
- [x] Task 2: collector spool migration acceptance та необхідний мінімальний backend fix. RED → GREEN, aged/unaged ACK, started/pending, crash/commit idempotence.
- [x] Task 3: спільний real-daemon acceptance: handoff, native ACK, safe rollback, new paired publish/readback та штатний isolated restore.
- [x] Task 4: незалежний review, цільові regression/CI wiring, документація/runbook та user-facing evidence.

Ruling: користувач прямо замовив локальну реалізацію попередньо підготовленого контракту; працюємо без повторного запиту дозволу, server GO залишається окремим.
Ruling: використовуємо вже ізольований task clone work/AvelRen-backup-fix на новій codex/collector-recovery-handoff-20261017; чужих змін немає.

Ruling: recreate → запис невідомого container ID не має безпечного автоматичного adopt; зупинений candidate та interlock зберігаються, потрібен новий перевірений operator plan.
Ruling: SQLite WAL status helper має writable coordination mount, але SQL connection mode=ro; реальна non-root регресія доводить відмову DELETE.
Ruling: native inventory acceptance запускається окремо від інших Docker suites; зміна inventory під час scan безпечно зупиняє операцію.

Completion: native fixture 261017-8055 PASS, pair20261017-080544, restore verified5cycles/3observations, pending0; 64 runtime files matched tested snapshot; production untouched.
