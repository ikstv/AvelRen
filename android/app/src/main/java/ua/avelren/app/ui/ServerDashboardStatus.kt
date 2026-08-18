package ua.avelren.app.ui

import ua.avelren.app.data.Api

/**
 * Pure logic for computing the statuses of the Server Dashboard sections.
 *
 * Extracted separately from `ServerDashboard.kt` to cover it with unit tests
 * without Compose: the main risky part is when a field is missing
 * (⚪ Unknown vs 🟢 OK vs 🔴). Confusion here turns "the server did not respond"
 * into "all is well", which is the worst class of bug for monitoring.
 *
 * No method invents a value. If there is no data — the status is UNKNOWN, not OK.
 */

enum class SectionStatus(val emoji: String) {
    OK("🟢"),       // 🟢
    WARN("🟡"),     // 🟡
    ERROR("🔴"),    // 🔴
    UNKNOWN("⚪"),        // ⚪
}

object ServerDashboardStatus {

    /** The server's poll_interval is 60 s (see app/src/avelren/config.py). Three
     *  missed cycles = "collector_silent" on the server; we use the same threshold
     *  so the client and the watchdog do not diverge. */
    const val POLL_INTERVAL_SECONDS = 60L
    const val COLLECTOR_STALE_THRESHOLD_SECONDS = POLL_INTERVAL_SECONDS * 3

    /** Host-snapshot freshness: the server considers it stale after 5 min. */
    const val SNAPSHOT_STALE_SECONDS = 300

    fun overall(sections: List<SectionStatus>): SectionStatus {
        if (sections.isEmpty()) return SectionStatus.UNKNOWN
        return when {
            sections.any { it == SectionStatus.ERROR } -> SectionStatus.ERROR
            sections.any { it == SectionStatus.WARN } -> SectionStatus.WARN
            sections.all { it == SectionStatus.UNKNOWN } -> SectionStatus.UNKNOWN
            sections.any { it == SectionStatus.OK } -> SectionStatus.OK
            else -> SectionStatus.UNKNOWN
        }
    }

    fun host(system: Api.TelemetrySystem): SectionStatus {
        // stale=true — the host snapshot is not updating, the host metrics are stale.
        // We do not show OK on stale numbers: this is the main monitoring risk.
        if (system.stale == true) return SectionStatus.ERROR

        val disk = system.disk_used_percent
        val memPercent = memoryPercent(system)

        return when {
            disk != null && disk >= 90 -> SectionStatus.ERROR
            memPercent != null && memPercent >= 90 -> SectionStatus.ERROR
            disk != null && disk >= 75 -> SectionStatus.WARN
            memPercent != null && memPercent >= 80 -> SectionStatus.WARN
            system.reboot_required && (system.reboot_pending_days ?: 0) >= 3 -> SectionStatus.WARN
            // With no snapshot at all (not a single metric filled in) — UNKNOWN.
            disk == null && memPercent == null && system.uptime_seconds == null ->
                SectionStatus.UNKNOWN
            else -> SectionStatus.OK
        }
    }

    fun memoryPercent(system: Api.TelemetrySystem): Int? {
        val total = system.memory_total_mb
        if (total <= 0) return null
        return (system.memory_used_mb * 100 / total).coerceIn(0, 100)
    }

    /** The age of the last observation in seconds. null — the server did not return
     *  the field (old backend) or observations is empty. Computed relative to `now`,
     *  which is passed from outside — this makes the function pure (the test does not
     *  depend on the system clock). */
    fun observationAgeSeconds(lastObservationIso: String?, nowEpochSeconds: Long): Long? {
        if (lastObservationIso.isNullOrBlank()) return null
        // We accept ISO-8601 with or without "Z" — the server returns it in psycopg
        // format, which can have either variant. A parse error = null (not OK).
        return try {
            val instant = java.time.Instant.parse(
                if (lastObservationIso.endsWith("Z") || lastObservationIso.contains("+")) {
                    lastObservationIso
                } else {
                    lastObservationIso + "Z"
                }
            )
            (nowEpochSeconds - instant.epochSecond).coerceAtLeast(0)
        } catch (_: java.time.format.DateTimeParseException) {
            null
        }
    }

    fun collector(
        pipeline: Api.TelemetryPipeline,
        problems: List<Api.HealthProblem>,
        nowEpochSeconds: Long,
    ): SectionStatus {
        // The watchdog already decided the collector is silent — we take its verdict as truth.
        if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
            return SectionStatus.ERROR
        }
        if (problems.any { it.kind == "collector_errors" || it.kind == "derived_errors"
                || it.kind == "derived_stuck" }) {
            return SectionStatus.ERROR
        }

        val age = observationAgeSeconds(pipeline.last_observation, nowEpochSeconds)
        val errors = pipeline.errors_last_hour

        return when {
            age == null && pipeline.observations == 0L -> SectionStatus.UNKNOWN
            age != null && age > COLLECTOR_STALE_THRESHOLD_SECONDS -> SectionStatus.ERROR
            errors >= 10 -> SectionStatus.ERROR
            errors > 0 -> SectionStatus.WARN
            pipeline.completeness_percent < 90 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }

