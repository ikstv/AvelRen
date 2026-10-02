package ua.avelren.app.notify

import android.content.Context
import androidx.work.*
import androidx.work.await
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import ua.avelren.app.AvelRenApp
import ua.avelren.app.data.SurgeRepository

internal suspend fun syncSurgeAck(store: SurgeLocalStore, alertId: Long, ack: suspend (Long) -> Unit): Boolean {
    if (alertId !in store.pendingAcks()) return true
    return try {
        ack(alertId)
        store.confirmAck(alertId)
    } catch (e: CancellationException) { throw e }
    catch (_: Exception) { false }
}

class SurgeAckWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val id = inputData.getLong("alert_id", -1)
        if (id <= 0) return Result.failure()
        val store = SurgeLocalStore(applicationContext)
        if (id !in store.pendingAcks()) return Result.success()
        val installation = (applicationContext as? AvelRenApp)?.installationOrNull() ?: return Result.retry()
        val repository = SurgeRepository(installation)
        return if (syncSurgeAck(store, id, repository::ack)) Result.success() else Result.retry()
    }
    companion object {
        suspend fun enqueue(context: Context, alertId: Long) {
            val request = OneTimeWorkRequestBuilder<SurgeAckWorker>()
                .setInputData(workDataOf("alert_id" to alertId))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS).build()
            WorkManager.getInstance(context.applicationContext).enqueueUniqueWork(
                "avelren_surge_ack_$alertId", ExistingWorkPolicy.KEEP, request,
            ).await()
        }
        suspend fun recover(context: Context) {
            SurgeLocalStore(context).pendingAcks().forEach { enqueue(context, it) }
        }
    }
}
