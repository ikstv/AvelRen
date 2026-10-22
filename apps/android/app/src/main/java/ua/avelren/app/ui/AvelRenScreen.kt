package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import ua.avelren.app.ui.theme.hapticClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Build as MaintenanceIcon
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import ua.avelren.app.data.PushSyncState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.ColorMatrix
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import android.os.Build

import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalDensity

import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import ua.avelren.app.data.NotificationPermissionState
import ua.avelren.app.data.ForecastPresentation
import ua.avelren.app.data.WaitPresentation
import ua.avelren.app.ui.theme.SignClosed
import ua.avelren.app.ui.theme.SignOnClosed
import ua.avelren.app.ui.theme.AppAccent as SignWarn
import ua.avelren.app.ui.theme.AppOnAccent as SignOnWarn
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import ua.avelren.app.BuildConfig
import ua.avelren.app.AvelRenApp
import ua.avelren.app.R
import ua.avelren.app.data.BackgroundDelivery
import ua.avelren.app.data.BackgroundDeliveryHint
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.UiPrefs
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.ThemeChoice
import ua.avelren.app.data.LiveRefresh
import ua.avelren.app.data.NetworkAvailability
import ua.avelren.app.data.InternetState
import ua.avelren.app.data.MaintenanceStore
import ua.avelren.app.data.ServerStatus
import ua.avelren.app.data.PlayUpdateState
import ua.avelren.app.ui.theme.AppBackground
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.AppOnAccent
import ua.avelren.app.ui.theme.HeroNumberStyle
import ua.avelren.app.ui.theme.RoadSignShape
import ua.avelren.app.ui.theme.TabularNumberFeature
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.plateBorder
import ua.avelren.app.ui.theme.tapNoRipple
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

// Незмінні draw-об'єкти: створюються раз на процес, а не щорекомпозиції.
// Повнокранне ч/б фото (grayscale-матриця) + два градієнти-затемнення згори/знизу.
private val GrayscaleFilter: ColorFilter =
    ColorFilter.colorMatrix(ColorMatrix().apply { setToSaturation(0f) })
private val TopScrim: Brush =
    Brush.verticalGradient(listOf(Color(0xB808090A), Color(0x0008090A)))
private val BottomScrim: Brush =
    Brush.verticalGradient(listOf(Color(0x00000000), Color(0xBF000000)))

// Країну виводимо з наявного flag_emoji (бекенд не чіпаємо — country_name у
// клієнтській моделі немає). Список — стабільні сухопутні пункти пропуску
// вантажівок з України; невідомий прапор просто лишається як є.
private val COUNTRY_BY_FLAG = mapOf(
    "🇵🇱" to "Польща",
    "🇭🇺" to "Угорщина",
    "🇷🇴" to "Румунія",
    "🇸🇰" to "Словаччина",
    "🇲🇩" to "Молдова",
)

internal fun countryLabel(flag: String?): String {
    if (flag == null) return "Інше"
    return COUNTRY_BY_FLAG[flag]?.let { "$flag $it" } ?: flag
}

/**
 * Головний екран.
 *
 * Увесь вміст — один `LazyColumn`, а не `Column` із вкладеними списками.
 * Інакше картки, що не вмістились у висоту екрана, мовчки обрізаються: вони
 * намальовані, але їх не видно й не доскролиш. Саме так зникла телеметрія,
 * коли карток стало більше трьох.
 */
