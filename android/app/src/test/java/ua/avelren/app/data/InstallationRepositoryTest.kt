package ua.avelren.app.data

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import ua.avelren.app.data.DeviceStore.Credentials

/**
 * Unit-тести централізованого installation-стану (AND-1). Мережа, FCM і
 * сховище замінені fakes — жодного Firebase/Android runtime.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InstallationRepositoryTest {

    /** Маркер 401 (stale installation). Реальний seam розпізнає його як 401. */
    private class Stale : RuntimeException()

    private class FakeApi : InstallationApi {
        var registerCount = 0
        var updateCount = 0
        var updateBehavior: (() -> Unit) = {}          // за замовч. — успіх
        var registerBehavior: (() -> Unit) = {}          // hook: напр. кинути
        val updatedTokens = mutableListOf<String>()

        override suspend fun registerDevice(fcmToken: String): Credentials {
            yield() // дати іншим корутинам дійти до mutex — для dedup-тесту
            registerBehavior()
            registerCount++
            return Credentials("device-$registerCount", "secret-$registerCount")
        }

        override suspend fun updateToken(creds: Credentials, fcmToken: String) {
            updateCount++
            updatedTokens += fcmToken
            updateBehavior()
        }

        override fun isStaleInstallation(exc: Throwable): Boolean = exc is Stale
    }

    private class FakeStore(seed: Credentials? = null) : CredentialStore {
        var current: Credentials? = seed
        var cleared = 0
        override fun load(): Credentials? = current
        override fun save(creds: Credentials) { current = creds }
        override fun clear() { current = null; cleared++ }
    }

    private class FakeTokens(
        private var token: String? = "fcm-token",
    ) : FcmTokenProvider {
        var fail = false
        override suspend fun currentToken(): String {
            if (fail) throw RuntimeException("play services offline")
            return token ?: throw RuntimeException("no token")
        }
    }

    private fun repo(
        api: InstallationApi,
        store: CredentialStore,
        tokens: FcmTokenProvider,
        scope: kotlinx.coroutines.CoroutineScope,
    ) = InstallationRepository(api, store, tokens, scope)

    // 1
    @Test
    fun `persisted credentials initialize to Ready and refresh token`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-A", "sec-A"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)

        r.initialize()

        assertTrue(r.state.value is InstallationState.Ready)
        assertEquals(0, api.registerCount)          // не реєструвались наново
        assertEquals(1, api.updateCount)            // токен синхронізовано
        assertEquals("dev-A", (r.state.value as InstallationState.Ready).deviceId)
    }

    // 2
    @Test
    fun `fresh install with no credentials registers and becomes Ready`() = runTest {
        val api = FakeApi()
        val store = FakeStore(null)
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)

        r.initialize()

        assertEquals(1, api.registerCount)
        assertTrue(r.state.value is InstallationState.Ready)
        assertEquals(Credentials("device-1", "secret-1"), store.current)
    }

    // 3
    @Test
    fun `state transitions Initializing to Ready observably`() = runTest(UnconfinedTestDispatcher()) {
        val api = FakeApi()
        val r = repo(api, FakeStore(null), FakeTokens("tok-1"), backgroundScope)

        val seen = mutableListOf<InstallationState>()
        // Unconfined: collector підписується одразу й ловить Initializing ДО initialize.
        val job = backgroundScope.launch { r.state.collect { seen += it } }

        assertEquals(InstallationState.Initializing, seen.first())
        r.initialize()
        job.cancel()

        assertTrue(seen.last() is InstallationState.Ready)
    }

    // 4
    @Test
    fun `startup updateToken 401 clears and re-registers to Ready`() = runTest {
        val api = FakeApi().apply { updateBehavior = { throw Stale() } }
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)

        r.initialize()

        assertEquals(1, store.cleared)
        assertEquals(1, api.registerCount)
        assertTrue(r.state.value is InstallationState.Ready)
        assertEquals("device-1", (r.state.value as InstallationState.Ready).deviceId)
    }

    // 5
    @Test
    fun `authenticatedCall recovers on 401 and retries original once`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()

        var attempts = 0
        val usedCreds = mutableListOf<Credentials>()
        val result = r.authenticatedCall { creds ->
            attempts++
            usedCreds += creds
            if (attempts == 1) throw Stale()
            "ok"
        }

        assertEquals("ok", result)
        assertEquals(2, attempts)                        // рівно один retry
        assertEquals(1, api.registerCount)               // одна нова installation
        assertEquals("dev-old", usedCreds[0].deviceId)   // спершу стара
        assertEquals("device-1", usedCreds[1].deviceId)  // потім свіжа
    }

    // 6
    @Test
    fun `authenticatedCall second 401 after retry fails without loop`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()

        var attempts = 0
        try {
            r.authenticatedCall<String> { _ -> attempts++; throw Stale() }
            throw AssertionError("мав кинути")
        } catch (e: Stale) {
            // очікувано
        }

        assertEquals(2, attempts)                // 1 оригінал + 1 retry, не більше
        assertEquals(1, api.registerCount)       // рівно одна спроба recovery
    }

    // 7
    @Test
    fun `concurrent 401 recoveries register exactly once`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()

        val calls = List(5) {
            async {
                var tries = 0
                r.authenticatedCall { _ -> tries++; if (tries == 1) throw Stale() else "ok-$it" }
            }
        }
        val results = calls.awaitAll()

        assertTrue(results.all { it.startsWith("ok-") })
        assertEquals(1, api.registerCount)       // єдиний POST /devices на всі 5
    }

    // 8
    @Test
    fun `onNewFcmToken updates existing installation`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-A", "sec-A"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()
        api.updatedTokens.clear()

        r.onNewFcmToken("tok-new")

        assertEquals(listOf("tok-new"), api.updatedTokens)
        assertEquals(0, api.registerCount)
    }

    // 9
    @Test
    fun `onNewFcmToken with stale 401 recovers centrally`() = runTest {
        val api = FakeApi().apply { updateBehavior = { throw Stale() } }
        val store = FakeStore(Credentials("dev-A", "sec-A"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        // initialize зробить свій updateToken(stale)→register; скинемо, щоб бачити саме onNewFcmToken
        r.initialize()
        val baselineRegister = api.registerCount
        store.cleared = 0

        r.onNewFcmToken("tok-new")

        assertEquals(baselineRegister + 1, api.registerCount)  // централізований recovery
        assertTrue(r.state.value is InstallationState.Ready)
    }

    // 10
    @Test
    fun `recovery failure does not declare Ready with invalid credentials`() = runTest {
        val api = FakeApi().apply {
            updateBehavior = { throw Stale() }
            registerBehavior = { throw RuntimeException("network down") }
        }
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)

        r.initialize()

        assertTrue(r.state.value is InstallationState.Unavailable)
        assertNull(store.current)                // невалідну пару прибрано, не Ready з нею
    }

    // 13 (B1) — провал runtime-recovery не лишає брехливий Ready
    @Test
    fun `authenticatedCall recovery failure goes Unavailable with cleared creds`() = runTest {
        val api = FakeApi().apply { registerBehavior = { throw RuntimeException("net down") } }
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()   // updateToken ok → Ready(dev-old)

        try {
            r.authenticatedCall<String> { _ -> throw Stale() }
            throw AssertionError("мав кинути")
        } catch (e: RuntimeException) {
            // очікувано — реєстрація впала
        }

        assertTrue(r.state.value is InstallationState.Unavailable)  // НЕ Ready
        assertNull(store.current)
    }

    // 14 (B1) — другий 401 після успішного retry → Unavailable, без 2-ї реєстрації
    @Test
    fun `authenticatedCall second 401 invalidates and does not re-register`() = runTest {
        val api = FakeApi()
        val store = FakeStore(Credentials("dev-old", "sec-old"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)
        r.initialize()

        try {
            r.authenticatedCall<String> { _ -> throw Stale() }  // 401 щоразу
            throw AssertionError("мав кинути")
        } catch (e: Stale) {
            // очікувано
        }

        assertEquals(1, api.registerCount)                          // рівно одна реєстрація
        assertTrue(r.state.value is InstallationState.Unavailable)  // свіжу пару теж відкинуто
        assertNull(store.current)
    }

    // 15 (B1) — провал FCM stale-recovery → Unavailable + store очищено
    @Test
    fun `onNewFcmToken stale recovery failure goes Unavailable`() = runTest {
        val api = FakeApi().apply {
            updateBehavior = { throw Stale() }
            registerBehavior = { throw RuntimeException("net down") }
        }
        val store = FakeStore(Credentials("dev-A", "sec-A"))
        val r = repo(api, store, FakeTokens("tok-1"), backgroundScope)

        r.onNewFcmToken("tok-new")   // update→401→register→fail

        assertTrue(r.state.value is InstallationState.Unavailable)
        assertNull(store.current)
    }

    // 16 — аудит 2026-08-15: причина Unavailable мала нести справжній виняток
    // FCM-провайдера, а не узагальнений текст. Раніше .getOrNull() ковтав його
    // мовчки, і саме тому знадобився тимчасовий Log.e, щоб дістати "Please set
    // a valid API key" при зламаному google-services.json.
    @Test
    fun `initialize with no credentials surfaces the real token failure as reason`() = runTest {
        val api = FakeApi()
        val store = FakeStore(seed = null)
        val tokens = FakeTokens().apply { fail = true }
        val r = repo(api, store, tokens, backgroundScope)

        r.initialize()

        val state = r.state.value
        assertTrue(state is InstallationState.Unavailable)
        assertEquals("play services offline", (state as InstallationState.Unavailable).reason)
    }

    // 12 (seam для UI без instrumented Compose)
    @Test
    fun `protected load runs when installation becomes Ready`() = runTest(UnconfinedTestDispatcher()) {
        val state = kotlinx.coroutines.flow.MutableStateFlow<InstallationState>(
            InstallationState.Initializing
        )
        val loads = mutableListOf<String>()
        val job = backgroundScope.launch {
            ProtectedLoad.observe(state) { ready -> loads += ready.deviceId }
        }

        assertTrue("Initializing не має тригерити load", loads.isEmpty())

        state.value = InstallationState.Ready("dev-A")
        job.cancel()

        assertEquals(listOf("dev-A"), loads)     // поява Ready запустила protected load
    }
}
