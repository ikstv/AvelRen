package ua.avelren.app

import java.time.Instant
import ua.avelren.app.data.*

enum class PreviewScenario(val label: String) {
    EMPTY("Порожньо"), FORECAST("Прогноз"), FACT("Факт"), OFFLINE("Немає зв’язку"),
    FIVE_CHECKPOINTS("5 КПП"), FORECAST_UNAVAILABLE("Без прогнозу"),
}

/** Виключно локальні дані: клас не має HTTP, Firebase чи installation залежностей. */
class PreviewAppClient(
    initial: PreviewScenario = PreviewScenario.FORECAST,
    private val clock: () -> Instant = { Instant.now() },
) : AppScreenClient, SurgeMonitorClient {
    private var scenario = initial
    private var lastOnlineScenario = initial
    private val catalog = listOf(
        SurgeCheckpoint(17, "Чоп", "Угорщина", "🇭🇺", true, true, true),
        SurgeCheckpoint(6, "Краківець", "Польща", "🇵🇱", true, true, true),
        SurgeCheckpoint(1, "Ягодин", "Польща", "🇵🇱", true, true, true),
        SurgeCheckpoint(29, "Ягодин — порожні вантажівки", "Польща", "🇵🇱", true, true, true),
        SurgeCheckpoint(5, "Рава-Руська", "Польща", "🇵🇱", true, true, true),
        SurgeCheckpoint(7, "Тестовий КПП", "Польща", "🇵🇱", true, true, true),
    )
    private var selected = emptyList<SurgeSubscription>()
    private var thresholds = emptyList<Api.Subscription>()
    private var targets = emptyList<Api.EtaTarget>()
    private var nextId = clock().toEpochMilli()
    init { setScenario(initial) }

    fun setScenario(value: PreviewScenario) {
        val recovering = scenario == PreviewScenario.OFFLINE && value == lastOnlineScenario
        scenario = value
        if (value == PreviewScenario.OFFLINE) return
        if (recovering) return
        lastOnlineScenario = value
        thresholds = emptyList(); targets = emptyList()
        selected = when (value) {
            PreviewScenario.EMPTY -> emptyList()
            PreviewScenario.FIVE_CHECKPOINTS -> catalog.take(5).map { subscription(it) }
            else -> listOf(subscription(catalog.first()))
        }
    }
    private fun online() { check(scenario != PreviewScenario.OFFLINE) { "Тест: немає зв’язку" } }
    private fun checkpoint(id: Int) = catalog.first { it.checkpoint_id == id }
    private fun subscription(cp: SurgeCheckpoint): SurgeSubscription {
        val fact = scenario == PreviewScenario.FACT
        val kind = if (fact) "surge_started" else "surge_forecast"
        val alert = SurgeAlert(
            nextId++, nextId++, cp.checkpoint_id, kind, clock().plusSeconds(3600).toString(),
            cp.title, if (fact) "Почалось зростання черги: ${cp.title}" else "Можливий початок масової реєстрації: ${cp.title}",
            growth_5m = if (fact) 25 else null,
        )
        return SurgeSubscription(cp.checkpoint_id, cp.title, scenario != PreviewScenario.FORECAST_UNAVAILABLE,
            true, if (scenario == PreviewScenario.FORECAST_UNAVAILABLE) emptyList() else listOf(alert))
    }
    override suspend fun checkpoints(): List<SurgeCheckpoint> {
        online()
        return catalog.map { it.copy(forecast_supported = scenario != PreviewScenario.FORECAST_UNAVAILABLE,
            observed_at = clock().toString()) }
    }
    override suspend fun subscriptions(): List<SurgeSubscription> { online(); return selected }
    override suspend fun snapshot(checkpointId: Int): SurgeStatus {
        online(); checkpoint(checkpointId)
        return SurgeStatus(checkpointId, if (scenario == PreviewScenario.FACT) "started" else "risk",
            issued_at = clock().toString(), window_start = clock().plusSeconds(3600).toString(),
            window_end = clock().plusSeconds(7200).toString(), expires_at = clock().plusSeconds(3600).toString(),
            forecast_supported = scenario != PreviewScenario.FORECAST_UNAVAILABLE)
    }
    override suspend fun setSubscription(checkpointId: Int, forecast: Boolean, fact: Boolean) {
        online()
        val cp = checkpoint(checkpointId)
        check(selected.any { it.checkpoint_id == checkpointId } || selected.size < 5) { "Максимум 5 КПП" }
        selected = selected.filterNot { it.checkpoint_id == checkpointId } +
            SurgeSubscription(checkpointId, cp.title, forecast, fact)
    }
    override suspend fun removeSubscription(checkpointId: Int) { online(); selected = selected.filterNot { it.checkpoint_id == checkpointId } }
    fun acknowledge(id: Long) { selected = selected.map { it.copy(alerts = it.alerts.filterNot { alert -> alert.surge_alert_id == id }) } }
    override suspend fun workload(): List<Api.Workload> {
        online()
        return catalog.mapIndexed { index, cp -> Api.Workload(cp.checkpoint_id, cp.title, cp.flag_emoji,
            40 + index * 10, 3600, false, clock().plusSeconds(3600).toString(), clock().toString()) }
    }
    override suspend fun serverStatus(): PublicServerStatus { online(); return PublicServerStatus() }
    override suspend fun history(checkpointId: Int): Api.History {
        online(); checkpoint(checkpointId)
        return Api.History(points = (0..59).map { Api.HistoryPoint(clock().minusSeconds((59L - it) * 60).toString(), 30 + it / 3) })
    }
    override suspend fun forecast(checkpointId: Int): Api.Forecast {
        online(); checkpoint(checkpointId)
        return Api.Forecast(checkpointId, "ready", 8.0, 4, count_points = (0..23).map {
            Api.CountForecastPoint(clock().plusSeconds(it * 3600L).toString(), 30, 40 + it, 80, 20)
        })
    }
    override suspend fun monitors(): Pair<List<Api.Subscription>, List<Api.EtaTarget>> { online(); return thresholds to targets }
    override suspend fun subscribe(checkpointId: Int, threshold: Int) {
        online(); val cp = checkpoint(checkpointId)
        thresholds = thresholds + Api.Subscription(nextId++, checkpointId, cp.title, cp.flag_emoji, threshold)
    }
    override suspend fun unsubscribe(subscriptionId: Long) { online(); thresholds = thresholds.filterNot { it.id == subscriptionId } }
    override suspend fun createEtaTarget(checkpointId: Int, targetAtIso: String) {
        online(); val cp = checkpoint(checkpointId)
        targets = targets + Api.EtaTarget(nextId++, checkpointId, cp.title, cp.flag_emoji, targetAtIso, 300, true)
    }
    override suspend fun deleteEtaTarget(targetId: Long) { online(); targets = targets.filterNot { it.id == targetId } }
}