@Composable
internal fun AvelRenScreen(
    permissionState: NotificationPermissionState,
    onOpenNotificationSettings: () -> Unit,
    ignoringBatteryOptimizations: Boolean = true,
    backgroundHintDismissed: Boolean = false,
    onOpenBatterySettings: () -> Unit = {},
    onDismissBackgroundHint: () -> Unit = {},
    updateAvailable: Boolean = false,
    updateState: PlayUpdateState = PlayUpdateState.AVAILABLE,
    updateActionPending: Boolean = false,
    onStartUpdate: () -> Unit = {},
    screenClient: ua.avelren.app.data.AppScreenClient? = null,
    surgeClient: ua.avelren.app.data.SurgeMonitorClient? = null,
    adminClient: AdminAccessClient? = null,
    adminServerClient: AdminServerClient? = null,
    onOpenPrivacyPolicy: (() -> Unit)? = null,
    enqueueSurgeAck: ((Long) -> Unit)? = null,
    refreshVersion: Int = 0,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    // Малюємо стан дозволу в момент рендеру, нічого не зберігаючи в підписках:
    // позначка «беззвучна» має зникнути сама, щойно дозвіл з'явиться.
    val notificationsSilent = permissionState !is NotificationPermissionState.Granted

    var workload by remember { mutableStateOf<List<Api.Workload>>(emptyList()) }
    var selected by remember { mutableStateOf(DeviceStore.selectedCheckpoint(context)) }
    var loading by remember { mutableStateOf(true) }
    var responseSucceeded by remember { mutableStateOf<Boolean?>(null) }
    var internet by remember { mutableStateOf(NetworkAvailability.current(context)) }
    var networkGeneration by remember { mutableStateOf(0) }
    val refreshMutex = remember { Mutex() }
    val maintenanceStore = remember { MaintenanceStore(context) }
    var maintenance by remember { mutableStateOf(maintenanceStore.read(Instant.now())) }
    // Оновлюється КОЖЕН poll (навіть якщо payload не змінився), щоб freshness
    // рухалась і UI переходив у stale, коли collector завис, а API віддає той
    // самий snapshot (B2).
    var freshnessNow by remember { mutableStateOf(Instant.now()) }
    var countryFilter by remember { mutableStateOf<String?>(null) }
    var showPicker by remember { mutableStateOf(false) }
    var showUpdatePrompt by remember { mutableStateOf(updateAvailable) }
    // Активна вкладка нижньої навігації. Окремого екрана «Моніторинг» ще нема
    // (у макеті теж лише підсвітка), тож поки це тільки стан підсвітки.
    var activeTab by remember { mutableStateOf("home") }
    var testMenuOpen by remember { mutableStateOf(false) }
    var testMenuRefreshing by remember { mutableStateOf(false) }
    var settingsInitialPage by remember { mutableStateOf("menu") }
    var settingsCurrentPage by remember { mutableStateOf("menu") }
    var settingsNavigationRequest by remember { mutableStateOf(0) }
    val uriHandler = LocalUriHandler.current
    // Динаміка реєстрацій обраного КПП за останню годину. null — ще не
    // завантажено; порожній список — сервер віддав, але точок замало.
    var history by remember { mutableStateOf<List<Int>?>(null) }

    // Пороги (threshold-підписки) — екран 04, плитка «Пороги». Реальні дані з
    // сервера: subscriptions()/subscribe()/unsubscribe(). Флоу: тап по плитці →
    // пікер КПП → вибір порога (50/100/150/200) → subscribe.
    val scope = rememberCoroutineScope()
    val selectedTheme = LocalThemeChoice.current
    val keepScreenOn = if (BuildConfig.ENABLE_TEST_DRAWER) {
        val enabled by remember(context) { UiPrefs.keepScreenOnFlow(context) }
            .collectAsStateWithLifecycle(false)
        FullTestKeepScreenOn(enabled)
        enabled
    } else false
    fun savePreference(action: suspend () -> Unit) {
        scope.launch {
            try { action() }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) {
                android.widget.Toast.makeText(context, "Не вдалося зберегти налаштування", android.widget.Toast.LENGTH_SHORT).show()
            }
        }
    }
    val toggleTheme: () -> Unit = {
        savePreference {
            UiPrefs.setTheme(context, if (selectedTheme == ThemeChoice.DARK) ThemeChoice.LIGHT else ThemeChoice.DARK)
        }
    }
    var showRatingInfo by remember { mutableStateOf(false) }
    val installation = remember(context, screenClient) {
        if (screenClient == null) (context.applicationContext as AvelRenApp).installation else null
    }
    val installationState = installation?.state?.collectAsStateWithLifecycle()?.value
    val pushState = if (BuildConfig.ENABLE_PUSH) installation?.pushState?.collectAsStateWithLifecycle()?.value else null
    val retryPush = { scope.launch { installation?.retryBlocked() }; Unit }
    val dataClient = remember(installation, screenClient) {
        screenClient ?: ua.avelren.app.data.ProductionAppScreenClient(
            requireNotNull(installation), mutationCredentials = { DeviceStore.credentials(context) },
        )
    }
    // Registration finishes asynchronously after a fresh install. Do not retain
    // the initial null credentials for the whole lifetime of this screen.
    val creds = remember(installationState) { if (installation != null) DeviceStore.credentials(context) else null }
    val canChangeMonitors = screenClient != null || creds != null
    var subscriptions by remember { mutableStateOf<List<Api.Subscription>>(emptyList()) }
    var etaTargets by remember { mutableStateOf<List<Api.EtaTarget>>(emptyList()) }
    // Порожній список сам по собі НЕ означає «підписок немає» — рівно так само
    // виглядає список, який ще не вдалося завантажити (офлайн-старт). Без цього
    // прапорця UI стверджував «Нема вибраних вами КПП», хоча підписки є (#107).
    // true лише після успішної відповіді сервера.
    var monitorsLoaded by remember { mutableStateOf(false) }
    var monitorsLoading by remember { mutableStateOf(true) }
    var monitorsFailed by remember { mutableStateOf(false) }
    val monitorsMutex = remember { Mutex() }
    var showThresholdCpPicker by remember { mutableStateOf(false) }
    var pendingThresholdCp by remember { mutableStateOf<Api.Workload?>(null) }
    var showEtaCpPicker by remember { mutableStateOf(false) }
    var pendingEtaCp by remember { mutableStateOf<Api.Workload?>(null) }
    // Прогноз — read-only потік: вибір КПП відкриває окремий екран.
    var surgeOpen by remember { mutableStateOf(false) }
    val surgeRepository = remember(installation, surgeClient) {
        surgeClient ?: ua.avelren.app.data.SurgeRepository(requireNotNull(installation))
    }
    var showAiCpPicker by remember { mutableStateOf(false) }
    var pendingAiCp by remember { mutableStateOf<Api.Workload?>(null) }
    // Гейт беззвучної підписки (#117 крок 2): коли дозволу нема, вибір порога
    // веде не прямо в subscribe, а в діалог «увімкнути / все одно». Тут — КПП+поріг,
    // що чекають на рішення. Наполегливо, але прохідно: намір не втрачається.
    var pendingSilentSub by remember { mutableStateOf<Pair<Api.Workload, Int>?>(null) }
    // Рядок, який ✕ пропонує прибрати — тримаємо до підтвердження (запобіжник
    // від випадкового тапу). Саме видалення — лише після «Прибрати».
    var pendingRemove by remember { mutableStateOf<MonitorRow?>(null) }
    // Одне тіло завантаження моніторингу на всі тригери — старт, зміна вкладки,
    // відновлення мережі, полл, зміни підписок, — щоб вони не розійшлись у
    // поведінці. Прапорець зводиться лише коли ОБИДВА запити вдались: інакше
    // напівпорожній список видавали б за повний.
    val loadMonitors: suspend () -> Unit = {
        // Concurrent triggers share the current request instead of queuing duplicates.
        if (monitorsMutex.tryLock()) {
            monitorsLoading = true
            monitorsFailed = false
            try {
                val result = withTimeout(15_000L) {
                    dataClient.monitors()
                }
                // Publish a complete snapshot; preserve the previous one on errors.
                subscriptions = result.first
                etaTargets = result.second
                monitorsLoaded = true
            } catch (_: TimeoutCancellationException) {
                monitorsFailed = true
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                monitorsFailed = true
            } finally {
                monitorsLoading = false
                monitorsMutex.unlock()
            }
        }
    }
    val reloadSubs: () -> Unit = { scope.launch { loadMonitors() } }
    val reloadTargets: () -> Unit = { scope.launch { loadMonitors() } }
    // #117: дозвіл наданий, а пуш однаково може не прийти — систему цікавить не
    // дозвіл, а чи живий процес. Рахуємо тут, бо тільки тут відомо, чи користувач
    // узагалі просив його будити: підказка про фон без жодної підписки — шум.
    val backgroundHint = BackgroundDelivery.evaluate(
        permissionGranted = !notificationsSilent,
        ignoringBatteryOptimizations = ignoringBatteryOptimizations,
        manufacturer = Build.MANUFACTURER,
        brand = Build.BRAND,
        hasActiveSubscriptions = subscriptions.isNotEmpty() || etaTargets.isNotEmpty(),
        dismissed = backgroundHintDismissed,
    )
    // Спільний список моніторингу — пороги + час в'їзду. Показується і на 04, і
    // (дублем) на головній. Поле `current` — живий стан цього КПП зараз (черга
    // для порога / час в'їзду для eta) з workload. Прибирання знає тип DELETE.
    val monitorRows = remember(subscriptions, etaTargets, workload) {
        subscriptions.map { s ->
            val now = workload.firstOrNull { it.checkpoint_id == s.checkpoint_id }
            MonitorRow(
                badge = "${s.threshold}",
                label = monitorLabel(s.flag_emoji, s.title),
                current = now?.let { "${it.vehicles_in_queue}" } ?: "—",
                kind = MonitorKind.THRESHOLD,
                id = s.id,
            )
        } + etaTargets.map { t ->
            val now = workload.firstOrNull { it.checkpoint_id == t.checkpoint_id }
            MonitorRow(
                badge = etaBadge(t.target_at),
                label = monitorLabel(t.flag_emoji, t.title),
                current = now?.let { WaitPresentation.entryEta(it) }?.let { formatEntry(it) } ?: "—",
                kind = MonitorKind.ETA,
                id = t.id,
            )
        }
    }
    val removeRow: (MonitorRow) -> Unit = { row ->
        if (canChangeMonitors) {
            scope.launch {
                runCatching {
                    ua.avelren.app.data.removeMonitorAndReconcile(
                        remove = {
                            when (row.kind) {
                                MonitorKind.THRESHOLD -> dataClient.unsubscribe(row.id)
                                MonitorKind.ETA -> dataClient.deleteEtaTarget(row.id)
                            }
                        },
                        reconcile = {
                            if (BuildConfig.ENABLE_PUSH && installation != null) {
                                ua.avelren.app.notify.NotificationReconciler.reconcile(context, installation)
                            }
                        },
                    )
                }
                loadMonitors()
            }
        }
    }

    // Одне тіло оновлення на два тригери — цикл і сигнал мережі, — щоб вони не
    // розійшлись у поведінці при майбутніх правках.
    val refresh: suspend () -> Unit = {
        refreshMutex.withLock {
            val generation = networkGeneration
            if (screenClient == null && internet == InternetState.OFFLINE) {
                responseSucceeded = false
                loading = false
            } else coroutineScope {
                val monitors = async { loadMonitors() }
                val status = async {
                    runCatching { dataClient.serverStatus() }
                        .onFailure { if (it is CancellationException) throw it }
                }
                val wlRes = runCatching { dataClient.workload() }
                    .onFailure { if (it is CancellationException) throw it }
                if (generation == networkGeneration) {
                    workload = LiveRefresh.keepOnError(workload, wlRes)
                    responseSucceeded = wlRes.isSuccess
                    loading = false
                }
                status.await().onSuccess { result ->
                    if (generation == networkGeneration) {
                        maintenance = result.maintenance?.takeIf { it.bounds(Instant.now()) != null }
                        maintenanceStore.write(maintenance)
                    }
                }
                monitors.await()
                freshnessNow = Instant.now()
            }
        }
    }

    // Живе оновлення (AND-4): refresh одразу при вході/поверненні, далі кожні
    // 60 c — але ЛИШЕ у foreground (repeatOnLifecycle(RESUMED) паузить при
    // згортанні й перезапускає при поверненні → миттєвий refresh). При помилці
    // останні валідні дані НЕ стираються (keep-last).
    //
    // Паралельно слухаємо відновлення зв'язку: без цього після повернення
    // інтернету екран лишався б із червоною плашкою до кінця 60-секундного
    // циклу. Обидві гілки живуть у тому ж RESUMED-скоупі, тож у фоні не
    // працюють і скасовуються разом.
    LaunchedEffect(refreshVersion) { if (screenClient != null) refresh() }
    LaunchedEffect(lifecycleOwner, selected) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            launch {
                NetworkAvailability.states(context).collect { state ->
                    val changed = internet != state
                    if (changed) {
                        internet = state
                        networkGeneration += 1
                        responseSucceeded = null
                    }
                    if (state == InternetState.OFFLINE) loading = false
                    else if (changed && (state == InternetState.ONLINE || state == InternetState.WEAK))
                        launch { refresh() }
                }
            }
            launch {
                while (true) {
                    freshnessNow = Instant.now()
                    delay(1_000)
                }
            }
            LiveRefresh.poll { refresh() }
        }
    }

    // Макет тримає `currentId: 'cp1'` — пункт обраний завжди, стану «не
    // обрано» не існує. Якщо збереженого вибору ще немає (перший запуск) або
    // він зник зі snapshot — показуємо перший зі списку.
    val current = workload.firstOrNull { it.checkpoint_id == selected }
        ?: workload.firstOrNull()

    // Історія для графіка — прив'язана до обраного КПП: зміна пункту (ключ на
    // current.checkpoint_id) перезапускає запит. Оновлюється й щохвилини разом
    // з екраном. Помилка не стирає попередню лінію (лишається остання валідна).
    val currentId = current?.checkpoint_id
    LaunchedEffect(lifecycleOwner, currentId) {
        if (currentId == null) return@LaunchedEffect
        history = null
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            LiveRefresh.poll {
                runCatching { dataClient.history(currentId) }
                    .onSuccess { h -> history = h.points.map { it.vehicles_in_queue } }
            }
        }
    }

    // Моніторинг потрібен на обох вкладках (на головній дублюється), тож
    // перезавантажуємо при зміні вкладки. Основний шлях — `refresh()` (полл +
    // сигнал мережі); цей ефект лише доганяє перемикання вкладки між поллами.
    // Мовчить, коли креденшалів ще нема.
    LaunchedEffect(activeTab, creds) {
        loadMonitors()
    }

    LaunchedEffect(updateAvailable, updateState) {
        showUpdatePrompt = updateAvailable && updateState.actionable
    }

    // Свіжість за server observation time обраного КПП (без вибору — макс. по
    // списку). Якщо обраний зник зі snapshot — current==null → time==null →
    // stale, чужим часом не підміняємо.
    val obsTime = if (selected > 0) current?.time else workload.mapNotNull { it.time }.maxOrNull()
    val freshness = if (workload.isNotEmpty()) LiveRefresh.freshness(obsTime, freshnessNow) else null
    val serverStatus = ServerStatus.resolve(internet, responseSucceeded, freshness?.stale, maintenance, freshnessNow)

    val onMonitor = activeTab == "monitor"
    val activeMonitorCount = if (monitorsLoaded && !monitorsFailed) {
        subscriptions.size + etaTargets.count { it.is_active }
    } else null
    val onSettings = activeTab == "settings"
    val forecastOpen = pendingAiCp != null || surgeOpen
    BackHandler(enabled = forecastOpen) { pendingAiCp = null; surgeOpen = false }
    val density = LocalDensity.current
    var bottomChromeHeightPx by remember { mutableStateOf(0) }
    val measuredBottomChromeDp = with(density) { bottomChromeHeightPx.toDp().value }
    val bottomChromePadding = if (BuildConfig.ENABLE_TEST_DRAWER) {
        maxOf(84f, measuredBottomChromeDp + 8f).dp
    } else {
        bottomChromeContentInset(measuredBottomChromeDp, updateAvailable).dp
    }

    // Усі основні вкладки мають рівне чорне тло.
    Box(Modifier.fillMaxSize().background(if (forecastOpen) MonitorBg else AppBackground)) {

    if (surgeOpen && pendingAiCp == null) {
        SurgeMonitorScreen(
            repository = surgeRepository,
            onBack = { surgeOpen = false },
            notificationsAllowed = !notificationsSilent && ua.avelren.app.notify.Notifications.surgeChannelAllowed(context),
            onOpenNotificationSettings = onOpenNotificationSettings,
            onCountForecast = { id -> pendingAiCp = workload.firstOrNull { it.checkpoint_id == id } },
            enqueueAck = enqueueSurgeAck,
            refreshVersion = refreshVersion,
        )
    } else if (forecastOpen) {
        pendingAiCp?.let { cp ->
            ForecastScreen(
                checkpointTitle = monitorLabel(cp.flag_emoji, cp.title),
                checkpointId = cp.checkpoint_id,
                onBack = { pendingAiCp = null },
                loadForecast = dataClient::forecast,
            )
        }
    } else if (onMonitor) {
        // Природна висота плиток: великий системний шрифт не стискає текст.
        // Сторінка має один скрол, без вкладеного скролу списку підписок.
        Column(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp)
                .padding(bottom = bottomChromePadding)
                .verticalScroll(rememberScrollState())
                .padding(bottom = 12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            HeaderRow(
                showServerStatus = false,
                title = "Моніторинг",
            )
            PushSyncStatus(pushState, retryPush)
            if (notificationsSilent) {
                NotificationSilentBanner(onOpenNotificationSettings)
            }
            BackgroundDeliveryHintRow(
                hint = backgroundHint,
                onOpenSettings = onOpenBatterySettings,
                onDismiss = onDismissBackgroundHint,
            )
            ActionTile(
                title = "Пороги",
                subtitle = "Сповістити, коли черга сягне певної кількості авто",
                onClick = { showThresholdCpPicker = true },
                modifier = Modifier.fillMaxWidth(),
                icon = { TileIcon(Icons.Filled.BarChart) },
            )
            ActionTile(
                title = "Час в'їзду",
                subtitle = "Сповістити, коли черга дійде до бажаного часу в'їзду",
                onClick = { showEtaCpPicker = true },
                modifier = Modifier.fillMaxWidth(),
                icon = { TileIcon(Icons.Filled.HourglassEmpty) },
            )
            ActionTile(
                title = "Прогноз черги",
                subtitle = "Кілька КПП · прогноз, початок зростання та голос",
                onClick = { surgeOpen = true },
                modifier = Modifier.fillMaxWidth(),
                icon = { TileIcon(Icons.Filled.AutoAwesome) },
            )
            MonitoringTile(
                rows = monitorRows,
                onRemove = { pendingRemove = it },
                modifier = Modifier.fillMaxWidth(),
                homeStyle = true,
                fill = false,
                loaded = monitorsLoaded,
                loading = monitorsLoading,
                failed = monitorsFailed,
                onRetry = reloadSubs,
                notificationsSilent = notificationsSilent,
            )
        }
    } else if (onSettings) {
        key(settingsNavigationRequest) {
        SettingsScreen(
            adminClient = adminClient,
            adminServerClient = adminServerClient,
            onOpenPrivacyPolicy = onOpenPrivacyPolicy,
            initialPage = settingsInitialPage,
            onPageChanged = if (BuildConfig.ENABLE_TEST_DRAWER) {
                { page -> settingsCurrentPage = page }
            } else null,
            menuContent = if (BuildConfig.ENABLE_TEST_DRAWER) { navigate ->
                FullTestSettingsScreen(
                    dark = selectedTheme == ThemeChoice.DARK,
                    onToggleTheme = toggleTheme,
                    keepScreenOn = keepScreenOn,
                    onKeepScreenOnChange = { enabled -> savePreference { UiPrefs.setKeepScreenOn(context, enabled) } },
                    notificationsEnabled = !notificationsSilent,
                    ignoringBatteryOptimizations = ignoringBatteryOptimizations,
                    onOpenNotificationSettings = onOpenNotificationSettings,
                    onOpenBatterySettings = onOpenBatterySettings,
                    onShareApp = { shareAvelRen(context) },
                    onRateApp = { showRatingInfo = true },
                    onOpenAbout = { navigate("about") },
                    onOpenPrivacy = {
                        if (onOpenPrivacyPolicy != null) onOpenPrivacyPolicy()
                        else openAvelRenPrivacy(context)
                    },
                    onOpenDeveloper = { navigate("admin") },
                )
            } else null,
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp)
                .padding(bottom = bottomChromePadding),
        )
        }
    } else {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp)
                .padding(bottom = bottomChromePadding),
            contentPadding = PaddingValues(bottom = 12.dp),
        ) {
            item {
                HeaderRow(
                    status = serverStatus,
                    remainingMinutes = maintenance?.remainingMinutes(freshnessNow),
                )
            }
            if (pushState != null && pushState != PushSyncState.Synced) {
                item { PushSyncStatus(pushState, retryPush) }
            }
            if (notificationsSilent) {
                item { NotificationSilentBanner(onOpenNotificationSettings) }
            }
            if (backgroundHint !is BackgroundDeliveryHint.None) {
                item {
                    BackgroundDeliveryHintRow(
                        hint = backgroundHint,
                        onOpenSettings = onOpenBatterySettings,
                        onDismiss = onDismissBackgroundHint,
                    )
                }
            }
            if (loading) {
                item {
                    Box(Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator()
                    }
                }
            } else if (current != null) {
                item { HeroPanel(current) { showPicker = true } }
                if (BuildConfig.ENABLE_TEST_DRAWER) {
                    item {
                        FullTestCheckpointActions(
                            canChangeMonitors = canChangeMonitors,
                            onThreshold = { pendingThresholdCp = current },
                            onEta = { pendingEtaCp = current },
                            onForecast = { surgeOpen = false; pendingAiCp = current },
                            modifier = Modifier.padding(top = 12.dp),
                        )
                    }
                }
                item {
                    RegistrationChart(
                        values = history,
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                    )
                }
                item {
                    // Дубль «Ваш моніторинг» на головній — ті самі реальні дані.
                    MonitoringTile(
                        rows = monitorRows,
                        onRemove = { pendingRemove = it },
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                        homeStyle = true,
                        loaded = monitorsLoaded,
                        loading = monitorsLoading,
                        failed = monitorsFailed,
                        onRetry = reloadSubs,
                        notificationsSilent = notificationsSilent,
                    )
                }
            } else {
                // `tilesHidden` — коли показувати нема чого (keep-last: current
                // null означає, що валідних даних ще НЕ було).
                item { DataUnavailablePanel(Modifier.padding(top = 38.dp)) }
            }
        }
    }

    // Єдиний нижній блок: фактична висота враховує переноси великого тексту.
    // Вміст вкладки резервує цей простір, не малюється під футером.
    if (!forecastOpen) {
        Column(
            modifier = Modifier.align(Alignment.BottomCenter)
                .windowInsetsPadding(
                    if (BuildConfig.ENABLE_TEST_DRAWER) WindowInsets.navigationBars else WindowInsets.systemBars,
                )
                .onSizeChanged { bottomChromeHeightPx = it.height }
                .padding(horizontal = 12.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (updateAvailable) {
                AppUpdatePill(
                    state = updateState, actionPending = updateActionPending,
                    onStartUpdate = onStartUpdate,
                    modifier = Modifier.padding(horizontal = 8.dp),
                )
            }
            if (onSettings) {
                SettingsDeveloperFooter(Modifier.padding(horizontal = 8.dp))
            } else if (!onMonitor) {
                AttributionBar(
                    Modifier.padding(horizontal = 8.dp)
                        .clip(RoundedCornerShape(10.dp))
                        .background(AppBackground)
                        .padding(horizontal = 8.dp, vertical = 4.dp),
                )
            }
            if (BuildConfig.ENABLE_TEST_DRAWER) {
                FullTestBottomBar(
                    activeTab = activeTab,
                    monitorCount = activeMonitorCount,
                    onOpenMenu = { testMenuOpen = true },
                    onHome = { activeTab = "home" },
                    onMonitoring = { activeTab = "monitor" },
                )
            } else {
                BottomNavBar(
                    activeTab = activeTab, onSelect = { activeTab = it },
                    flatDark = onMonitor || onSettings,
                )
            }
        }
    }
    }

    if (BuildConfig.ENABLE_TEST_DRAWER) {
        val selectedDestination = when {
            forecastOpen -> FullTestDestination.FORECAST
            onMonitor -> FullTestDestination.MONITOR
            onSettings -> when (settingsCurrentPage) {
                "theme" -> FullTestDestination.THEME
                "about" -> FullTestDestination.ABOUT
                "admin" -> FullTestDestination.DEVELOPER
                else -> FullTestDestination.SETTINGS
            }
            else -> FullTestDestination.HOME
        }
        FullTestNavigationDrawer(
            open = testMenuOpen,
            selected = selectedDestination,
            checkpointTitle = current?.let { "${it.flag_emoji.orEmpty()} ${it.title}".trim() },
            serverStatus = serverStatus,
            refreshing = testMenuRefreshing,
            canChooseCheckpoint = workload.isNotEmpty(),
            monitorCount = activeMonitorCount,
            onToggleTheme = toggleTheme,
            onChooseCheckpoint = {
                testMenuOpen = false
                pendingAiCp = null
                surgeOpen = false
                activeTab = "home"
                showPicker = true
            },
            onRefresh = {
                if (!testMenuRefreshing) {
                    testMenuRefreshing = true
                    scope.launch {
                        try {
                            refresh()
                        } finally {
                            testMenuRefreshing = false
                        }
                    }
                }
            },
            onClose = { testMenuOpen = false },
            onSelect = { destination ->
                testMenuOpen = false
                when (destination) {
                    FullTestDestination.NOTIFICATIONS -> onOpenNotificationSettings()
                    FullTestDestination.PRIVACY -> {
                        if (onOpenPrivacyPolicy != null) onOpenPrivacyPolicy()
                        else uriHandler.openUri("https://api.bordersignal.pp.ua/privacy?v=20260924")
                    }
                    else -> {
                        pendingAiCp = null
                        surgeOpen = destination == FullTestDestination.FORECAST
                        activeTab = when (destination) {
                            FullTestDestination.HOME -> "home"
                            FullTestDestination.MONITOR, FullTestDestination.FORECAST -> "monitor"
                            else -> "settings"
                        }
                        if (activeTab == "settings") {
                            settingsInitialPage = when (destination) {
                                FullTestDestination.THEME -> "theme"
                                FullTestDestination.ABOUT -> "about"
                                FullTestDestination.SETTINGS -> "menu"
                                else -> "admin"
                            }
                            settingsNavigationRequest += 1
                        }
                    }
                }
            },
        )
    }

    if (BuildConfig.ENABLE_TEST_DRAWER && showRatingInfo) {
        FullTestRatingInfo(
            onDismiss = { showRatingInfo = false },
            onOpenStore = { showRatingInfo = false; openAvelRenStore(context) },
        )
    }

    if (showUpdatePrompt && updateAvailable && updateState.actionable) {
        AppUpdateDialog(
            ready = updateState == PlayUpdateState.READY,
            actionPending = updateActionPending,
            onUpdate = {
                showUpdatePrompt = false
                onStartUpdate()
            },
            onDismiss = { showUpdatePrompt = false },
        )
    }

    if (showPicker) {
        CheckpointPickerSheet(
            workload = workload,
            selectedId = selected,
            countryFilter = countryFilter,
            onFilter = { countryFilter = it },
            onPick = { id ->
                selected = id
                DeviceStore.saveSelectedCheckpoint(context, id)
                showPicker = false
            },
            onDismiss = { showPicker = false },
        )
    }

    // Додавання порога, крок 1 — той самий пікер КПП, але вибір веде до вибору
    // порога, а не змінює обраний на головній.
    if (showThresholdCpPicker) {
        CheckpointPickerSheet(
            workload = workload,
            selectedId = -1,
            countryFilter = countryFilter,
            onFilter = { countryFilter = it },
            onPick = { id ->
                pendingThresholdCp = workload.firstOrNull { it.checkpoint_id == id }
                showThresholdCpPicker = false
            },
            onDismiss = { showThresholdCpPicker = false },
        )
    }

    // Крок 2 — вибір значення порога для обраного КПП → subscribe.
    pendingThresholdCp?.let { cp ->
        ThresholdChooserDialog(
            checkpointTitle = monitorLabel(cp.flag_emoji, cp.title),
            onPick = { threshold ->
                if (notificationsSilent) {
                    // Дозволу нема — не підписуємо мовчки: спершу діалог вибору.
                    pendingSilentSub = cp to threshold
                } else {
                    if (canChangeMonitors) {
                        scope.launch {
                            runCatching { dataClient.subscribe(cp.checkpoint_id, threshold) }
                            reloadSubs()
                        }
                    }
                }
                pendingThresholdCp = null
            },
            onDismiss = { pendingThresholdCp = null },
        )
    }

    // Гейт беззвучної підписки (#117): наполегливо, але прохідно.
    pendingSilentSub?.let { (cp, threshold) ->
        SilentSubscribeDialog(
            onEnable = {
                onOpenNotificationSettings()
                pendingSilentSub = null
            },
            onSubscribeAnyway = {
                if (canChangeMonitors) {
                    scope.launch {
                        runCatching { dataClient.subscribe(cp.checkpoint_id, threshold) }
                        reloadSubs()
                    }
                }
                pendingSilentSub = null
            },
            onDismiss = { pendingSilentSub = null },
        )
    }

    // Час в'їзду, крок 1 — пікер КПП.
    if (showEtaCpPicker) {
        CheckpointPickerSheet(
            workload = workload,
            selectedId = -1,
            countryFilter = countryFilter,
            onFilter = { countryFilter = it },
            onPick = { id ->
                pendingEtaCp = workload.firstOrNull { it.checkpoint_id == id }
                showEtaCpPicker = false
            },
            onDismiss = { showEtaCpPicker = false },
        )
    }

    // Підтвердження прибирання — запобіжник від випадкового ✕.
    pendingRemove?.let { row ->
        ConfirmRemoveDialog(
            row = row,
            onConfirm = {
                removeRow(row)
                pendingRemove = null
            },
            onDismiss = { pendingRemove = null },
        )
    }

    // Крок 2 — вибір дня й часу в'їзду → createEtaTarget.
    pendingEtaCp?.let { cp ->
        EtaChooserDialog(
            checkpointTitle = monitorLabel(cp.flag_emoji, cp.title),
            onPick = { targetAtIso ->
                if (canChangeMonitors) {
                    scope.launch {
                        runCatching { dataClient.createEtaTarget(cp.checkpoint_id, targetAtIso) }
                        reloadTargets()
                    }
                }
                pendingEtaCp = null
            },
            onDismiss = { pendingEtaCp = null },
        )
    }


}

