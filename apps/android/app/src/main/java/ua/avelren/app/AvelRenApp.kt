package ua.avelren.app

import android.app.Application
import android.content.Context
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import androidx.lifecycle.Lifecycle
import kotlinx.coroutines.tasks.await
import ua.avelren.app.data.Api
import ua.avelren.app.data.CredentialStore
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.FcmTokenProvider
import ua.avelren.app.data.DevicePendingFcmTokenStore
import ua.avelren.app.data.InstallationApi
import ua.avelren.app.data.InstallationRepository
import ua.avelren.app.data.WorkManagerFcmTokenRetryScheduler
import ua.avelren.app.data.ProtectedLoad
import ua.avelren.app.notify.NotificationReconciler
import ua.avelren.app.notify.Notifications
import ua.avelren.app.notify.SurgeAckWorker
import ua.avelren.app.notify.SurgeVoiceAssets
import ua.avelren.app.notify.SurgeVoiceChannels
import ua.avelren.app.notify.SurgeLocalStore
import ua.avelren.app.notify.VoicePreparation
import ua.avelren.app.data.SurgeRepository
import ua.avelren.app.data.InstallationState

/**
 * Owner of the process-scoped [InstallationRepository] — the single source of
 * truth about the installation. Previously registration/recovery lived here and
 * were duplicated in `AvelRenMessagingService`, while the UI read `DeviceStore`
 * directly. Now all paths (cold start, FCM token, 401 recovery, protected calls)
 * converge in the repository.
 */
class AvelRenApp : Application() {

    /** A single SupervisorJob scope for the whole process — no scattered CoroutineScope instances. */
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var voiceRecovery: Job? = null
    private fun recoverVoices() {
        if (!BuildConfig.ENABLE_PUSH || installation.state.value !is InstallationState.Ready ||
            !ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) return
        voiceRecovery?.cancel()
        voiceRecovery = appScope.launch {
            try {
                val repository = SurgeRepository(installation)
                val catalogue = repository.checkpoints()
                val subscriptions = repository.subscriptions()
                val assets = SurgeVoiceAssets(this@AvelRenApp)
                for (sub in subscriptions.filter { it.forecast_enabled || it.fact_enabled }) {
                    val cp = catalogue.firstOrNull { it.checkpoint_id == sub.checkpoint_id } ?: continue
                    when (val result = assets.prepare(cp.checkpoint_id, cp.title)) {
                        is VoicePreparation.Ready -> result.voices.forEach { SurgeVoiceChannels.ensure(this@AvelRenApp, it, cp.title) }
                        is VoicePreparation.Failure -> SurgeLocalStore(this@AvelRenApp).setVoiceProblem(result.reason)
                    }
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { SurgeLocalStore(this@AvelRenApp).setVoiceProblem("voice_not_ready") }
        }
    }

    private var installationRef: InstallationRepository? = null
    val installation: InstallationRepository
        get() = checkNotNull(installationRef)

    fun installationOrNull(): InstallationRepository? = installationRef

    override fun onCreate() {
        super.onCreate()

        // Create the channel right away: if it does not exist at the moment of
        // the first push, the notification simply will not appear.
        Notifications.ensureChannel(this)

        val ctx: Context = this
        installationRef = InstallationRepository(
            api = object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials =
                    Api.registerDevice(fcmToken)

                override suspend fun updateToken(
                    creds: DeviceStore.Credentials,
                    fcmToken: String,
                ) = Api.updateToken(creds, fcmToken)

                override fun isStaleInstallation(exc: Throwable): Boolean =
                    Api.isStaleInstallation(exc)
            },
            store = object : CredentialStore {
                override fun load(): DeviceStore.Credentials? = DeviceStore.credentials(ctx)
                override fun save(creds: DeviceStore.Credentials) =
                    DeviceStore.saveCredentials(ctx, creds)
                override fun clear() = DeviceStore.clearCredentials(ctx)
            },
            tokens = object : FcmTokenProvider {
                override suspend fun currentToken(): String =
                    FirebaseMessaging.getInstance().token.await()
            },
            scope = appScope,
            pendingTokens = DevicePendingFcmTokenStore(ctx),
            retryScheduler = WorkManagerFcmTokenRetryScheduler(ctx),
        )
        // A connected side-by-side APK exercises the real public API and UI,
        // but must not create a second production device/FCM identity.
        if (!BuildConfig.ENABLE_PUSH) return
        installation.start()
        appScope.launch { SurgeAckWorker.recover(ctx) }

        // Reconcile on EVERY new Ready (including after a recovery re-registration).
        // Closes the startup race (A-02): foreground onResume could fire before
        // credentials appeared and that reconcile returned early; now the
        // Initializing→Ready transition itself triggers reconciliation. A mutex in
        // the reconciler deduplicates against the foreground path.
        appScope.launch {
            ProtectedLoad.observe(installation.state) {
                NotificationReconciler.reconcile(ctx, installation)
                kotlinx.coroutines.withContext(Dispatchers.Main.immediate) { recoverVoices() }
            }
        }

        // Reconciliation on return to foreground (A-02, layer 2): if a
        // cancel-push was lost, reconcile the shown notifications against the
        // server. At the application level, not the Compose screen: this is not UI state.
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onResume(owner: LifecycleOwner) {
                    recoverVoices()
                    appScope.launch {
                        SurgeAckWorker.recover(ctx)
                        NotificationReconciler.reconcile(ctx, installation)
                    }
                }
                override fun onPause(owner: LifecycleOwner) { voiceRecovery?.cancel(); voiceRecovery = null }
            }
        )
    }

    /** The FCM service delegates here — all register/recovery is centralized in the repository. */
    fun handleNewFcmToken(token: String) {
        appScope.launch { installation.onNewFcmToken(token) }
    }

    /**
     * Launch short background work in the application scope (e.g. a server-ack
     * from `AckReceiver`), so components do not spawn their own `CoroutineScope`.
     */
    fun launchInScope(block: suspend () -> Unit) {
        appScope.launch { block() }
    }

    companion object {
        fun from(context: Context): AvelRenApp =
            context.applicationContext as AvelRenApp
    }
}
