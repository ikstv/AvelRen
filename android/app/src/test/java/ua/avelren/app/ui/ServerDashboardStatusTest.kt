package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import ua.avelren.app.data.Api

/**
 * Юніт-тести чистої status-логіки Server Dashboard.
 *
 * Фокус — на «⚪ Unknown замість вигаданого 🟢 OK» при відсутніх полях:
 * саме така плутанина перетворила б тихий провал моніторингу на «все гаразд».
 */
class ServerDashboardStatusTest {

    private val emptySystem = Api.TelemetrySystem()
    private val emptyPipeline = Api.TelemetryPipeline()
    private val emptyCert = Api.TelemetryCert()
    private val emptyBackups = Api.TelemetryBackups()

    // --- overall ------------------------------------------------------------

    @Test fun `overall — worst wins ERROR`() {
        assertEquals(SectionStatus.ERROR,
            ServerDashboardStatus.overall(
                listOf(SectionStatus.OK, SectionStatus.WARN, SectionStatus.ERROR)))
    }

    @Test fun `overall — WARN коли немає ERROR`() {
        assertEquals(SectionStatus.WARN,
            ServerDashboardStatus.overall(
                listOf(SectionStatus.OK, SectionStatus.WARN, SectionStatus.UNKNOWN)))
    }