/**
 * Плашка лише на головній. Вузький екран переносить її під назву без обрізання.
 * Стан визначає ServerStatus; перезапуск можливий лише у підтвердженому
 * maintenance-вікні, а не як припущення з віку даних.
 */
@Composable
@OptIn(ExperimentalLayoutApi::class)
private fun HeaderRow(
    status: ServerStatus = ServerStatus.CHECKING,
    remainingMinutes: Long? = null,
    showServerStatus: Boolean = true,
    title: String = "AVELREN",
) {
    val avelren = MaterialTheme.avelren
    FlowRow(
        modifier = Modifier.fillMaxWidth().padding(top = 26.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            title,
            style = MaterialTheme.typography.headlineMedium,
            color = AppInk,
            modifier = if (showServerStatus) Modifier else Modifier.alignByBaseline(),
        )
        if (showServerStatus && status.label.isNotEmpty()) {
            val dot = when (status) {
                ServerStatus.ONLINE -> avelren.go
                ServerStatus.CHECKING, ServerStatus.STALE, ServerStatus.NO_DATA,
                ServerStatus.WEAK_INTERNET, ServerStatus.MAINTENANCE,
                ServerStatus.RESTARTING -> avelren.warn
                else -> avelren.closed
            }
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .clip(RoundedCornerShape(8.dp))
                    .padding(horizontal = 10.dp, vertical = 5.dp),
            ) {
                if (status == ServerStatus.MAINTENANCE || status == ServerStatus.RESTARTING) {
                    Icon(Icons.Filled.MaintenanceIcon, contentDescription = null,
                        tint = dot, modifier = Modifier.size(14.dp))
                } else {
                    Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
                }
                Spacer(Modifier.width(7.dp))
                Text(
                    if (status == ServerStatus.MAINTENANCE && remainingMinutes != null)
                        "${status.label} · ДО $remainingMinutes ХВ"
                    else status.label,
                    style = MaterialTheme.typography.bodySmall,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 0.sp,
                    color = when (status) {
                        ServerStatus.NO_INTERNET, ServerStatus.WEAK_INTERNET,
                        ServerStatus.MAINTENANCE, ServerStatus.RESTARTING -> dot
                        else -> AppInk
                    },
                )
            }
        } else if (!showServerStatus) {
            VersionHeader(Modifier.alignByBaseline())
        }
    }
}

@Composable
private fun VersionHeader(modifier: Modifier = Modifier) {
    Text(
        "ВЕРСІЯ ${BuildConfig.VERSION_NAME}",
        modifier = modifier,
        color = AppInk,
        fontWeight = FontWeight.Bold,
        fontSize = 10.sp,
        letterSpacing = 2.sp,
    )
}

@Composable
private fun FadingHairline(modifier: Modifier = Modifier) {
    Box(
        modifier
            .fillMaxWidth()
            .height(1.dp)
            .background(
                Brush.horizontalGradient(
                    listOf(Color.Transparent, AppInk.copy(alpha = 0.85f), Color.Transparent)
                )
            )
    )
}


// Колір тексту/іконки порожнього стану — rgba(255,255,255,.6) з макета.
private val EmptyInk: Color @Composable get() = AppInk.copy(alpha = 0.6f)

/**
 * Порожній стан «Дані недоступні» (макет: екран 04 / `tilesHidden`). Та сама
 * скляна панель, іконка перекресленого Wi-Fi, підпис і пояснення. Показується
 * замість плиток, коли валідних даних ще не було (нема інтернету на старті).
 */
@Composable
private fun DataUnavailablePanel(modifier: Modifier = Modifier) {
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(HeroGlass)
            .border(1.dp, HeroBorder, RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        WifiOffIcon()
        Spacer(Modifier.height(10.dp))
        // Макет: панель жовта — заголовок #F5C400, опис #F5C400 з opacity .85.
        Text(
            "Дані недоступні",
            color = HeroYellow,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.bodyMedium,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "Перевірте з'єднання з інтернетом — щойно сервер відповість, дані з'являться знову",
            color = HeroYellow.copy(alpha = 0.85f),
            style = MaterialTheme.typography.bodySmall,
            fontSize = 12.sp,
            lineHeight = 17.sp,
            textAlign = TextAlign.Center,
        )
    }
}

/** Іконка «немає мережі» — три дуги Wi-Fi, крапка й діагональна риска (SVG з Design). */
@Composable
private fun WifiOffIcon(modifier: Modifier = Modifier) {
    val iconAccent = HeroYellow
    Canvas(modifier.size(40.dp)) {
        val s = size.minDimension / 24f       // viewBox макета — 0 0 24 24
        val sw = 1.8f * s
        // Три «хвилі» Wi-Fi (cubic-криві з SVG-шляху), зверху вниз.
        val waves = Path().apply {
            moveTo(1f * s, 9f * s); cubicTo(7f * s, 4f * s, 17f * s, 4f * s, 23f * s, 9f * s)
            moveTo(4.5f * s, 12.5f * s); cubicTo(8.5f * s, 9.5f * s, 15.5f * s, 9.5f * s, 19.5f * s, 12.5f * s)
            moveTo(8f * s, 16f * s); cubicTo(10f * s, 14.5f * s, 14f * s, 14.5f * s, 16f * s, 16f * s)
        }
        drawPath(waves, iconAccent, style = Stroke(width = sw, cap = StrokeCap.Round))
        // Крапка під хвилями та діагональна риска «перекреслено».
        drawCircle(iconAccent, radius = sw * 0.6f, center = Offset(12f * s, 19.5f * s))
        drawLine(iconAccent, Offset(2f * s, 2f * s), Offset(22f * s, 22f * s), sw, cap = StrokeCap.Round)
    }
}

