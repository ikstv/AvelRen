package ua.avelren.app.data

import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope

/** Обидва запити належать одному завантаженню; частковий результат не публікується. */
internal suspend fun <S, T> loadMonitorSnapshot(
    subscriptions: suspend () -> List<S>,
    etaTargets: suspend () -> List<T>,
): Pair<List<S>, List<T>> = coroutineScope {
    val subscriptionsResult = async { subscriptions() }
    val targetsResult = async { etaTargets() }
    subscriptionsResult.await() to targetsResult.await()
}