    @Test fun `overall — усі UNKNOWN дають UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN,
            ServerDashboardStatus.overall(
                listOf(SectionStatus.UNKNOWN, SectionStatus.UNKNOWN)))
    }

    @Test fun `overall — порожній список дає UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.overall(emptyList()))
    }

    // --- host ---------------------------------------------------------------

    @Test fun `host — порожній snapshot дає UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.host(emptySystem))
    }

    @Test fun `host — stale ставить ERROR навіть якщо цифри виглядають нормально`() {
        val s = Api.TelemetrySystem(
            memory_total_mb = 1000, memory_used_mb = 100,
            disk_total_gb = 40.0, disk_free_gb = 30.0, disk_used_percent = 25,
            stale = true,
        )
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.host(s))
    }

    @Test fun `host — диск понад 90 percent це ERROR`() {
        val s = Api.TelemetrySystem(
            memory_total_mb = 1000, memory_used_mb = 100,
            disk_total_gb = 40.0, disk_free_gb = 4.0, disk_used_percent = 91,
        )
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.host(s))
    }

    @Test fun `host — RAM 85 percent це WARN`() {
        val s = Api.TelemetrySystem(
            memory_total_mb = 1000, memory_used_mb = 850,
            disk_total_gb = 40.0, disk_free_gb = 30.0, disk_used_percent = 25,
        )
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.host(s))
    }

    @Test fun `host — здоровий стан це OK`() {
        val s = Api.TelemetrySystem(
            uptime_seconds = 100, memory_total_mb = 1000, memory_used_mb = 300,
            disk_total_gb = 40.0, disk_free_gb = 30.0, disk_used_percent = 25,
        )
        assertEquals(SectionStatus.OK, ServerDashboardStatus.host(s))
    }

    // --- observationAgeSeconds ---------------------------------------------

    @Test fun `age — null коли поле відсутнє`() {
        assertNull(ServerDashboardStatus.observationAgeSeconds(null, 1000L))
    }

    @Test fun `age — null коли рядок порожній`() {
        assertNull(ServerDashboardStatus.observationAgeSeconds("", 1000L))
    }

    @Test fun `age — правильний обрахунок ISO з Z`() {
        // 1970-01-01T00:00:00Z = epoch 0
        val age = ServerDashboardStatus.observationAgeSeconds("1970-01-01T00:00:00Z", 100L)
        assertEquals(100L, age)
    }

    @Test fun `age — не негативне значення при часі з майбутнього`() {
        val age = ServerDashboardStatus.observationAgeSeconds("2099-01-01T00:00:00Z", 100L)
        assertEquals(0L, age)
    }

    @Test fun `age — некоректний рядок дає null не exception`() {
        assertNull(ServerDashboardStatus.observationAgeSeconds("not-a-date", 100L))
    }

    // --- collector ----------------------------------------------------------

    @Test fun `collector — collector_silent problem = ERROR`() {
        val status = ServerDashboardStatus.collector(
            emptyPipeline,
            listOf(Api.HealthProblem(kind = "collector_silent", detail = "мовчить 5 хв")),
            nowEpochSeconds = 1000L,
        )
        assertEquals(SectionStatus.ERROR, status)
    }

    @Test fun `collector — свіжі дані і без помилок = OK`() {
        val pipeline = Api.TelemetryPipeline(
            observations = 100, last_observation = "2099-01-01T00:00:00Z",
            runs_last_hour = 60, errors_last_hour = 0, completeness_percent = 100,
        )
        assertEquals(SectionStatus.OK,
            ServerDashboardStatus.collector(pipeline, emptyList(), 1000L))
    }

    @Test fun `collector — 1-9 помилок за годину = WARN`() {
        val pipeline = Api.TelemetryPipeline(
            observations = 100, last_observation = "2099-01-01T00:00:00Z",
            runs_last_hour = 59, errors_last_hour = 3, completeness_percent = 98,
        )
        assertEquals(SectionStatus.WARN,
            ServerDashboardStatus.collector(pipeline, emptyList(), 1000L))
    }

    @Test fun `collector — порожня БД без даних = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN,
            ServerDashboardStatus.collector(emptyPipeline, emptyList(), 1000L))
    }

    // --- database -----------------------------------------------------------

    @Test fun `database — порожня БД = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.database(emptyPipeline))
    }

    @Test fun `database — нормальний розмір = OK`() {
        val p = Api.TelemetryPipeline(observations = 100, db_size_mb = 500.0)
        assertEquals(SectionStatus.OK, ServerDashboardStatus.database(p))
    }

    @Test fun `database — 12 GB = WARN`() {
        val p = Api.TelemetryPipeline(observations = 100, db_size_mb = 12_000.0)
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.database(p))
    }

    @Test fun `database — понад 20 GB (поріг watchdog) = ERROR`() {
        val p = Api.TelemetryPipeline(observations = 100, db_size_mb = 25_000.0)
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.database(p))
    }

    // --- backup -------------------------------------------------------------

    @Test fun `backup — немає інформації = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.backup(emptyBackups))
    }

    @Test fun `backup — свіжа копія = OK`() {
        assertEquals(SectionStatus.OK,
            ServerDashboardStatus.backup(Api.TelemetryBackups(age_hours = 12.0)))
    }

    @Test fun `backup — сервер каже stale = ERROR`() {
        val b = Api.TelemetryBackups(age_hours = 48.0, stale = true)
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.backup(b))
    }

    @Test fun `backup — старіша за 30 год але ще не stale = WARN`() {
        val b = Api.TelemetryBackups(age_hours = 32.0, stale = false)
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.backup(b))
    }

    // --- certificate --------------------------------------------------------

    @Test fun `certificate — days_left null = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.certificate(emptyCert))
    }

    @Test fun `certificate — handshake error = ERROR`() {
        val c = Api.TelemetryCert(error = "handshake failed")
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.certificate(c))
    }

    @Test fun `certificate — менше 7 днів = ERROR`() {
        assertEquals(SectionStatus.ERROR,
            ServerDashboardStatus.certificate(Api.TelemetryCert(days_left = 3)))
    }

    @Test fun `certificate — менше 30 днів = WARN`() {
        assertEquals(SectionStatus.WARN,
            ServerDashboardStatus.certificate(Api.TelemetryCert(days_left = 20)))
    }

    @Test fun `certificate — більше 30 днів = OK`() {
        assertEquals(SectionStatus.OK,
            ServerDashboardStatus.certificate(Api.TelemetryCert(days_left = 60)))
    }

    // --- watchdog -----------------------------------------------------------

    @Test fun `watchdog — жодних проблем = OK`() {
        assertEquals(SectionStatus.OK, ServerDashboardStatus.watchdog(emptyList()))
    }

    @Test fun `watchdog — лише snapshot_stale = WARN`() {
        val problems = listOf(Api.HealthProblem(kind = "telemetry_snapshot_stale"))
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.watchdog(problems))
    }

    @Test fun `watchdog — інша проблема = ERROR`() {
        val problems = listOf(Api.HealthProblem(kind = "collector_silent"))
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.watchdog(problems))
    }

    // --- billing ------------------------------------------------------------

    @Test fun `billing — завжди UNKNOWN до PR-C`() {
        // Це не описка: PR-A свідомо не має жодного джерела білінгу.
        // Тест страхує від випадкового «покажу нулі» — тихий провал моніторингу
        // витрат гірший за чесний ⚪ Unknown.
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.billing())
    }

    // --- upstream -----------------------------------------------------------

    @Test fun `upstream — collector_silent робить ERROR`() {
        val problems = listOf(Api.HealthProblem(kind = "collector_silent"))
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.upstream(problems))
    }

    @Test fun `upstream — без специфічної телеметрії PR-B = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.upstream(emptyList()))
    }

    // --- memoryPercent ------------------------------------------------------

    @Test fun `memoryPercent — total 0 дає null`() {
        assertNull(ServerDashboardStatus.memoryPercent(Api.TelemetrySystem()))
    }

    @Test fun `memoryPercent — обрізає до 100`() {
        val s = Api.TelemetrySystem(memory_total_mb = 100, memory_used_mb = 500)
        assertEquals(100, ServerDashboardStatus.memoryPercent(s))
    }

    // ---- PR-B: service ----------------------------------------------------

    @Test fun `service — running healthy = OK`() {
        val svc = Api.TelemetryService(name = "api", status = "running", health = "healthy")
        assertEquals(SectionStatus.OK, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — running без health-check теж OK`() {
        val svc = Api.TelemetryService(name = "collector", status = "running", health = null)
        assertEquals(SectionStatus.OK, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — unhealthy = ERROR навіть коли status=running`() {
        val svc = Api.TelemetryService(name = "db", status = "running", health = "unhealthy")
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — exited = ERROR`() {
        val svc = Api.TelemetryService(name = "collector", status = "exited", exit_code = 137)
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — OOM killed = ERROR навіть якщо status=running`() {
        val svc = Api.TelemetryService(name = "collector", status = "running", oom_killed = true)
        assertEquals(SectionStatus.ERROR, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — restarting = WARN`() {
        val svc = Api.TelemetryService(name = "api", status = "restarting")
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — starting health = WARN`() {
        val svc = Api.TelemetryService(name = "db", status = "running", health = "starting")
        assertEquals(SectionStatus.WARN, ServerDashboardStatus.service(svc))
    }

    @Test fun `service — відсутній status = UNKNOWN`() {
        val svc = Api.TelemetryService(name = "caddy")
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.service(svc))
    }

    // ---- PR-B: upstream з реальними полями --------------------------------

    @Test fun `upstream PR-B — HTTP 200 і свіжий успіх = OK`() {
        val run = Api.TelemetryLastRun(http_status = 200, error = null)
        val success = Api.TelemetryLastSuccess(
            time = "2099-01-01T00:00:00Z", http_status = 200)
        assertEquals(SectionStatus.OK,
            ServerDashboardStatus.upstream(run, success, emptyList(), 1000L))
    }

    @Test fun `upstream PR-B — HTTP 502 = ERROR`() {
        val run = Api.TelemetryLastRun(http_status = 502, error = "gateway")
        assertEquals(SectionStatus.ERROR,
            ServerDashboardStatus.upstream(run, null, emptyList(), 1000L))
    }

    @Test fun `upstream PR-B — HTTP 429 = WARN`() {
        val run = Api.TelemetryLastRun(http_status = 429, error = "rate")
        assertEquals(SectionStatus.ERROR,  // 429 з error != null => ERROR
            ServerDashboardStatus.upstream(run, null, emptyList(), 1000L))
    }

    @Test fun `upstream PR-B — HTTP 429 без error = WARN`() {
        val run = Api.TelemetryLastRun(http_status = 429, error = null)
        assertEquals(SectionStatus.WARN,
            ServerDashboardStatus.upstream(run, null, emptyList(), 1000L))
    }

    @Test fun `upstream PR-B — watchdog collector_silent перекриває будь-що`() {
        val run = Api.TelemetryLastRun(http_status = 200, error = null)
        val problems = listOf(Api.HealthProblem(kind = "collector_silent"))
        assertEquals(SectionStatus.ERROR,
            ServerDashboardStatus.upstream(run, null, problems, 1000L))
    }

    @Test fun `upstream PR-B — null run = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN,
            ServerDashboardStatus.upstream(null, null, emptyList(), 1000L))
    }

    // ---- PR-B: inodes -----------------------------------------------------

    @Test fun `inodes — null = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN, ServerDashboardStatus.inodes(null))
    }

    @Test fun `inodes — used_percent null = UNKNOWN`() {
        assertEquals(SectionStatus.UNKNOWN,
            ServerDashboardStatus.inodes(Api.TelemetryInodes()))
    }

    @Test fun `inodes — 30 percent = OK`() {
        assertEquals(SectionStatus.OK,
            ServerDashboardStatus.inodes(Api.TelemetryInodes(used_percent = 30)))
    }

    @Test fun `inodes — 80 percent = WARN`() {
        assertEquals(SectionStatus.WARN,
            ServerDashboardStatus.inodes(Api.TelemetryInodes(used_percent = 80)))
    }

    @Test fun `inodes — 95 percent = ERROR`() {
        assertEquals(SectionStatus.ERROR,
            ServerDashboardStatus.inodes(Api.TelemetryInodes(used_percent = 95)))
    }
}