// --- Плитка «Ваш моніторинг» ----------------------------------------------
// Список того, що користувач моніторить: пороги + час в'їзду. Кожен запис —
// Поріг або дата й час цілі, повна назва КПП та окреме поточне вимірювання.
// Червоний хрестик відкриває підтвердження прибирання.
enum class MonitorKind { THRESHOLD, ETA }

/**
 * @param badge   значення підписки (поріг або дата й час цілі в'їзду).
 * @param label   повна назва КПП із прапором та уточненням типу вантажівки.
 * @param current поточний стан цього КПП зараз (черга або час в'їзду).
 * @param kind    тип — визначає, який DELETE викликати при прибиранні.
 * @param id      id підписки/цілі на сервері.
 */
data class MonitorRow(
    val badge: String,
    val label: String,
    val current: String,
    val kind: MonitorKind,
    val id: Long,
)

private val WatchRowBorder: Color @Composable get() = AppInk.copy(alpha = 0.14f)  // rgba(255,255,255,.14)

@Composable
private fun MonitoringTile(
    rows: List<MonitorRow>,
    onRemove: (MonitorRow) -> Unit,
    modifier: Modifier = Modifier,
    homeStyle: Boolean = false,
    fill: Boolean = false,   // true — заповнити висоту плитки (екран «Моніторинг»)
    loaded: Boolean = true,  // false — список ще не приїхав; НЕ показувати empty-state
    loading: Boolean = false,
    failed: Boolean = false,
    onRetry: () -> Unit = {},
    notificationsSilent: Boolean = false,  // дозволу нема → рядки несуть позначку «беззвучна»
) {
    val shape = RoundedCornerShape(if (BuildConfig.ENABLE_TEST_DRAWER) 20.dp else 16.dp)
    Column(
        modifier
            .clip(shape)
            .background(if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.colorScheme.surfaceVariant else if (homeStyle) AppBackground else HeroGlass)
            .border(if (homeStyle && !BuildConfig.ENABLE_TEST_DRAWER) 1.5.dp else 1.dp,
                if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.avelren.line else if (homeStyle) SignWarn.copy(alpha = 0.5f) else HeroBorder, shape)
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "Ваш моніторинг",
            color = if (BuildConfig.ENABLE_TEST_DRAWER) AppInk else HeroYellow,
            fontWeight = FontWeight.Black,
            style = MaterialTheme.typography.bodyMedium,
            fontSize = if (BuildConfig.ENABLE_TEST_DRAWER) 16.sp else 12.sp,
            letterSpacing = 0.025.em,
        )
        if (failed || (!loaded && !loading)) {
            Text(
                if (loaded) "Не вдалося оновити моніторинг. Показано попередні дані."
                else "Не вдалося завантажити моніторинг.",
                color = EmptyInk,
                fontSize = 13.sp,
                modifier = Modifier.padding(top = 12.dp),
            )
            Text(
                "Повторити",
                color = HeroYellow,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.hapticClickable(enabled = !loading, onClick = onRetry)
                    .padding(vertical = 12.dp),
            )
        }
        if (rows.isEmpty() && !(failed || (!loaded && !loading))) {
            // fill — центр по всій висоті плитки; інакше — природна висота.
            Box(
                if (fill) Modifier.weight(1f).fillMaxWidth() else Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                // Поки список не приїхав — стан очікування, а не твердження
                // «нічого не відстежується». Стверджувати можна лише після
                // успішної відповіді сервера (#107).
                if (!loaded && loading) {
                    CircularProgressIndicator(
                        color = HeroYellow,
                        strokeWidth = 2.dp,
                        modifier = Modifier.padding(vertical = 22.dp).size(20.dp),
                    )
                } else {
                    Text(
                        "Нема вибраних вами КПП для моніторингу",
                        color = EmptyInk,
                        style = MaterialTheme.typography.bodySmall,
                        fontSize = 12.5.sp,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(vertical = 22.dp),
                    )
                }
            }
        } else {
            Spacer(Modifier.height(12.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .then(if (fill) Modifier.weight(1f).verticalScroll(rememberScrollState()) else Modifier),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                rows.forEach { row -> MonitorRowView(row, notificationsSilent) { onRemove(row) } }
            }
        }
    }
}

/**
 * Назва КПП має власний рядок; ціль та поточний стан підписані окремо.
 * Кнопка прибирання спільна з прогнозом і відкриває підтвердження.
 */
@Composable
private fun MonitorRowView(row: MonitorRow, notificationsSilent: Boolean, onRemove: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .then(if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.clip(RoundedCornerShape(12.dp)).background(AppBackground) else Modifier)
            .border(1.dp, WatchRowBorder, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // Назва має власний рядок і не конкурує з датою та числом за ширину.
        Text(row.label, color = AppInk, style = MaterialTheme.typography.bodySmall,
            fontSize = 12.5.sp, modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(
                    when (row.kind) {
                        MonitorKind.THRESHOLD -> "Поріг: ${row.badge} авто"
                        MonitorKind.ETA -> "Ціль: ${row.badge}"
                    },
                    color = HeroYellow, fontWeight = FontWeight.Bold, fontSize = 12.sp,
                    style = MaterialTheme.typography.bodySmall.copy(fontFeatureSettings = TabularNumberFeature),
                )
                Text(
                    when (row.kind) {
                        MonitorKind.THRESHOLD -> "Зараз: ${row.current} авто"
                        MonitorKind.ETA -> "В’їзд за поточною чергою: ${row.current}"
                    },
                    color = AppInk, fontSize = 12.5.sp,
                    style = MaterialTheme.typography.bodySmall.copy(fontFeatureSettings = TabularNumberFeature),
                )
            }
            RemoveCheckpointButton(row.label, onClick = onRemove)
        }
        if (notificationsSilent) {
            // Позначка «беззвучна» — суто зі стану дозволу в момент рендеру.
            // Зникне сама, щойно дозвіл з'явиться (нічого не збережено в підписці).
            Text(
                "🔕",
                fontSize = 12.sp,
                modifier = Modifier
                    .border(1.dp, SignClosed, RoundedCornerShape(6.dp))
                    .padding(horizontal = 5.dp, vertical = 3.dp),
            )
        }
    }
}

// --- Екран «Моніторинг»: плитки-дії та додавання порога -------------------
/** Повний підпис: уточнення типу вантажівки є частиною назви КПП. */
private fun monitorLabel(flag: String?, title: String): String =
    "${flag ?: ""} $title".trim()

/**
 * Плитка-дія (напр. «Пороги») — скляна панель, уся клікабельна, з тактильним
 * відгуком і афордансом «+». Тап відкриває пікер КПП.
 */
@Composable
private fun ActionTile(
    title: String,
    subtitle: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: @Composable () -> Unit = {},
) {
    val shape = RoundedCornerShape(if (BuildConfig.ENABLE_TEST_DRAWER) 20.dp else 16.dp)
    Row(
        modifier
            .clip(shape)
            .background(if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.colorScheme.surfaceVariant else AppBackground)
            .border(if (BuildConfig.ENABLE_TEST_DRAWER) 1.dp else 1.5.dp,
                if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.avelren.line else SignWarn.copy(alpha = 0.5f), shape)
            .then(if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.semantics { role = Role.Button } else Modifier)
            .tapNoRipple {
                onClick()
            }
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        icon()
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(
                title,
                color = if (BuildConfig.ENABLE_TEST_DRAWER) AppInk else HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = if (BuildConfig.ENABLE_TEST_DRAWER) 16.sp else 12.sp,
                letterSpacing = 0.025.em,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                subtitle,
                color = EmptyInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = if (BuildConfig.ENABLE_TEST_DRAWER) 13.sp else 12.sp,
                lineHeight = if (BuildConfig.ENABLE_TEST_DRAWER) 19.sp else 16.sp,
            )
        }
        Spacer(Modifier.width(12.dp))
        if (BuildConfig.ENABLE_TEST_DRAWER) {
            Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, null, tint = MaterialTheme.avelren.ink2, modifier = Modifier.size(24.dp))
        } else {
        // «+» намальований штрихами (не гліф шрифту): рівні плечі, круглі кінці,
        // ідеально по центру — чистіший вигляд.
        val iconAccent = HeroYellow
        Canvas(Modifier.size(22.dp)) {
            val c = size.width / 2f
            val arm = size.width * 0.32f
            val sw = 2.2.dp.toPx()
            drawLine(iconAccent, Offset(c - arm, c), Offset(c + arm, c), sw, cap = StrokeCap.Round)
            drawLine(iconAccent, Offset(c, c - arm), Offset(c, c + arm), sw, cap = StrokeCap.Round)
        }
        }
    }
}

/** Справжня Material-іконка для плитки-дії — жовта, 26dp. */
@Composable
private fun TileIcon(icon: androidx.compose.ui.graphics.vector.ImageVector) {
    Icon(icon, contentDescription = null, tint = HeroYellow, modifier = Modifier.size(26.dp))
}

