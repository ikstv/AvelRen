package ua.avelren.app.data

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters

internal suspend fun runFcmTokenSync(repository: InstallationRepository?): androidx.work.ListenableWorker.Result {
    if (repository == null) return androidx.work.ListenableWorker.Result.retry()
    return when (repository.syncPendingTokenOnce()) {
        PendingTokenSyncOutcome.NothingPending,
        PendingTokenSyncOutcome.Synced -> androidx.work.ListenableWorker.Result.success()
        is PendingTokenSyncOutcome.RetryableFailure -> androidx.work.ListenableWorker.Result.retry()
        is PendingTokenSyncOutcome.TerminalFailure -> androidx.work.ListenableWorker.Result.failure()
    }
}

class FcmTokenSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters,
) : CoroutineWorker(appContext, workerParams) {
    override suspend fun doWork(): Result {
        val repository = (applicationContext as? ua.avelren.app.AvelRenApp)?.installationOrNull()
        return runFcmTokenSync(repository)
    }

    companion object {
        const val UNIQUE_WORK_NAME = "avelren_fcm_token_sync"
    }
}
