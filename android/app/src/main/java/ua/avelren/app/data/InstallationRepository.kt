package ua.avelren.app.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filterIsInstance
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * Єдине джерело істини про стан installation у процесі (AND-1).
 *
 * До цього registration/recovery був розмазаний: `AvelRenApp` стартував
 * реєстрацію, `AvelRenMessagingService` тримав власну копію 401-recovery, а UI
 * напряму читав `DeviceStore.credentials()` — і на холодному старті не бачив
 * появу пари, бо SharedPreferences не observable. Тепер усе проходить тут:
 *
 *   * `state` (StateFlow) — lifecycle/auth-readiness для UI (без secret);
 *   * `authenticatedCall` — єдиний protected-шлях із 401-recovery;
 *   * `onNewFcmToken` — FCM делегує сюди, без дубльованої логіки.
 *
 * `Ready` означає **auth-ready**, а не «FCM гарантовано синхронізований»: якщо
 * персистовані credentials уже є, тимчасовий збій `FirebaseMessaging` не блокує
 * protected UI — пара може бути цілком валідною. Токен синхронізуємо окремо; на
 * 401 переходимо у recovery.
 *
 * `DeviceStore` лишається persistence-адаптером (шифроване сховище); цей клас
 * НЕ дублює його, а координує мутації через один `Mutex`, щоб паралельні
 * cold-start / FCM / recovery не зробили два `POST /devices`.
 */
class InstallationRepository(
    private val api: InstallationApi,
    private val store: CredentialStore,
    private val tokens: FcmTokenProvider,
    private val scope: CoroutineScope,
) {
    private val _state = MutableStateFlow<InstallationState>(InstallationState.Initializing)
    val state: StateFlow<InstallationState> = _state.asStateFlow()

    // Один coordination gate на ВСІ мутації installation: initialize, fresh
    // registration, onNewFcmToken і 401-recovery. business-`block` у
    // authenticatedCall виконується ПОЗА mutex — серіалізуємо лише зміну пари.
    private val mutex = Mutex()

    @Volatile
    private var creds: DeviceStore.Credentials? = null

    /** Запуск ініціалізації у application-scope (викликати з Application.onCreate). */
    fun start() {
        scope.launch { initialize() }
    }

    /**
     * Стартовий шлях. `internal`, щоб тести цього ж модуля викликали напряму;
     * production-callers бачать `state`/`start`/`onNewFcmToken`/`authenticatedCall`.
     */
    internal suspend fun initialize() = mutex.withLock {
        val existing = store.load()
        if (existing != null) {
            // Персистована пара — вважаємо auth-ready одразу, ще до FCM-синку.
            creds = existing
            _state.value = InstallationState.Ready(existing.deviceId)

            val token = runCatching { tokens.currentToken() }.getOrNull() ?: return@withLock
            try {
                api.updateToken(existing, token)
            } catch (e: Throwable) {
                if (api.isStaleInstallation(e)) {
                    // 401 = сервер відкинув пару (напр. DB restore). Пара
                    // насправді невалідна → мусимо перереєструватись.
                    runCatching { registerFreshLocked(token) }.onFailure {
                        invalidateLocked("перереєстрація не вдалася: ${it.message}")
                    }
                }
                // не-401 (offline/5xx): пара валідна, лишаємось Ready.
            }
        } else {
            // Fresh install: без FCM-токена немає з чим робити POST /devices.
            val token = runCatching { tokens.currentToken() }.getOrNull()
            if (token == null) {
                _state.value = InstallationState.Unavailable("немає FCM-токена для реєстрації")
                return@withLock
            }
            runCatching { registerFreshLocked(token) }.onFailure {
                invalidateLocked("реєстрація не вдалася: ${it.message}")
            }
        }
    }

    /** FCM `onNewToken` делегує сюди — жодної окремої register/recovery логіки в сервісі. */
    suspend fun onNewFcmToken(token: String) = mutex.withLock {
        val existing = creds ?: store.load()
        if (existing == null) {
            runCatching { registerFreshLocked(token) }.onFailure {
                invalidateLocked("реєстрація не вдалася: ${it.message}")
            }
        } else {
            creds = existing
            try {
                api.updateToken(existing, token)
            } catch (e: Throwable) {
                if (api.isStaleInstallation(e)) {
                    runCatching { registerFreshLocked(token) }.onFailure {
                        invalidateLocked("перереєстрація не вдалася: ${it.message}")
                    }
                }
            }
        }
    }

    /**
     * Виконати protected-операцію з поточними credentials. На 401 — атомарний
     * recovery (одна нова installation на всіх concurrent-викликачів) і РІВНО
     * один retry. Другий 401 у retry пробрасується — жодного loop.
     */
    suspend fun <T> authenticatedCall(block: suspend (DeviceStore.Credentials) -> T): T {
        val c = currentOrRegister() ?: error("installation недоступна")
        try {
            return block(c)
        } catch (e: Throwable) {
            if (!api.isStaleInstallation(e)) throw e
        }
        // 401 №1 → recovery. recoverFrom при провалі реєстрації сам переведе в
        // Unavailable і кине — тоді операція чесно падає, а не «висить» Ready.
        recoverFrom(c)
        val fresh = creds ?: error("installation недоступна після recovery")
        try {
            return block(fresh)
        } catch (e: Throwable) {
            if (api.isStaleInstallation(e)) {
                // 401 №2 на щойно зареєстрованій парі — сервер відкинув і її.
                // НЕ ретраїмо ще раз: installation недійсна.
                invalidateIf(fresh, "сервер відкинув свіжозареєстровану installation")
            }
            throw e
        }
    }

    private suspend fun currentOrRegister(): DeviceStore.Credentials? {
        creds?.let { return it }
        return mutex.withLock {
            creds ?: run {
                val token = runCatching { tokens.currentToken() }.getOrNull()
                    ?: return@withLock null
                runCatching { registerFreshLocked(token); creds }.getOrNull()
            }
        }
    }

    private suspend fun recoverFrom(stale: DeviceStore.Credentials) = mutex.withLock {
        // Dedup за ідентичністю пари: лише перший waiter, чия пара ще актуальна,
        // проводить recovery. Наступні бачать або нову пару (успіх), або null
        // (провал) — обидва != stale, тож другого POST /devices не буде.
        if (creds != stale) return@withLock
        try {
            val token = tokens.currentToken()
            registerFreshLocked(token)
        } catch (e: Throwable) {
            // Провал recovery: пара недійсна. Єдиний invalidate-path — щоб не
            // лишити брехливий Ready і щоб інші waiter'и отримали той самий
            // результат, а не пробували ще раз.
            invalidateLocked("recovery не вдалася: ${e.message}")
            throw e
        }
    }

    /** Мусить викликатися під `mutex`. Єдиний перехід у недоступний стан. */
    private fun invalidateLocked(reason: String) {
        store.clear()
        creds = null
        _state.value = InstallationState.Unavailable(reason)
    }

    /** Invalidate лише якщо поточна пара — та сама, що використав викликач. */
    private suspend fun invalidateIf(used: DeviceStore.Credentials, reason: String) =
        mutex.withLock {
            if (creds != used) return@withLock
            invalidateLocked(reason)
        }

    /**
     * Мусить викликатися під `mutex`. Реєструє нову пару. Стару in-memory `creds`
     * НЕ занулюємо до успіху: паралельні викликачі fast-path мають бачити
     * стабільну пару, а не транзієнтний null посеред реєстрації.
     */
    private suspend fun registerFreshLocked(token: String) {
        store.clear()
        val fresh = api.registerDevice(token)
        store.save(fresh)
        creds = fresh
        _state.value = InstallationState.Ready(fresh.deviceId)
    }
}