/** Play Core reports an update only after Google Play can serve it to this install. */
@Composable
private fun AppUpdatePill(
    state: PlayUpdateState,
    actionPending: Boolean,
    onStartUpdate: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(SignWarn)
            .hapticClickable(enabled = state.actionable && !actionPending) { onStartUpdate() }
            .padding(horizontal = 14.dp, vertical = 9.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("↻", color = SignOnWarn, fontWeight = FontWeight.Black, fontSize = 18.sp)
        Column(Modifier.weight(1f)) {
            Text(
                when (state) {
                    PlayUpdateState.READY -> "Оновлення готове"
                    PlayUpdateState.DOWNLOADING -> "Оновлення завантажується"
                    PlayUpdateState.INSTALLING -> "Оновлення встановлюється"
                    else -> "Доступна нова версія"
                },
                color = SignOnWarn,
                fontWeight = FontWeight.Black,
                fontSize = 12.5.sp,
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                when {
                    actionPending -> "Зачекайте, будь ласка."
                    state == PlayUpdateState.READY -> "Натисніть, щоб встановити й перезапустити."
                    state == PlayUpdateState.DOWNLOADING -> "Можна продовжувати користуватися застосунком."
                    state == PlayUpdateState.INSTALLING -> "Застосунок буде перезапущено."
                    else -> "Натисніть, щоб оновити через Google Play."
                },
                color = SignOnWarn,
                fontSize = 11.5.sp,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/**
 * Банер «сповіщення вимкнені» (#117 крок 1). Малюється лише коли дозволу нема;
 * тап веде в налаштування. Стан перечитується в MainActivity.onResume, тож банер
 * зникає сам після повернення з налаштувань.
 */
@Composable
private fun NotificationSilentBanner(onOpenSettings: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = 12.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(SignClosed)
            .hapticClickable { onOpenSettings() }
            .padding(horizontal = 14.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("🔕", fontSize = 18.sp)
        Column(Modifier.weight(1f)) {
            Text(
                "Сповіщення вимкнені",
                color = SignOnClosed,
                fontWeight = FontWeight.Black,
                fontSize = 12.5.sp,
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                "Застосунок не зможе вас попередити. Натисніть, щоб увімкнути.",
                color = SignOnClosed,
                fontSize = 11.5.sp,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

/**
 * Підказка про фонову доставку (#117): дозвіл є, а пуш однаково може не прийти.
 *
 * Жовтий, а не червоний: банер вище — блокер («сповіщень не буде взагалі»), а це
 * порада («можуть запізнитись»). Один колір на два різні за вагою стани зробив би
 * обидва однаково невиразними.
 *
 * Формулювання розділяє виміряне й припущене. Про оптимізацію батареї ми знаємо
 * від системи, тож кажемо прямо. Список автозапуску не читається жодним API —
 * там лише «перевірте», бо єдиний наш сигнал це виробник, а не сам телефон.
 * Видавати здогад за факт — найкоротший шлях до того, щоб наступну підказку
 * гортали не читаючи.
 *
 * Закривається назавжди: людина, яка вже сходила в налаштування (або свідомо
 * вирішила не йти), не має бачити ту саму пораду щодня.
 */
@Composable
private fun BackgroundDeliveryHintRow(
    hint: BackgroundDeliveryHint,
    onOpenSettings: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (hint is BackgroundDeliveryHint.None) return

    val (title, body) = when (hint) {
        is BackgroundDeliveryHint.BatteryOptimised ->
            "Сповіщення можуть запізнюватись" to
                "Система економить батарею й присипляє застосунок. Натисніть, щоб зняти обмеження."
        is BackgroundDeliveryHint.OemAutostart ->
            "Перевірте автозапуск" to
                "На телефонах цього виробника фонову роботу вимикає окремий список. Знайдіть у ньому AvelRen."
        is BackgroundDeliveryHint.BatteryAndAutostart ->
            "Сповіщення можуть не прийти" to
                "Зніміть обмеження батареї, а також перевірте автозапуск — на цьому телефоні це різні налаштування."
        is BackgroundDeliveryHint.None -> return
    }

    Row(
        Modifier
            .fillMaxWidth()
            .padding(top = 12.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(SignWarn)
            .hapticClickable { onOpenSettings() }
            .padding(start = 14.dp, end = 6.dp, top = 11.dp, bottom = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text("⏱", fontSize = 18.sp)
        Column(Modifier.weight(1f)) {
            Text(
                title,
                color = SignOnWarn,
                fontWeight = FontWeight.Black,
                fontSize = 12.5.sp,
                style = MaterialTheme.typography.bodyMedium,
            )
            Text(
                body,
                color = SignOnWarn,
                fontSize = 11.5.sp,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        // Окремий таргет: тап по рядку веде в налаштування, тап по хрестику —
        // ховає. Без цього закрити підказку можна було б лише сходивши туди.
        Text(
            "✕",
            color = SignOnWarn,
            fontSize = 15.sp,
            modifier = Modifier.tapNoRipple(onClick = onDismiss).padding(8.dp),
        )
    }
}

/**
 * Гейт беззвучної підписки (#117 крок 2): наполегливо, але прохідно. Дві дії —
 * увімкнути дозвіл або підписатись усе одно (тоді рядок нестиме позначку «беззвучна»).
 */
@Composable
private fun SilentSubscribeDialog(
    onEnable: () -> Unit,
    onSubscribeAnyway: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        FullTestDialog("Сповіщення вимкнені", onDismiss, actions = {
            FullTestDialogAction("Увімкнути сповіщення", onEnable, primary = true)
            FullTestDialogAction("Все одно підписатись", onSubscribeAnyway)
        }) {
            Text("Без дозволу на сповіщення підписка не зможе вас попередити — сервер надішле, але екран промовчить.",
                color = AppInk, style = MaterialTheme.typography.bodyMedium)
        }
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(PickerSheetBg)
                .border(1.dp, NavBorder, RoundedCornerShape(20.dp))
                .padding(20.dp),
        ) {
            Text(
                "Сповіщення вимкнені",
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "Без дозволу на сповіщення підписка не зможе вас попередити — " +
                    "сервер надішле, але екран промовчить.",
                color = AppInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(18.dp))
            Text(
                "Увімкнути сповіщення",
                color = PickerInk,
                fontWeight = FontWeight.Black,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(HeroYellow)
                    .hapticClickable { onEnable() }
                    .padding(vertical = 12.dp),
            )
            Spacer(Modifier.height(10.dp))
            Text(
                "Все одно підписатись",
                color = EmptyInk,
                fontWeight = FontWeight.Bold,
                fontSize = 12.5.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .hapticClickable { onSubscribeAnyway() }
                    .padding(vertical = 8.dp),
            )
        }
    }
}

/** Крок 2 додавання порога: діалог із чипами 50/100/150/200 для обраного КПП. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThresholdChooserDialog(
    checkpointTitle: String,
    onPick: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        FullTestDialog("Поріг сповіщення", onDismiss, actions = {
            FullTestDialogAction("Скасувати", onDismiss)
        }) {
            Text(checkpointTitle, color = AppInk, style = MaterialTheme.typography.titleMedium)
            Text("Сповістити, коли авто в черзі буде:", color = MaterialTheme.avelren.ink2,
                style = MaterialTheme.typography.bodyMedium)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(50, 100, 150, 200, 250, 300, 350, 400).forEach { value ->
                    PickerFilterChip("$value", active = false) { onPick(value) }
                }
            }
        }
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(PickerSheetBg)
                .border(1.dp, NavBorder, RoundedCornerShape(20.dp))
                .padding(20.dp),
        ) {
            Text(
                "Поріг сповіщення",
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                checkpointTitle,
                color = AppInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                "Сповістити, коли авто в черзі буде:",
                color = EmptyInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 12.sp,
            )
            Spacer(Modifier.height(10.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                listOf(50, 100, 150, 200, 250, 300, 350, 400).forEach { v ->
                    PickerFilterChip("$v", active = false) {
                        onPick(v)
                    }
                }
            }
        }
    }
}

// --- Час в'їзду: бейдж, підписи днів та діалог вибору ----------------------
private val ETA_DAY_FMT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("EE dd.MM", java.util.Locale("uk"))

/** Дата й час цілі: не плутати завтра з сьогоднішнім вимірюванням. */
private fun etaBadge(iso: String): String = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(KYIV)
        .format(DateTimeFormatter.ofPattern("dd.MM.uuuu 'о' HH:mm"))
}.getOrDefault("—")

/** Підпис дня для чипів: СЬОГОДНІ / ЗАВТРА / «ПТ 22.08». */
private fun etaDayLabel(today: java.time.LocalDate, off: Int): String = when (off) {
    0 -> "СЬОГОДНІ"
    1 -> "ЗАВТРА"
    else -> today.plusDays(off.toLong()).format(ETA_DAY_FMT).uppercase()
}

/** ISO-8601 з offset для createEtaTarget з обраних дня й часу (київський пояс). */
private fun etaIso(date: java.time.LocalDate, hour: Int): String {
    return date.atTime(hour, 0)
        .atZone(KYIV)
        .toOffsetDateTime()
        .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
}

/** Крок 2 «Час в'їзду»: вибір дня й часу для обраного КПП → ISO у createEtaTarget. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun EtaChooserDialog(
    checkpointTitle: String,
    onPick: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var now by remember { mutableStateOf(Instant.now()) }
    val today = now.atZone(KYIV).toLocalDate()
    var selectedDate by remember { mutableStateOf(today.plusDays(1)) }
    var hour by remember { mutableStateOf<Int?>(6) }
    var showError by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) {
        while (true) {
            delay(1_000)
            now = Instant.now()
        }
    }
    val hours = etaFutureHours(selectedDate, now, KYIV)
    val submit = {
        val current = Instant.now()
        now = current
        val selectedHour = hour
        if (selectedHour != null && etaTargetIsFuture(selectedDate, selectedHour, current, KYIV)) {
            onPick(etaIso(selectedDate, selectedHour))
        } else {
            hour = null
            showError = true
        }
    }
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        FullTestDialog("Час в'їзду", onDismiss, actions = {
            FullTestDialogAction("Стежити", submit, primary = true)
            FullTestDialogAction("Скасувати", onDismiss)
        }) {
            Text(checkpointTitle, color = AppInk, style = MaterialTheme.typography.titleMedium)
            Text("Коли плануєте в'їхати:", color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodyMedium)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                (0..4).forEach { off ->
                    val date = today.plusDays(off.toLong())
                    PickerFilterChip(etaDayLabel(today, off), active = selectedDate == date) {
                        selectedDate = date; hour = null; showError = false
                    }
                }
            }
            Text("Час за Києвом", color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                hours.forEach { value -> PickerFilterChip("%02d:00".format(value), active = hour == value) { hour = value; showError = false } }
            }
            if (hours.isEmpty()) {
                Text("На цей день майбутніх годин немає. Оберіть інший день.", color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
            } else if (showError || (hour != null && hour !in hours)) {
                Text("Оберіть майбутній час в'їзду.", color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
            }
        }
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(PickerSheetBg)
                .border(1.dp, NavBorder, RoundedCornerShape(20.dp))
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
        ) {
            Text(
                "Час в'їзду",
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                checkpointTitle,
                color = AppInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(16.dp))
            Text("Коли плануєте в'їхати:", color = EmptyInk, fontSize = 12.sp, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(10.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                (0..4).forEach { off ->
                    val date = today.plusDays(off.toLong())
                    PickerFilterChip(etaDayLabel(today, off), active = selectedDate == date) {
                        selectedDate = date; hour = null; showError = false
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                hours.forEach { h ->
                    PickerFilterChip("%02d:00".format(h), active = hour == h) {
                        hour = h
                        showError = false
                    }
                }
            }
            if (hours.isEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text("На цей день майбутніх годин немає. Оберіть інший день.", color = EmptyInk, style = MaterialTheme.typography.bodySmall)
            } else if (showError || (hour != null && hour !in hours)) {
                Spacer(Modifier.height(10.dp))
                Text("Оберіть майбутній час в'їзду.", color = EmptyInk, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(18.dp))
            Text(
                "Стежити",
                color = PickerInk,
                fontWeight = FontWeight.Black,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
                style = MaterialTheme.typography.bodyMedium,
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(HeroYellow)
                    .tapNoRipple {
                        submit()
                    }
                    .padding(vertical = 13.dp),
            )
        }
    }
}

// --- Прогноз черги --------------------------------------------------------
private val FORECAST_DATE: DateTimeFormatter = DateTimeFormatter.ofPattern("d MMMM", java.util.Locale("uk"))
private fun forecastReadyDate(iso: String): String = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(FORECAST_DATE)
}.getOrDefault(iso)

/**
 * Прогноз хвиль реєстрацій для обраного КПП. Читає `forecast()`:
 * collecting — модель ще вчиться (показуємо прогрес і дату готовності);
 * ready/preliminary — очікуваний пік черги з прогнозних точок.
 */
@Composable
private fun ForecastScreen(
    checkpointTitle: String,
    checkpointId: Int,
    onBack: () -> Unit,
    loadForecast: suspend (Int) -> Api.Forecast,
) {
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
    var loading by remember { mutableStateOf(true) }
    var failed by remember { mutableStateOf(false) }
    var reload by remember { mutableStateOf(0) }
    var horizonStart by remember { mutableStateOf(Instant.now()) }
    LaunchedEffect(checkpointId, reload) {
        loading = true
        failed = false
        horizonStart = Instant.now()
        runCatching { loadForecast(checkpointId) }
            .onSuccess { forecast = it; loading = false }
            .onFailure { failed = true; loading = false }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(MonitorBg)
            .windowInsetsPadding(WindowInsets.systemBars),
        contentPadding = PaddingValues(start = 20.dp, top = 8.dp, end = 20.dp, bottom = 72.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            if (BuildConfig.ENABLE_TEST_DRAWER) {
                TextButton(onClick = onBack, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("←  Назад до КПП", color = HeroYellow, fontWeight = FontWeight.Bold)
                }
            } else {
            Text(
                "←  Назад до КПП",
                color = HeroYellow,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp,
                modifier = Modifier.tapNoRipple(onClick = onBack).padding(vertical = 8.dp),
            )
            }
        }
        item {
            Column {
                Text(
                    "Прогноз черги",
                    color = AppInk,
                    fontWeight = FontWeight.Black,
                    fontSize = 28.sp,
                )
                Spacer(Modifier.height(4.dp))
                Text(checkpointTitle, color = HeroYellow, fontWeight = FontWeight.Bold, fontSize = 16.sp)
                Text(
                    "${horizonStart.atZone(KYIV).format(FORECAST_DATE)} · наступні 24 години",
                    color = EmptyInk,
                    fontSize = 13.sp,
                )
            }
        }

        val f = forecast
        when {
            loading -> item {
                Box(Modifier.fillMaxWidth().padding(vertical = 56.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = HeroYellow, strokeWidth = 2.dp)
                }
            }
            failed || f == null -> item {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    ForecastLine("Не вдалося завантажити прогноз.")
                    Text(
                        "Спробувати ще раз",
                        color = PickerInk,
                        fontWeight = FontWeight.Black,
                        textAlign = TextAlign.Center,
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .background(HeroYellow).hapticClickable { reload++ }.padding(14.dp),
                    )
                }
            }
            f.status == "ready" || f.status == "preliminary" -> {
                val todayPoints = ForecastPresentation.next24CountHours(
                    ForecastPresentation.displayPoints(f), horizonStart,
                )
                val peak = ForecastPresentation.countPeak(todayPoints)
                if (peak != null) {
                    item { ForecastPeakCard(peak) }
                    item {
                        Text(
                            "Погодинний прогноз",
                            color = AppInk,
                            fontWeight = FontWeight.Black,
                            fontSize = 17.sp,
                            modifier = Modifier.padding(top = 8.dp),
                        )
                    }
                    items(todayPoints, key = { it.time }) { point ->
                        ForecastHourRow(
                            point = point,
                            maxVehicles = todayPoints.maxOf { it.vehicles_expected },
                            isPeak = point.time == peak.time,
                        )
                    }
                } else item {
                    ForecastEmptyState(
                        "На наступні 24 години недостатньо даних для прогнозу.",
                    )
                }
            }
            else -> item {
                ForecastEmptyState(
                    "Модель ще збирає історію для цього КПП.",
                    detail = buildString {
                        append("Зібрано ${"%.1f".format(f.weeks_collected)} з ${f.weeks_needed} тижнів")
                        f.ready_at?.let { append(" · орієнтовна готовність ${forecastReadyDate(it)}") }
                    },
                )
            }
        }
        item { ForecastLine("Попередній прогноз. AI-модель ще в розробці.") }
    }
}

@Composable
private fun ForecastPeakCard(point: Api.CountForecastPoint) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
            .background(HeroYellow.copy(alpha = 0.12f))
            .border(1.dp, HeroYellow.copy(alpha = 0.45f), RoundedCornerShape(20.dp))
            .padding(18.dp),
    ) {
        Text("ПРОГНОЗОВАНА ЧЕРГА У НАЙБЛИЖЧИЙ ЧАС", color = HeroYellow, fontWeight = FontWeight.Black, fontSize = 12.sp)
        Spacer(Modifier.height(6.dp))
        Text("${point.vehicles_expected} авто", color = AppInk, fontWeight = FontWeight.Black, fontSize = 34.sp)
        Text("орієнтовно ${forecastHourLabel(point.time)}", color = HeroYellow, fontWeight = FontWeight.Bold, fontSize = 18.sp)
        Spacer(Modifier.height(8.dp))
        Text(forecastRangeLabel(point), color = EmptyInk, fontSize = 12.sp)
    }
}

@Composable
private fun ForecastHourRow(point: Api.CountForecastPoint, maxVehicles: Int, isPeak: Boolean) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        Column(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant).padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(forecastHourLabel(point.time), modifier = Modifier.weight(1f),
                    color = if (isPeak) HeroYellow else MaterialTheme.avelren.ink2, fontWeight = FontWeight.Bold, fontSize = 14.sp)
                Text("${point.vehicles_expected} авто", modifier = Modifier.weight(1f), textAlign = TextAlign.End,
                    color = AppInk, fontWeight = FontWeight.Bold, fontSize = 16.sp)
            }
            Text(forecastRangeLabel(point), color = MaterialTheme.avelren.ink2, fontSize = 12.sp)
            val fraction = if (maxVehicles > 0) (point.vehicles_expected.toFloat() / maxVehicles).coerceIn(0f, 1f) else 0f
            Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(MaterialTheme.avelren.line)) {
                Box(Modifier.fillMaxWidth(fraction).fillMaxHeight().background(HeroYellow.copy(alpha = if (isPeak) 1f else 0.58f)))
            }
        }
        return
    }
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            forecastHourLabel(point.time),
            modifier = Modifier.width(92.dp),
            color = if (isPeak) HeroYellow else EmptyInk,
            fontWeight = FontWeight.Bold,
            fontSize = 13.sp,
        )
        Column(Modifier.weight(1f)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text("${point.vehicles_expected} авто", color = AppInk, fontWeight = FontWeight.Bold, fontSize = 13.sp)
                Text(forecastRangeLabel(point), color = EmptyInk, fontSize = 11.sp)
            }
            Spacer(Modifier.height(5.dp))
            val fraction = if (maxVehicles > 0) (point.vehicles_expected.toFloat() / maxVehicles).coerceIn(0f, 1f) else 0f
            Box(Modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(AppInk.copy(alpha = 0.12f))) {
                Box(
                    Modifier.fillMaxWidth(fraction).fillMaxHeight()
                        .background(HeroYellow.copy(alpha = if (isPeak) 1f else 0.58f)),
                )
            }
        }
    }
}

