package ua.avelren.app.ui

import ua.avelren.app.data.Api

/**
 * Чиста логіка обчислення статусів секцій Server Dashboard.
 *
 * Винесено з `ServerDashboard.kt` окремо, щоб покрити юніт-тестами без Compose:
 * основна ризикова частина — коли поле відсутнє (⚪ Unknown vs 🟢 OK vs 🔴).
 * Плутанина тут перетворює «сервер не відповів» на «все гаразд», що і є
 * найгірший клас багу для моніторингу.
 *
 * Жоден метод не вигадує значення. Якщо даних немає — статус UNKNOWN, а не OK.
 */

enum class SectionStatus(val emoji: String) {
    OK("🟢"),       // 🟢
    WARN("🟡"),     // 🟡
    ERROR("🔴"),    // 🔴
    UNKNOWN("⚪"),        // ⚪
}

object ServerDashboardStatus {

    /** poll_interval сервера — 60 сек (див. app/src/avelren/config.py). Три
     *  пропущені цикли = «collector_silent» на сервері; використовуємо той
     *  самий поріг, щоб клієнт і watchdog не розходились. */
    const val POLL_INTERVAL_SECONDS = 60L
    const val COLLECTOR_STALE_THRESHOLD_SECONDS = POLL_INTERVAL_SECONDS * 3

    /** Свіжість host-snapshot: сервер вважає протухлим після 5 хв. */
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
        // stale=true — host-snapshot не оновлюється, host-метрики застарілі.
        // Не показуємо OK по протухлих числах: це головний ризик моніторингу.
        if (system.stale == true) return SectionStatus.ERROR

        val disk = system.disk_used_percent
        val memPercent = memoryPercent(system)

        return when {
            disk != null && disk >= 90 -> SectionStatus.ERROR
            memPercent != null && memPercent >= 90 -> SectionStatus.ERROR
            disk != null && disk >= 75 -> SectionStatus.WARN
            memPercent != null && memPercent >= 80 -> SectionStatus.WARN
            system.reboot_required && (system.reboot_pending_days ?: 0) >= 3 -> SectionStatus.WARN
            // Без snapshot взагалі (жоден показник не заповнений) — UNKNOWN.
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

    /** Вік останнього спостереження в секундах. null — сервер не віддав поле
     *  (старий backend) або observations порожній. Обчислюється відносно `now`,
     *  який передається зовні — це робить функцію чистою (тест не залежить від
     *  системного годинника). */
    fun observationAgeSeconds(lastObservationIso: String?, nowEpochSeconds: Long): Long? {
        if (lastObservationIso.isNullOrBlank()) return null
        // Приймаємо ISO-8601 з "Z" або без — сервер віддає у форматі psycopg,
        // який може мати обидва варіанти. Помилка парсингу = null (не OK).
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
        // Watchdog уже вирішив, що збирач мовчить — приймаємо його вердикт як істину.
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
        // Watchdog алертить при >20 GB — тримаємо той самий поріг у клієнті.
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
        // telemetry_snapshot_stale — жовтий тільки в блоці watchdog: сама
        // помилка вже піднімає Host в ERROR, тут не повторюємо суворість.
        val onlyStale = problems.all { it.kind == "telemetry_snapshot_stale" }
        return if (onlyStale) SectionStatus.WARN else SectionStatus.ERROR
    }

    /** Джерело білінгу з'явиться в PR-C (Hetzner read-only token). До того
     *  чесніше показувати UNKNOWN, ніж вигадувати нулі чи «немає витрат». */
    fun billing(): SectionStatus = SectionStatus.UNKNOWN

    /** ЄЧерга-специфічної телеметрії ще немає в /admin/telemetry (додається у
     *  PR-B). Єдиний непрямий сигнал — collector_silent, який уже підіймає
     *  Collector в ERROR. */
    fun upstream(problems: List<Api.HealthProblem>): SectionStatus {
        if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
            return SectionStatus.ERROR
        }
        return SectionStatus.UNKNOWN
    }

    /** Per-service статус приходить у PR-B. Поки виводимо з непрямих сигналів:
     *  api — 🟢 (сам факт, що telemetry прийшла), db — 🟢 (запит до pipeline
     *  повернувся), інші — ⚪ Unknown. */
    fun apiService(): SectionStatus = SectionStatus.OK

    fun dbService(pipeline: Api.TelemetryPipeline): SectionStatus =
        if (pipeline.observations > 0 || pipeline.db_size_mb > 0.0) SectionStatus.OK
        else SectionStatus.UNKNOWN

    // ---- PR-B: реальні per-container статуси і upstream з бекенду ----

    /** Статус одного контейнера з `docker inspect` (whitelist полів).
     *  Пороги свідомо строгі: `unhealthy` — одразу ERROR, `restarting` — WARN
     *  (перезапуск нормальний під навантаженням, але часто = проблема).
     *  Відсутність поля → UNKNOWN, а не OK. */
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

    /** ЄЧерга з реальним HTTP-статусом (PR-B заміняє попередній UNKNOWN). */
    fun upstream(
        lastRun: Api.TelemetryLastRun?,
        lastSuccess: Api.TelemetryLastSuccess?,
        problems: List<Api.HealthProblem>,
        nowEpochSeconds: Long,
    ): SectionStatus {
        // Watchdog уже підняв тривогу — вірити йому в першу чергу.
        if (problems.any { it.kind == "collector_silent" || it.kind == "no_data" }) {
            return SectionStatus.ERROR
        }
        if (lastRun == null) return SectionStatus.UNKNOWN

        val http = lastRun.http_status
        val successAge = observationAgeSeconds(lastSuccess?.time, nowEpochSeconds)

        return when {
            // Будь-яка помилка в останньому циклі — ERROR, незалежно від HTTP.
            // Раніше умова була `error != null && http != 200`, і сценарій
            // «HTTP 200 з body-parse-помилкою» (collector записує
            // http_status=200, error="parse failed") виглядав як 🟢 OK. Це
            // саме той клас багу, від якого нас страхує інваріант «⚪ ≠ 🟢».
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

    /** Inode usage. Заповнена filesystem за inode виглядає як «диску купа»,
     *  а create() починає повертати ENOSPC — тому окремий сигнал. */
    fun inodes(inodes: Api.TelemetryInodes?): SectionStatus {
        val pct = inodes?.used_percent ?: return SectionStatus.UNKNOWN
        return when {
            pct >= 90 -> SectionStatus.ERROR
            pct >= 75 -> SectionStatus.WARN
            else -> SectionStatus.OK
        }
    }
}
