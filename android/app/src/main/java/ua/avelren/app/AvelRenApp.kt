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

/**
 * Власник процес-скоупного [InstallationRepository] — єдиного джерела істини про
 * installation. Раніше реєстрація/recovery жили тут і дублювалися в
 * `AvelRenMessagingService`, а UI напряму читав `DeviceStore`. Тепер усі шляхи
 * (cold start, FCM-токен, 401-recovery, protected-виклики) сходяться в repository.
 */
class AvelRenApp : Application() {

    /** Один SupervisorJob-скоуп на весь процес — без розсипаних CoroutineScope. */
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var installationRef: InstallationRepository? = null
    val installation: InstallationRepository
        get() = checkNotNull(installationRef)

    fun installationOrNull(): InstallationRepository? = installationRef

    override fun onCreate() {
        super.onCreate()

        // Канал створюємо одразу: якщо його не буде на момент першого пуша,
        // сповіщення просто не з'явиться.
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
        installation.start()

        // Reconcile на КОЖЕН новий Ready (у т.ч. після recovery-перереєстрації).
        // Закриває startup-race (A-02): foreground onResume міг спрацювати ще до
        // появи credentials і той reconcile вийшов рано; тепер перехід
        // Initializing→Ready сам запускає звірку. Mutex у reconciler дедупить із
        // foreground-шляхом.
        appScope.launch {
            ProtectedLoad.observe(installation.state) {
                NotificationReconciler.reconcile(ctx, installation)
            }
        }

        // Reconciliation при поверненні у foreground (A-02, шар 2): якщо
        // cancel-push загубився, звіряємо показані сповіщення з сервером. На
        // рівні application, а не Compose-екрана: це не UI-стан.
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onResume(owner: LifecycleOwner) {
                    appScope.launch { NotificationReconciler.reconcile(ctx, installation) }
                }
            }
        )
    }

    /** FCM-сервіс делегує сюди — весь register/recovery централізовано в repository. */
    fun handleNewFcmToken(token: String) {
        appScope.launch { installation.onNewFcmToken(token) }
    }

    /**
     * Запуск короткої фонової роботи в application-scope (напр. server-ack із
     * `AckReceiver`), щоб компоненти не плодили власні `CoroutineScope`.
     */
    fun launchInScope(block: suspend () -> Unit) {
        appScope.launch { block() }
    }

    companion object {
        fun from(context: Context): AvelRenApp =
            context.applicationContext as AvelRenApp
    }
}