private fun forecastHourLabel(time: String): String =
    runCatching {
        OffsetDateTime.parse(time).atZoneSameInstant(KYIV)
            .format(DateTimeFormatter.ofPattern("dd.MM HH:mm"))
    }.getOrDefault("—")

private fun forecastRangeLabel(point: Api.CountForecastPoint): String =
    if (point.vehicles_low != null && point.vehicles_high != null) {
        "Типовий розкид ${point.vehicles_low}–${point.vehicles_high} авто"
    } else {
        "Орієнтир за історичними даними"
    }

@Composable
private fun ForecastEmptyState(text: String, detail: String? = null) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
            .background(AppInk.copy(alpha = 0.05f)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(text, color = AppInk, fontWeight = FontWeight.Bold, fontSize = 15.sp)
        detail?.let { ForecastLine(it) }
    }
}

/** Рядок пояснення на екрані прогнозу (приглушений). */
@Composable
private fun ForecastLine(text: String) {
    Text(
        text,
        color = EmptyInk,
        style = MaterialTheme.typography.bodySmall,
        fontSize = 12.5.sp,
    )
}

/** Підтвердження прибирання рядка моніторингу — запобіжник від випадкового ✕. */
@Composable
private fun ConfirmRemoveDialog(
    row: MonitorRow,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val desc = when (row.kind) {
        MonitorKind.THRESHOLD -> "Поріг ${row.badge} авто · ${row.label}"
        MonitorKind.ETA -> "Час в'їзду ${row.badge} · ${row.label}"
    }
    ConfirmRemoveDialog(description = desc, onConfirm = onConfirm, onDismiss = onDismiss)
}

@Composable
internal fun ConfirmRemoveDialog(
    description: String,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        FullTestDialog("Прибрати з моніторингу?", onDismiss, actions = {
            FullTestDialogAction("Прибрати", onConfirm, primary = true)
            FullTestDialogAction("Скасувати", onDismiss)
        }) {
            Text(description, color = AppInk, style = MaterialTheme.typography.bodyMedium)
        }
        return
    }
    Dialog(onDismissRequest = onDismiss) {
        Column(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .background(PickerSheetBg)
                .border(1.dp, NavBorder, RoundedCornerShape(20.dp))
                .padding(20.dp),
        ) {
            Text(
                "Прибрати з моніторингу?",
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 15.sp,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                description,
                color = AppInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(20.dp))
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    "Скасувати",
                    color = HeroYellow,
                    fontWeight = FontWeight.Bold,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(12.dp))
                        .border(1.5.dp, PickerYellowHalf, RoundedCornerShape(12.dp))
                        .tapNoRipple(onClick = onDismiss)
                        .padding(vertical = 12.dp),
                )
                Text(
                    "Прибрати",
                    color = PickerInk,
                    fontWeight = FontWeight.Black,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    style = MaterialTheme.typography.bodyMedium,
                    modifier = Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(12.dp))
                        .background(HeroYellow)
                        .tapNoRipple {
                            onConfirm()
                        }
                        .padding(vertical = 12.dp),
                )
            }
        }
    }
}

@Composable
internal fun SettingsScreen(
    modifier: Modifier = Modifier,
    adminClient: AdminAccessClient? = null,
    adminServerClient: AdminServerClient? = null,
    onOpenPrivacyPolicy: (() -> Unit)? = null,
    initialPage: String = "menu",
    onPageChanged: ((String) -> Unit)? = null,
    menuContent: (@Composable ((String) -> Unit) -> Unit)? = null,
) {
    MaterialTheme(colorScheme = MaterialTheme.colorScheme) {
        androidx.compose.material3.Surface(
            modifier = modifier,
            color = AppBackground,
            contentColor = MaterialTheme.colorScheme.onSurface,
        ) {
            Column {
                HeaderRow(
                    showServerStatus = false,
                    title = "Налаштування",
                )
                AdministrationSettings(
                    Modifier.fillMaxWidth().weight(1f), adminClient, adminServerClient,
                    onOpenPrivacyPolicy, initialPage, onPageChanged,
                    menuContent,
                )
            }
        }
    }
}

@Composable
private fun AppUpdateDialog(
    ready: Boolean,
    actionPending: Boolean,
    onUpdate: () -> Unit,
    onDismiss: () -> Unit,
) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        FullTestDialog(if (ready) "Оновлення готове" else "Доступна нова версія", onDismiss, actions = {
            FullTestDialogAction(if (ready) "Встановити" else "Оновити", onUpdate,
                primary = true, enabled = !actionPending)
            FullTestDialogAction("Пізніше", onDismiss)
        }) {
            Text(if (ready) "Нову версію завантажено. Для встановлення AvelRen буде перезапущено."
                else "Оновіть AvelRen через Google Play, щоб отримати останні зміни.",
                color = AppInk, style = MaterialTheme.typography.bodyMedium)
        }
        return
    }
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Box(
            Modifier
                .fillMaxSize()
                .background(Color(0xCC000000))
                .padding(24.dp),
            contentAlignment = Alignment.Center,
        ) {
            Column(
                Modifier
                    .fillMaxWidth()
                    .widthIn(max = 420.dp)
                    .clip(RoundedCornerShape(16.dp))
                    .background(MonitorBg)
                    .border(1.dp, SignWarn, RoundedCornerShape(16.dp))
                    .padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(
                    if (ready) "ОНОВЛЕННЯ ГОТОВЕ" else "ДОСТУПНА НОВА ВЕРСІЯ",
                    color = HeroYellow,
                    fontWeight = FontWeight.Black,
                    fontSize = 19.sp,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    if (ready) "Нову версію завантажено. Для встановлення AvelRen буде перезапущено."
                    else "Оновіть AvelRen через Google Play, щоб отримати останні зміни.",
                    color = AppInk.copy(alpha = 0.8f),
                    fontSize = 13.sp,
                    lineHeight = 19.sp,
                    textAlign = TextAlign.Center,
                )
                Spacer(Modifier.height(18.dp))
                Text(
                    if (ready) "ВСТАНОВИТИ" else "ОНОВИТИ",
                    color = SignOnWarn,
                    fontWeight = FontWeight.Black,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .background(SignWarn)
                        .hapticClickable(enabled = !actionPending) { onUpdate() }
                        .padding(vertical = 13.dp),
                )
                Spacer(Modifier.height(14.dp))
                Text(
                    "ПІЗНІШЕ",
                    color = AppInk.copy(alpha = 0.7f),
                    fontWeight = FontWeight.Bold,
                    fontSize = 11.sp,
                    letterSpacing = 1.sp,
                    modifier = Modifier.hapticClickable { onDismiss() },
                )
            }
        }
    }
}

@Composable
internal fun SettingsDeveloperFooter(
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        if (!BuildConfig.ENABLE_TEST_DRAWER) {
            FadingHairline()
            Spacer(Modifier.height(8.dp))
        }
        Text(
            "DEVELOPER — TANKO VIKTOR",
            color = if (BuildConfig.ENABLE_TEST_DRAWER) MaterialTheme.avelren.ink2 else AppInk.copy(alpha = 0.4f),
            style = MaterialTheme.typography.labelSmall,
            fontSize = 9.sp,
            letterSpacing = 1.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
    }
}

// --- Нижня навігація (з Design) -------------------------------------------
// Плавуча закруглена панель поверх вмісту. На фото — напівпрозора з тінню;
// на моніторингу й налаштуваннях — рівна чорна без світлого ореолу.
private val MonitorBg: Color @Composable get() = AppBackground    // фон прогнозу й темних діалогів
private val NavGlass: Color @Composable get() = AppBackground     // rgba(10,10,10,.72)
private val NavBorder: Color @Composable get() = AppInk.copy(alpha = 0.14f)    // rgba(255,255,255,.14)
private val NavInactive: Color @Composable get() = AppInk.copy(alpha = 0.45f)  // rgba(255,255,255,.45)

@Composable
private fun BottomNavBar(
    activeTab: String,
    onSelect: (String) -> Unit,
    flatDark: Boolean,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .heightIn(min = 60.dp)
            .height(IntrinsicSize.Min)
            .shadow(if (flatDark) 0.dp else 8.dp, RoundedCornerShape(20.dp))
            .background(if (flatDark) AppBackground else NavGlass, RoundedCornerShape(20.dp))
            .border(1.dp, NavBorder, RoundedCornerShape(20.dp)),
    ) {
        NavTab("Головна", activeTab == "home", { onSelect("home") }, Modifier.weight(1f)) { HomeIcon(it) }
        NavTab("Моніторинг", activeTab == "monitor", { onSelect("monitor") }, Modifier.weight(1f)) { MonitorIcon(it) }
        NavTab("Налаштування", activeTab == "settings", { onSelect("settings") }, Modifier.weight(1f)) { SettingsIcon(it) }
    }
}

@Composable
private fun NavTab(
    label: String,
    active: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    icon: @Composable (Color) -> Unit,
) {
    val color = if (active) HeroYellow else NavInactive
    // Тактильний відгук на тап по вкладці — легкий «тік» кнопки. Через View,
    // бо він поважає системне налаштування вібро (нема — просто не спрацює).
    Column(
        modifier.fillMaxHeight().tapNoRipple {
            onClick()
        }.padding(vertical = 8.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        icon(color)
        Spacer(Modifier.height(3.dp))
        Text(
            label,
            color = color,
            fontWeight = FontWeight.Bold,
            fontSize = 10.sp,
            style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 0.sp),
            textAlign = TextAlign.Center,
        )
    }
}

/** Іконка «дім» (SVG-шлях макета, кути 1px спрощено до гострих). */
@Composable
private fun HomeIcon(color: Color) {
    Canvas(Modifier.size(20.dp)) {
        val s = size.minDimension / 24f
        val p = Path().apply {
            moveTo(4f * s, 11f * s); lineTo(12f * s, 4f * s); lineTo(20f * s, 11f * s)
            lineTo(20f * s, 20f * s); lineTo(19f * s, 21f * s); lineTo(15f * s, 21f * s)
            lineTo(15f * s, 15f * s); lineTo(9f * s, 15f * s); lineTo(9f * s, 21f * s)
            lineTo(5f * s, 21f * s); lineTo(4f * s, 20f * s); close()
        }
        drawPath(p, color, style = Stroke(width = 1.8f * s, join = StrokeJoin.Round, cap = StrokeCap.Round))
    }
}

/** Іконка «графік» — ламана + крапка справа (SVG-шлях макета). */
@Composable
private fun MonitorIcon(color: Color) {
    Canvas(Modifier.size(20.dp)) {
        val s = size.minDimension / 24f
        val p = Path().apply {
            moveTo(4f * s, 17f * s); lineTo(8f * s, 11f * s); lineTo(12f * s, 14f * s)
            lineTo(16f * s, 6f * s); lineTo(20f * s, 11f * s)
        }
        drawPath(p, color, style = Stroke(width = 1.8f * s, join = StrokeJoin.Round, cap = StrokeCap.Round))
        drawCircle(color, radius = 1.6f * s, center = Offset(20f * s, 11f * s))
    }
}