    fun database(pipeline: Api.TelemetryPipeline): SectionStatus {
        // The watchdog alerts at >20 GB — we keep the same threshold in the client.
        val sizeMb = pipeline.db_size_mb
        return when {
            sizeMb <= 0.0 && pipeline.observations == 0L -> SectionStatus.UNKNOWN
            sizeMb > 20_000 -> SectionStatus.ERROR
            sizeMb > 10_000 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }

    fun backup(backups: Api.TelemetryBackups): SectionStatus {
        val age = backups.age_hours
        return when {
            age == null -> SectionStatus.UNKNOWN
            backups.stale -> SectionStatus.ERROR
            age > 30 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }

    fun certificate(cert: Api.TelemetryCert): SectionStatus {
        if (cert.error != null) return SectionStatus.ERROR
        val days = cert.days_left ?: return SectionStatus.UNKNOWN
        return when {
            days < 7 -> SectionStatus.ERROR
            days < 30 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }

    fun watchdog(problems: List<Api.HealthProblem>): SectionStatus {
        if (problems.isEmpty()) return SectionStatus.OK
        // telemetry_snapshot_stale — yellow only in the watchdog block: the error
        // itself already raises Host to ERROR, we do not repeat the severity here.
        val onlyStale = problems.all { it.kind == "telemetry_snapshot_stale" }
        return if (onlyStale) SectionStatus.WARN else SectionStatus.ERROR
    }

    /** The billing source will appear in PR-C (a Hetzner read-only token). Until
     *  then it is more honest to show UNKNOWN than to invent zeros or "no spending". */
    fun billing(): SectionStatus = SectionStatus.UNKNOWN

    /** eCherha-specific telemetry is not yet in /admin/telemetry (added in PR-B).
     *  The only indirect signal is collector_silent, which already raises the
     *  Collector to ERROR. */
    fun upstream(problems: List<Api.HealthProblem>): SectionStatus {
        if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
            return SectionStatus.ERROR
        }
        return SectionStatus.UNKNOWN
    }

    /** Per-service status arrives in PR-B. For now we derive it from indirect
     *  signals: api — 🟢 (the very fact that telemetry arrived), db — 🟢 (the
     *  pipeline request returned), the rest — ⚪ Unknown. */
    fun apiService(): SectionStatus = SectionStatus.OK

    fun dbService(pipeline: Api.TelemetryPipeline): SectionStatus =
        if (pipeline.observations > 0 || pipeline.db_size_mb > 0.0) SectionStatus.OK
        else SectionStatus.UNKNOWN

    // ---- PR-B: real per-container statuses and upstream from the backend ----

    /** The status of a single container from `docker inspect` (a whitelist of fields).
     *  The thresholds are deliberately strict: `unhealthy` — immediately ERROR,
     *  `restarting` — WARN (a restart is normal under load, but is often = a problem).
     *  A missing field → UNKNOWN, not OK. */
    fun service(svc: Api.TelemetryService): SectionStatus {
        val status = svc.status ?: return SectionStatus.UNKNOWN
        val health = svc.health
        return when {
            status == "exited" || status == "dead" -> SectionStatus.ERROR
            status == "restarting" -> SectionStatus.WARN
            health == "unhealthy" -> SectionStatus.ERROR
            health == "starting" -> SectionStatus.WARN
            svc.oom_killed == true -> SectionStatus.ERROR
            status == "running" -> SectionStatus.OK
            else -> SectionStatus.UNKNOWN
        }
    }

    /** eCherha with the real HTTP status (PR-B replaces the previous UNKNOWN). */
    fun upstream(
        lastRun: Api.TelemetryLastRun?,
        lastSuccess: Api.TelemetryLastSuccess?,
        problems: List<Api.HealthProblem>,
        nowEpochSeconds: Long,
    ): SectionStatus {
        // The watchdog already raised the alarm — trust it first.
        if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
            return SectionStatus.ERROR
        }
        if (lastRun == null) return SectionStatus.UNKNOWN

        val http = lastRun.http_status
        val successAge = observationAgeSeconds(lastSuccess?.time, nowEpochSeconds)

        return when {
            // Any error in the last cycle — ERROR, regardless of HTTP.
            // The condition used to be `error != null && http != 200`, and the
            // scenario "HTTP 200 with a body-parse error" (the collector writes
            // http_status=200, error="parse failed") looked like 🟢 OK. This is
            // exactly the class of bug the invariant "⚪ ≠ 🟢" insures us against.
            // N1 review PR #34.
            lastRun.error != null -> SectionStatus.ERROR
            http != null && http >= 500 -> SectionStatus.ERROR
            http != null && http >= 400 -> SectionStatus.WARN
            successAge != null && successAge > COLLECTOR_STALE_THRESHOLD_SECONDS ->
                SectionStatus.WARN
            http == 200 -> SectionStatus.OK
            else -> SectionStatus.UNKNOWN
        }
    }

    /** Inode usage. A filesystem full on inodes looks like "plenty of disk",
     *  yet create() starts returning ENOSPC — hence a separate signal. */
    fun inodes(inodes: Api.TelemetryInodes?): SectionStatus {
        val pct = inodes?.used_percent ?: return SectionStatus.UNKNOWN
        return when {
            pct >= 90 -> SectionStatus.ERROR
            pct >= 75 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }
}