/** Стан installation для UI. Secret сюди НІКОЛИ не потрапляє — лише публічний id. */
sealed interface InstallationState {
    data object Initializing : InstallationState
    data class Ready(val deviceId: String) : InstallationState
    data class Unavailable(val reason: String) : InstallationState
}

/** Мережеві операції installation. Реальна реалізація делегує `Api`; у тестах — fake. */
interface InstallationApi {
    suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials
    suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String)
    fun isStaleInstallation(exc: Throwable): Boolean
}

/** Persistence пари. Реальна реалізація делегує `DeviceStore`; у тестах — fake. */
interface CredentialStore {
    fun load(): DeviceStore.Credentials?
    fun save(creds: DeviceStore.Credentials)
    fun clear()
}

/** Джерело FCM-токена. Реальна реалізація — `FirebaseMessaging`; у тестах — fake. */
interface FcmTokenProvider {
    suspend fun currentToken(): String
}

/**
 * Координатор protected-завантаження для UI (тестований JVM-seam замість
 * instrumented Compose). Запускає [onReady] щоразу, коли installation стає
 * `Ready`; новий `Ready` (інший deviceId після recovery) ретригерить, тож UI
 * оновлює protected-дані без перезапуску процесу.
 */
object ProtectedLoad {
    suspend fun observe(
        state: StateFlow<InstallationState>,
        onReady: suspend (InstallationState.Ready) -> Unit,
    ) {
        state.filterIsInstance<InstallationState.Ready>()
            .distinctUntilChanged()
            .collect { onReady(it) }
    }
}