@Composable
private fun SettingsIcon(color: Color) {
    Icon(Icons.Filled.Settings, contentDescription = null, tint = color, modifier = Modifier.size(20.dp))
}

// Жовтий контент-колір hero — #F5C400 (той самий --warn, але тут це колір
// ТЕКСТУ на темному склі, не заливка).
private val HeroYellow: Color @Composable get() = SignWarn
// Макет: `background:rgba(10,10,10,.42)` РАЗОМ із `backdrop-filter:blur(18px)`.
// Compose не вміє розмивати фон під елементом, тож буквальні 42% на світлому
// небі у верхній частині фото лишають панель напівпрозорою й нечитабельною.
// Піднято до ~72%, щоб дати ту саму візуальну вагу, що дає blur у браузері.
private val HeroGlass: Color @Composable get() = AppBackground
private val HeroBorder: Color @Composable get() = AppInk.copy(alpha = 0.22f)   // rgba(255,255,255,.22)
private val HeroLine: Color @Composable get() = AppInk.copy(alpha = 0.35f)      // rgba(255,255,255,.35)

/**
 * Панель-герой за оновленим макетом: темна СКЛЯНА панель (не жовтий знак) із
 * жовтим текстом, уся клікабельна — тап відкриває вибір пункту. Назва КПП +
 * «ЗМІНИТИ» в рядок, число 64sp tabular з підписом «АВТО / В ЧЕРЗІ» збоку,
 * і рядок в'їзду через лінію. Пауза (немає entry_eta) прибирає лише той рядок.
 */
