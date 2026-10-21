package ua.avelren.app.data

import java.time.Instant
import kotlinx.coroutines.CancellationException

data class EditableMonitor(val id: Long, val checkpointId: Int, val threshold: Int? = null, val targetAt: String? = null)
sealed interface MonitorValue {
    data class Threshold(val threshold: Int) : MonitorValue
    data class Eta(val targetAt: String) : MonitorValue
}
enum class MonitorEditStatus { SUCCESS, NO_CHANGE, INVALID, STALE, DUPLICATE, LOAD_FAILED, CREATE_FAILED, PARTIAL }
data class MonitorEditResult(val status: MonitorEditStatus, val message: String)

private fun String.monitorInstant(): Instant? = runCatching { Instant.parse(this) }.getOrNull()

/** Сервер не має атомарної заміни: спочатку створюємо новий запис і лише потім видаляємо старий. */
suspend fun replaceMonitor(
    client: AppScreenClient,
    original: EditableMonitor,
    value: MonitorValue,
    now: Instant = Instant.now(),
): MonitorEditResult {
    fun result(status: MonitorEditStatus, message: String) = MonitorEditResult(status, message)
    val thresholdKind = original.threshold != null && original.targetAt == null
    val etaKind = original.threshold == null && original.targetAt?.monitorInstant() != null
    val newInstant = (value as? MonitorValue.Eta)?.targetAt?.monitorInstant()
    if (value is MonitorValue.Threshold && (!thresholdKind || value.threshold !in 50..400 || value.threshold % 50 != 0) ||
        value is MonitorValue.Eta && (!etaKind || newInstant == null || !newInstant.isAfter(now))) {
        return result(MonitorEditStatus.INVALID, "Оберіть поріг від 50 до 400 авто з кроком 50 або майбутній час відповідного моніторингу.")
    }
    if (value is MonitorValue.Threshold && value.threshold == original.threshold ||
        value is MonitorValue.Eta && newInstant == original.targetAt?.monitorInstant()) {
        return result(MonitorEditStatus.NO_CHANGE, "Значення не змінилося.")
    }
    val snapshot = try { client.monitors() } catch (e: CancellationException) { throw e } catch (_: Exception) {
        return result(MonitorEditStatus.LOAD_FAILED, "Не вдалося перевірити моніторинги на сервері. Старий моніторинг збережено.")
    }
    val exists = if (thresholdKind) snapshot.first.any { it.id == original.id && it.checkpoint_id == original.checkpointId && it.threshold == original.threshold }
        else snapshot.second.any { it.id == original.id && it.checkpoint_id == original.checkpointId && it.target_at.monitorInstant() == original.targetAt?.monitorInstant() }
    if (!exists) return result(MonitorEditStatus.STALE, "Цей моніторинг уже змінено або видалено. Оновіть список із сервера; змін не внесено.")
    val duplicate = when (value) {
        is MonitorValue.Threshold -> snapshot.first.any { it.checkpoint_id == original.checkpointId && it.threshold == value.threshold }
        is MonitorValue.Eta -> snapshot.second.any { it.checkpoint_id == original.checkpointId && it.target_at.monitorInstant() == newInstant }
    }
    if (duplicate) return result(MonitorEditStatus.DUPLICATE, "Моніторинг із таким значенням уже існує. Старий моніторинг збережено.")
    try {
        when (value) {
            is MonitorValue.Threshold -> client.subscribe(original.checkpointId, value.threshold)
            is MonitorValue.Eta -> client.createEtaTarget(original.checkpointId, value.targetAt)
        }
    } catch (e: CancellationException) { throw e } catch (_: Exception) {
        return result(MonitorEditStatus.CREATE_FAILED, "Не вдалося підтвердити створення нового моніторингу. Старий не видалено. Оновіть список перед повторною спробою.")
    }
    try {
        if (thresholdKind) client.unsubscribe(original.id) else client.deleteEtaTarget(original.id)
    } catch (e: CancellationException) { throw e } catch (_: Exception) {
        return result(MonitorEditStatus.PARTIAL, "Новий моніторинг створено, але видалення старого не підтверджено. Обидва можуть бути активні. Оновіть список із сервера й перевірте їх.")
    }
    return result(MonitorEditStatus.SUCCESS, "Моніторинг оновлено.")
}