@Composable
private fun HeroPanel(item: Api.Workload, onOpenPicker: () -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(top = 38.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(AppBackground)
            .border(1.5.dp, SignWarn.copy(alpha = 0.5f), RoundedCornerShape(16.dp))
            .tapNoRipple(onClick = onOpenPicker)
            .padding(16.dp),
    ) {
        // Макет: `font:700 13px`, назва — ВЕЛИКИМИ (`title.toUpperCase()`).
        // Без «ЗМІНИТИ»: уся плитка клікабельна (`onOpenPicker`), тож окрема
        // підказка зайва. Пауза пояснюється червоним рядком під кількістю авто.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${item.flag_emoji ?: ""} ${item.title}".trim().uppercase(),
                color = HeroYellow,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f, fill = false),
            )
        }
        Spacer(Modifier.height(12.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${item.vehicles_in_queue}", color = HeroYellow, style = HeroNumberStyle)
            Spacer(Modifier.width(12.dp))
            // Макет: `font:700 11px; letter-spacing:1.5px; opacity:.85;
            // white-space:nowrap; align-self:center` — в ОДИН рядок, по центру.
            Text(
                "АВТО В ЧЕРЗІ",
                color = HeroYellow.copy(alpha = 0.85f),
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
            )
        }
        if (item.is_paused) {
            Text(
                "Черга на паузі",
                color = SignClosed,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        // Макет: `≈ {wait} очікування` — рядок часу очікування, коли він є.
        (WaitPresentation.label(item.wait_estimate)
            ?: formatWait(item.wait_time_seconds)?.let { "≈ $it очікування" })?.let { wait ->
            Text(
                wait,
                color = HeroYellow.copy(alpha = 0.85f),
                style = MaterialTheme.typography.bodySmall,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
        // Макет: `sc-if current.open` — блок в'їзду показується, коли є час
        // (entry_eta), незалежно від паузи. Роздільник — жовтий напівпрозорий.
        // Дизайнер змінив на два рядки: підпис 14px, під ним час 16px жирним
        // (без стрілки), а не один рядок «назва | час →».
        val measuredEta = WaitPresentation.entryEta(item)
        if (measuredEta != null) {
            Spacer(Modifier.height(14.dp))
            Box(Modifier.fillMaxWidth().height(2.dp).background(HeroYellow.copy(alpha = 0.5f)))
            Spacer(Modifier.height(12.dp))
            Text(
                "Якщо зараз стати в чергу, в'їзд буде:",
                color = HeroYellow,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(4.dp))
            // Макет: `current.eta` = день + час. Близькі дати — СЬОГОДНІ/ЗАВТРА,
            // далі — «дд.мм (день тижня)». Роздільник дати — крапка, не слеш.
            Text(
                formatHeroEta(measuredEta),
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                fontSize = 16.sp,
            )
        }
    }
}

// --- Пікер вибору КПП: темне скло (оновлений макет) -----------------------
// Дизайнер перевів пікер із жовтого аркуша на ТЕМНИЙ: чорне тло, жовтий текст,
// обрана картка — жовта заливка з темним текстом.
private val PickerSheetBg: Color @Composable get() = AppBackground   // тло аркуша
private val PickerRowBg: Color @Composable get() = MaterialTheme.colorScheme.surfaceVariant     // необрана картка
private val PickerInk: Color @Composable get() = AppOnAccent       // текст/рамка на жовтому
private val PickerSubOnYellow: Color @Composable get() = AppOnAccent.copy(alpha = 0.7f) // підпис на обраній картці (.7)
private val PickerYellowHalf: Color @Composable get() = SignWarn.copy(alpha = 0.5f)  // рамка неактивної пігулки (.5)
// Назви КПП і країн — білі, а не жовті: у списку з ~40 рядків жовтий текст на
// темному читається гірше за білий, а сам жовтий лишається носієм сигналу
// (табличка з чергою, обрана картка, активна пігулка) — там, де він щось
// означає, а не просто фарбує назву.
private val PickerNameInk: Color @Composable get() = AppInk

/**
 * Вибір пункту пропуску — повноекранний sheet за оновленим макетом: темне
 * тло, заголовок із ✕, фільтри-пігулки, що переносяться в рядок, далі
 * рядки-картки з табличкою числа.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CheckpointPickerSheet(
    workload: List<Api.Workload>,
    selectedId: Int,
    countryFilter: String?,
    onFilter: (String?) -> Unit,
    onPick: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    // Фільтр-прапори й відсортований список — лише коли змінились дані/фільтр,
    // а не на кожну рекомпозицію діалогу (сортування ~40 елементів щоразу).
    val flags = remember(workload) {
        workload.mapNotNull { it.flag_emoji }.distinct().sorted()
    }
    val rows = remember(workload, countryFilter) {
        (if (countryFilter == null) workload
        else workload.filter { it.flag_emoji == countryFilter })
            .sortedByDescending { it.vehicles_in_queue }
    }

    Dialog(
        onDismissRequest = onDismiss,
        properties = if (BuildConfig.ENABLE_TEST_DRAWER)
            DialogProperties(usePlatformDefaultWidth = true, decorFitsSystemWindows = false)
            else DialogProperties(usePlatformDefaultWidth = false),
    ) {
        if (BuildConfig.ENABLE_TEST_DRAWER) FullTestPickerWindowChrome()
        val pickerModifier = if (BuildConfig.ENABLE_TEST_DRAWER) {
            // Use the helper's MATCH_PARENT window constraints, as in the drawer,
            // instead of Compose 1.7's configuration-sized full-width measurement.
            Modifier.fillMaxSize()
                .background(PickerSheetBg).windowInsetsPadding(WindowInsets.safeDrawing)
        } else {
            Modifier.fillMaxSize().background(PickerSheetBg)
                .windowInsetsPadding(WindowInsets.systemBars)
        }
        Column(
            pickerModifier.padding(horizontal = 14.dp, vertical = 16.dp),
        ) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (BuildConfig.ENABLE_TEST_DRAWER) {
                    Text("Оберіть КПП", color = AppInk, style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    IconButton(onClick = onDismiss, modifier = Modifier.size(48.dp)) {
                        Icon(Icons.Filled.Close, contentDescription = "Закрити вибір КПП", tint = MaterialTheme.avelren.ink2)
                    }
                } else {
                // Макет: `font:900 10.5px; letter-spacing:2px; color:rgba(255,255,255,.6)`
                // → трекінг 2/10.5 = 0.19em.
                Text(
                    "ОБЕРІТЬ ПУНКТ ПРОПУСКУ",
                    style = MaterialTheme.typography.labelSmall,
                    fontSize = 10.5.sp,
                    fontWeight = FontWeight.Black,
                    letterSpacing = 0.19.em,
                    color = EmptyInk,
                )
                Text(
                    "✕",
                    color = EmptyInk,
                    fontSize = 17.sp,
                    modifier = Modifier.tapNoRipple(onClick = onDismiss).padding(4.dp),
                )
                }
            }
            Spacer(Modifier.height(12.dp))

            LazyColumn(
                modifier = if (BuildConfig.ENABLE_TEST_DRAWER) Modifier.weight(1f) else Modifier,
                contentPadding = if (BuildConfig.ENABLE_TEST_DRAWER) PaddingValues(bottom = 16.dp) else PaddingValues(0.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                // Макет: `flex-wrap:wrap; gap:8px` — пігулки переносяться в рядок,
                // а не стоять колонкою; знизу відступ ~16 до списку.
                item {
                    FlowRow(
                        Modifier.fillMaxWidth().padding(bottom = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        PickerFilterChip(
                            "Всі",
                            countryFilter == null,
                            inactiveColor = PickerNameInk,
                        ) { onFilter(null) }
                        flags.forEach { flag ->
                            PickerFilterChip(
                                countryLabel(flag),
                                countryFilter == flag,
                                inactiveColor = PickerNameInk,
                            ) { onFilter(flag) }
                        }
                    }
                }
                items(rows, key = { it.checkpoint_id }) { row ->
                    PickerRow(
                        item = row,
                        selected = row.checkpoint_id == selectedId,
                        onClick = { onPick(row.checkpoint_id) },
                    )
                }
                if (!BuildConfig.ENABLE_TEST_DRAWER) item { Spacer(Modifier.height(14.dp)) }
            }
        }
    }
}

/**
 * Пігулка фільтра (оновлений макет): текст на прозорому, активна — жовта
 * заливка з темним текстом. `padding:11px 16px; radius:99px; font:700 12.5px`.
 * Без `fillMaxWidth` — переноситься по ширині вмісту у `FlowRow`.
 *
 * `inactiveColor` існує тому, що ця пігулка малює ЧОТИРИ різні набори: країни
 * в аркуші вибору КПП, пороги, дні й години. Білими просили саме країни, тож
 * колір неактивного стану задає місце виклику, а не сама пігулка — інакше
 * побіліли б і пороги з годинами.
 */
@Composable
private fun PickerFilterChip(
    label: String,
    active: Boolean,
    inactiveColor: Color = HeroYellow,
    onClick: () -> Unit,
) {
    if (BuildConfig.ENABLE_TEST_DRAWER) {
        Box(
            Modifier.clip(RoundedCornerShape(16.dp))
                .background(if (active) HeroYellow else MaterialTheme.colorScheme.surfaceVariant)
                .border(1.dp, if (active) HeroYellow else MaterialTheme.avelren.line, RoundedCornerShape(16.dp))
                .heightIn(min = 48.dp)
                .semantics { selected = active; role = Role.Button }
                .tapNoRipple(onClick = onClick)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, color = if (active) PickerInk else AppInk, fontWeight = FontWeight.Bold,
                style = MaterialTheme.typography.bodyMedium)
        }
        return
    }
    Text(
        label,
        color = if (active) PickerInk else inactiveColor,
        style = MaterialTheme.typography.bodyMedium,
        fontSize = 12.5.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier
            .clip(RoundedCornerShape(99.dp))
            .background(if (active) HeroYellow else Color.Transparent)
            .border(
                1.5.dp,
                if (active) HeroYellow else PickerYellowHalf,
                RoundedCornerShape(99.dp),
            )
            .tapNoRipple(onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 11.dp),
    )
}

@Composable
private fun PickerRow(item: Api.Workload, selected: Boolean, onClick: () -> Unit) {
    // Кольори з `rowOf` макета: обрана — жовта заливка + темний текст/табличка;
    // необрана — темна картка з БІЛОЮ назвою (жовтий лишився табличці черги).
    val bg = if (selected) HeroYellow else PickerRowBg
    val nameColor = if (selected) PickerInk else PickerNameInk
    val subColor = if (selected) PickerSubOnYellow else EmptyInk
    val borderColor = if (selected) PickerInk else Color.Transparent
    val plateColor = if (selected) PickerInk else HeroYellow
    val shape = if (BuildConfig.ENABLE_TEST_DRAWER) RoundedCornerShape(20.dp) else RoadSignShape.Card
    // Дата в'їзду парситься раз на КПП (ключ — entry_eta), а не на кожен кадр
    // скролу: OffsetDateTime.parse + форматер помітно дорожчі за решту рядка.
    val entrySub = remember(item.entry_eta, item.wait_estimate) {
        WaitPresentation.entryEta(item)?.let { "в'їзд ${formatEntry(it)}" }
    }
    // Тактильний «тік» на вибір КПП — як на навпанелі; поважає системне вібро.
    Row(
        Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(bg)
            .border(if (BuildConfig.ENABLE_TEST_DRAWER) 1.dp else 2.dp,
                if (BuildConfig.ENABLE_TEST_DRAWER && !selected) MaterialTheme.avelren.line else borderColor, shape)
            .tapNoRipple {
                onClick()
            }
            .padding(horizontal = 15.dp, vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Макет: назва `font:700 14px`, підпис `font-size:12px; margin-top:2px`.
        // Іконка паузи — одразу після назви, коли пункт реально призупинено
        // (is_paused від єЧерги). Рядок нижче — це завжди час в'їзду, коли він є.
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "${item.flag_emoji ?: ""} ${item.title}".trim(),
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = 14.sp,
                    color = nameColor,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (item.is_paused) {
                    Spacer(Modifier.width(8.dp))
                    PauseBadge()
                }
            }
            if (entrySub != null) {
                Spacer(Modifier.height(2.dp))
                Text(
                    entrySub,
                    style = MaterialTheme.typography.bodySmall,
                    color = subColor,
                )
            }
        }
        Spacer(Modifier.width(12.dp))
        // Макет: `border:2px; border-radius:6px; padding:3px 10px; font:900 16px`.
        Text(
            "${item.vehicles_in_queue}",
            color = plateColor,
            style = MaterialTheme.typography.titleMedium.copy(
                fontWeight = FontWeight.Black,
                fontSize = 16.sp,
                fontFeatureSettings = TabularNumberFeature,
            ),
            modifier = Modifier
                .plateBorder(plateColor)
                .padding(horizontal = 10.dp, vertical = 3.dp),
        )
    }
}

// --- Графік «Динаміка реєстрацій» (з Design) ------------------------------
// Та сама «liquid glass» темна панель, що й hero (спільні HeroGlass/HeroBorder),
// у якій східчаста лінія показує кількість авто в черзі за останні 60 хв на
// ОБРАНОМУ КПП. Дані реальні: GET /history/{id}?hours=1 → 60 точок
// vehicles_in_queue (не генеруються). Лінія градієнтна зелений→жовтий→червоний
// (60 хв тому → зараз), під нею напівпрозора заливка, що згасає вниз.
private val ChartAxis: Color @Composable get() = AppInk.copy(alpha = 0.6f)     // осі/підписи — світлі напівпрозорі
private val ChartGrid: Color @Composable get() = AppInk.copy(alpha = 0.5f)     // пунктирна сітка (біла 50%)
private val ChartGreen = Color(0xFF38D66B)
private val ChartYellow = Color(0xFFF5C400)
private val ChartRed = Color(0xFFE5372B)

/** Приріст авто/хв, на якому колір стає повністю червоним (масовий наплив). */
private const val REG_HOT_RATE = 6f

/**
 * Колір за темпом реєстрацій — приростом черги за хвилину.
 * `delta ≤ 0` (черга не росте / зменшується) → зелений; поодинокі
 * реєстрації → жовтий; `delta ≥ REG_HOT_RATE` (масовий наплив) → червоний.
 */
private fun colorForRate(delta: Int): Color {
    val t = (delta / REG_HOT_RATE).coerceIn(0f, 1f)
    return if (t < 0.5f) lerp(ChartGreen, ChartYellow, t * 2f)
    else lerp(ChartYellow, ChartRed, (t - 0.5f) * 2f)
}

@Composable
private fun RegistrationChart(values: List<Int>?, modifier: Modifier = Modifier) {
    val gridInk = ChartGrid
    val pointOutline = AppInk
    val areaInk = AppInk
    val axisStyle = MaterialTheme.typography.bodySmall.copy(
        fontSize = 8.sp, fontWeight = FontWeight.Bold, color = ChartAxis,
    )
    Column(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(AppBackground)
            .border(1.5.dp, SignWarn.copy(alpha = 0.5f), RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "Динаміка черги",
            color = HeroYellow,
            fontWeight = FontWeight.Black,
            style = MaterialTheme.typography.bodyMedium,
            fontSize = 12.sp,
        )
        Spacer(Modifier.height(12.dp))

        // Графік показуємо і на паузі — історія черги існує незалежно від
        // того, рухається зараз пункт чи стоїть. Ховаємо лише коли точок
        // фізично замало (щойно завантажується / новий пункт без історії).
        val hasData = values != null && values.size > 1
        if (!hasData) {
            Box(
                Modifier.fillMaxWidth().height(96.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (values == null) "Завантаження…" else "Даних поки замало",
                    color = ChartAxis,
                    fontWeight = FontWeight.Bold,
                    style = MaterialTheme.typography.bodySmall,
                    fontSize = 11.sp,
                )
            }
            return@Column
        }

        val data = values!!
        val vMin = data.min()
        val vMax = data.max()
        val span = maxOf(4, vMax - vMin)          // мінімум 4, щоб рівна лінія не липла до краю
        // Три позначки осі Y: низ / середина / верх діапазону.
        val yLabels = listOf(vMin + span, vMin + span / 2, vMin)

        Text("Авто", color = ChartAxis, style = axisStyle)
        Spacer(Modifier.height(2.dp))

        // Висота полотна графіка. Тягнеться лише цей контейнер — уся геометрія
        // всередині Canvas рахується від size, тож нічого не ламається.
        Row(Modifier.fillMaxWidth().height(96.dp)) {
            // Колонка підписів осі Y.
            Column(
                Modifier.fillMaxHeight().padding(end = 6.dp),
                verticalArrangement = Arrangement.SpaceBetween,
            ) {
                yLabels.forEach { Text("$it", color = ChartAxis, style = axisStyle) }
            }
            // Полотно графіка.
            Canvas(Modifier.weight(1f).fillMaxHeight()) {
                val w = size.width
                val h = size.height
                val n = data.size
                fun x(i: Int) = w * i / (n - 1)
                fun y(v: Int) = h - (v - vMin).toFloat() / span * h

                // Пунктирна сітка на верхніх двох позначках.
                val dash = PathEffect.dashPathEffect(floatArrayOf(3f, 4f))
                listOf(yLabels[0], yLabels[1]).forEach { lv ->
                    val gy = y(lv)
                    drawLine(gridInk, Offset(0f, gy), Offset(w, gy), 1f, pathEffect = dash)
                }

                // Колір кожного відрізка — за темпом реєстрацій (приростом
                // черги за хвилину), а НЕ за позицією в часі: черга не росте →
                // зелений; поодинокі реєстрації → жовтий; масовий наплив →
                // червоний. Заливка під відрізком — того ж кольору, згасає вниз.
                // Лінія ПРЯМА: точки з'єднані навскіс (не сходинками) — так менше
                // «сходів», особливо на вищому полотні.
                val strokeW = 2.5.dp.toPx()
                if (BuildConfig.ENABLE_TEST_DRAWER) {
                    // One continuous area avoids seams between independently shaded segments.
                    // Rate colours remain on the measured line; the area is neutral decoration.
                    val area = Path().apply {
                        moveTo(x(0), h)
                        for (i in 0 until n) lineTo(x(i), y(data[i]))
                        lineTo(x(n - 1), h)
                        close()
                    }
                    drawPath(area, brush = Brush.verticalGradient(
                        0f to areaInk.copy(alpha = 0.12f), 1f to Color.Transparent,
                        startY = 0f, endY = h,
                    ))
                }
                for (i in 1 until n) {
                    val c = colorForRate(data[i] - data[i - 1])
                    val x0 = x(i - 1); val x1 = x(i)
                    val yPrev = y(data[i - 1]); val yCur = y(data[i])
                    // Заливка — трапеція під діагональним відрізком до низу.
                    if (!BuildConfig.ENABLE_TEST_DRAWER) {
                    val fill = Path().apply {
                        moveTo(x0, yPrev)
                        lineTo(x1, yCur)
                        lineTo(x1, h)
                        lineTo(x0, h)
                        close()
                    }
                    drawPath(
                        fill,
                        brush = Brush.verticalGradient(
                            0f to c.copy(alpha = 0.38f), 1f to Color.Transparent,
                            startY = minOf(yPrev, yCur), endY = h,
                        ),
                    )
                    }
                    // Сам відрізок — прямою від точки до точки.
                    drawLine(c, Offset(x0, yPrev), Offset(x1, yCur), strokeW, cap = StrokeCap.Round)
                }

                // Крапка «Зараз» — кольором ПОТОЧНОГО темпу реєстрацій.
                val cx = x(n - 1)
                val cy = y(data[n - 1])
                val nowColor = colorForRate(data[n - 1] - data[n - 2])
                drawCircle(nowColor, radius = 4.5.dp.toPx(), center = Offset(cx, cy))
                drawCircle(pointOutline, radius = 4.5.dp.toPx(), center = Offset(cx, cy), style = Stroke(2.dp.toPx()))
            }
        }
        Spacer(Modifier.height(4.dp))
        // Вісь X: 60 хв / 30 хв / Зараз.
        Row(Modifier.fillMaxWidth().padding(start = 30.dp)) {
            Text("60 хв", color = ChartAxis, style = axisStyle)
            Spacer(Modifier.weight(1f))
            Text("30 хв", color = ChartAxis, style = axisStyle)
            Spacer(Modifier.weight(1f))
            Text("Зараз", color = ChartAxis, style = axisStyle)
        }
    }
}

// Позначка паузи (з Design): кругла ЧЕРВОНА іконка з символом «пауза» —
// дві вертикальні білі смужки. Показується біля назви пункту, коли рух через
// КПП тимчасово зупинено (єЧерга: «Черга затримується» — закриття МАПП через
// негоду/технічні причини/дії сусідньої країни; місце в черзі зберігається,
// але заїзд наразі не відбувається).
private val PauseRed = SignClosed

@Composable
private fun PauseBadge(size: Dp = 20.dp) {
    Box(
        Modifier.size(size).clip(CircleShape).background(PauseRed),
        contentAlignment = Alignment.Center,
    ) {
        // Макет: дві смужки 3×9px із проміжком 3px у колі 20px.
        Row(horizontalArrangement = Arrangement.spacedBy(size * 0.15f)) {
            repeat(2) {
                Box(
                    Modifier
                        .size(width = size * 0.15f, height = size * 0.45f)
                        .clip(RoundedCornerShape(size * 0.05f))
                        .background(Color.White)
                )
            }
        }
    }
}

/** "2 дн 3 год 40 хв" з wait_time_seconds. 0 або менше → null (рядок ховаємо). */
private fun formatWait(seconds: Int): String? {
    if (seconds <= 0) return null
    val mins = seconds / 60
    val d = mins / 1440
    val h = (mins % 1440) / 60
    val m = mins % 60
    return buildString {
        if (d > 0) append("$d дн ")
        if (h > 0 || d > 0) append("$h год ")
        append("$m хв")
    }.trim()
}

// Формат дати в'їзду для hero — точно як `current.eta` макета: близькі дати
// словом ВЕЛИКИМИ, далі «дд.мм (день тижня)». День тижня — з малих (як uk-UA
// weekday long), роздільник дати — КРАПКА (дизайнер прибрав слеш).
private val HERO_DATE: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM", java.util.Locale("uk"))
private val HERO_WEEKDAY: DateTimeFormatter = DateTimeFormatter.ofPattern("EEEE", java.util.Locale("uk"))
private val HERO_TIME: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")
private fun formatHeroEta(iso: String): String = runCatching {
    val zoned = OffsetDateTime.parse(iso).atZoneSameInstant(KYIV)
    val today = java.time.LocalDate.now(KYIV)
    val time = zoned.format(HERO_TIME)
    when (zoned.toLocalDate()) {
        today -> "СЬОГОДНІ $time"
        today.plusDays(1) -> "ЗАВТРА $time"
        else -> "${zoned.format(HERO_DATE)} (${zoned.format(HERO_WEEKDAY)}) $time"
    }
}.getOrDefault(iso)

/** "СЬОГОДНІ HH:mm" / "ЗАВТРА HH:mm" для близьких дат, інакше "dd.MM о HH:mm". */
private fun formatEntry(iso: String): String = runCatching {
    val zoned = OffsetDateTime.parse(iso).atZoneSameInstant(KYIV)
    val today = java.time.LocalDate.now(KYIV)
    when (zoned.toLocalDate()) {
        today -> "сьогодні ${zoned.format(DateTimeFormatter.ofPattern("HH:mm"))}"
        today.plusDays(1) -> "завтра ${zoned.format(DateTimeFormatter.ofPattern("HH:mm"))}"
        else -> zoned.format(FORMAT)
    }
}.getOrDefault(iso)

private val TARGET_FMT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM HH:mm")
private fun formatTarget(iso: String): String =
    runCatching { OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(TARGET_FMT) }
        .getOrDefault(iso)

/** Delivery readiness is independent of authenticated installation readiness. */
@Composable
private fun PushSyncStatus(state: PushSyncState?, onRetry: () -> Unit) {
    if (state == null || state == PushSyncState.Synced) return
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(
            when (state) {
                PushSyncState.Pending, PushSyncState.Retrying -> "Синхронізуємо сповіщення…"
                PushSyncState.Rejected -> "Не вдалося синхронізувати сповіщення. Спробуйте ще раз."
                else -> "Сповіщення тимчасово недоступні. Спробуйте ще раз."
            },
            style = MaterialTheme.typography.bodySmall,
        )
        if (state == PushSyncState.ConflictBlocked || state == PushSyncState.Rejected) {
            TextButton(onClick = onRetry) { Text("Спробувати ще раз") }
        }
    }
}
