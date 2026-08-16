package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import ua.avelren.app.AvelRenApp
import ua.avelren.app.R
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.InstallationState
import ua.avelren.app.data.LiveRefresh
import ua.avelren.app.data.NotificationPermissionState
import ua.avelren.app.data.ProtectedLoad
import ua.avelren.app.ui.theme.HeroNumberStyle
import ua.avelren.app.ui.theme.RoadSignShape
import ua.avelren.app.ui.theme.SignPanel
import ua.avelren.app.ui.theme.ThemeMode
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.plateBorder
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val THRESHOLDS = listOf(50, 100, 150, 200, 250, 300, 350, 400, 450, 500)
private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

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

private fun countryLabel(flag: String?): String {
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
fun AvelRenScreen(
    permissionState: NotificationPermissionState = NotificationPermissionState.Granted,
    onRequestPermission: () -> Unit = {},
    onOpenSettings: () -> Unit = {},
    themeMode: ThemeMode = ThemeMode.SYSTEM,
    onThemeChange: (ThemeMode) -> Unit = {},
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val lifecycleOwner = LocalLifecycleOwner.current
    val installation = remember { AvelRenApp.from(context).installation }
    val installState by installation.state.collectAsStateWithLifecycle()
    val authReady = installState is InstallationState.Ready

    var workload by remember { mutableStateOf<List<Api.Workload>>(emptyList()) }
    var selected by remember { mutableStateOf(DeviceStore.selectedCheckpoint(context)) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshError by remember { mutableStateOf(false) }
    var forecastError by remember { mutableStateOf(false) }
    // Оновлюється КОЖЕН poll (навіть якщо payload не змінився), щоб freshness
    // рухалась і UI переходив у stale, коли collector завис, а API віддає той
    // самий snapshot (B2).
    var freshnessNow by remember { mutableStateOf(Instant.now()) }
    var showEtaDialog by remember { mutableStateOf(false) }
    var showThemeDialog by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
    var telemetry by remember { mutableStateOf<Api.Telemetry?>(null) }
    var subs by remember { mutableStateOf<List<Api.Subscription>>(emptyList()) }
    var targets by remember { mutableStateOf<List<Api.EtaTarget>>(emptyList()) }
    var reload by remember { mutableStateOf(0) }
    var countryFilter by remember { mutableStateOf<String?>(null) }

    // Живе оновлення (AND-4): refresh одразу при вході/поверненні, далі кожні
    // 60 c — але ЛИШЕ у foreground (repeatOnLifecycle(RESUMED) паузить при
    // згортанні й перезапускає при поверненні → миттєвий refresh). Ключ на
    // `selected`, щоб зміна КПП одразу оновила forecast, не чекаючи циклу.
    // Workload і forecast — незалежні: збій одного не блокує інший, і при
    // помилці останні валідні дані НЕ стираються (keep-last).
    LaunchedEffect(lifecycleOwner, selected) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            LiveRefresh.poll {
                val wlRes = runCatching { Api.workload() }
                workload = LiveRefresh.keepOnError(workload, wlRes)
                wlRes
                    .onSuccess { error = null; refreshError = false }
                    .onFailure { e -> if (workload.isEmpty()) error = e.message else refreshError = true }

                if (selected > 0) {
                    val fcRes: Result<Api.Forecast?> = runCatching { Api.forecast(selected) }
                    // keep-last лише для того самого КПП: forecast(A) не має
                    // лишитися під карткою КПП B (B1).
                    forecast = LiveRefresh.scopedForecast(forecast, fcRes, selected)
                    forecastError = fcRes.isFailure
                } else {
                    forecast = null
                    forecastError = false
                }
                // Годинник свіжості рухається щополл, незалежно від payload.
                freshnessNow = Instant.now()
                loading = false
            }
        }
    }

    // Protected-дані завантажуються тим самим seam, що покритий тестом
    // (ProtectedLoad.observe): щойно installation стає Ready — вантажимо; новий
    // Ready після recovery-перереєстрації ретригерить сам, без restart. `reload`
    // перезапускає effect (StateFlow одразу реплеїть поточний Ready), тож
    // локальна мутація теж оновлює дані.
    LaunchedEffect(reload) {
        ProtectedLoad.observe(installation.state) {
            subs = runCatching {
                installation.authenticatedCall { Api.subscriptions(it) }
            }.getOrDefault(emptyList())
            targets = runCatching {
                installation.authenticatedCall { Api.etaTargets(it) }
            }.getOrDefault(emptyList())
            // 403 для звичайного пристрою — картка просто не зʼявиться.
            telemetry = runCatching {
                installation.authenticatedCall { Api.telemetry(it) }
            }.getOrNull()
        }
    }

    val current = workload.firstOrNull { it.checkpoint_id == selected }

    if (loading) {
        Row(
            modifier = Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.Center,
            verticalAlignment = Alignment.CenterVertically,
        ) { CircularProgressIndicator() }
        return
    }

    // Свіжість за server observation time обраного КПП (без вибору — макс. по
    // списку). Якщо обраний зник зі snapshot — current==null → time==null →
    // stale, чужим часом не підміняємо.
    val obsTime = if (selected > 0) current?.time else workload.mapNotNull { it.time }.maxOrNull()
    val freshness = if (workload.isNotEmpty()) LiveRefresh.freshness(obsTime, freshnessNow) else null

    val filteredWorkload = (
        if (countryFilter == null) workload else workload.filter { it.flag_emoji == countryFilter }
        ).sortedByDescending { it.vehicles_in_queue }
    val availableFlags = workload.mapNotNull { it.flag_emoji }.distinct()

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.systemBars)
            .padding(horizontal = 16.dp)
    ) {
        item {
            HeaderRow(
                freshness = freshness,
                errorNote = when {
                    refreshError -> "Не вдалося оновити"
                    forecastError -> "Прогноз не оновився"
                    else -> null
                },
                onThemeClick = { showThemeDialog = true },
            )
        }

        // AND-2: сповіщення заблоковані — алерт не дійде. Це сенс застосунку,
        // тож показуємо явно і даємо шлях назад (запит або потрібні налаштування).
        if (permissionState !is NotificationPermissionState.Granted) {
            item { NotificationBanner(permissionState, onRequestPermission, onOpenSettings) }
        }

        // Full-screen помилка лише коли даних ще нема взагалі. Якщо є старий
        // валідний snapshot — не затираємо екран, статус показує пілюля вище.
        if (workload.isEmpty()) {
            error?.let { msg ->
                item {
                    Text("Не вдалося завантажити: $msg",
                        modifier = Modifier.padding(top = 24.dp))
                }
            }
        }

        if (current != null) {
            item { HeroPanel(current) }

            item {
                NotificationsCard(
                    authReady = authReady,
                    subscriptions = subs,
                    targets = targets,
                    selectedCheckpointId = current.checkpoint_id,
                    note = note,
                    onPickThreshold = { threshold ->
                        scope.launch {
                            runCatching {
                                installation.authenticatedCall {
                                    Api.subscribe(it, current.checkpoint_id, threshold)
                                }
                            }
                                .onSuccess { note = "Стежу: поріг $threshold авто"; reload++ }
                                .onFailure { note = "Не вдалося підписатись" }
                        }
                    },
                    onOpenEtaDialog = { showEtaDialog = true },
                    onRemoveSubscription = { id ->
                        scope.launch {
                            runCatching { installation.authenticatedCall { Api.unsubscribe(it, id) } }
                            reload++
                        }
                    },
                    onRemoveTarget = { id ->
                        scope.launch {
                            runCatching { installation.authenticatedCall { Api.deleteEtaTarget(it, id) } }
                            reload++
                        }
                    },
                )
            }

            // Defense-in-depth (B1): навіть якщо в стан просочився прогноз
            // іншого КПП — під карткою обраного його не показуємо.
            item { ForecastCard(forecast?.takeIf { it.checkpoint_id == selected }) }
            item { TelemetryCard(telemetry) }
        }

        item {
            Column(modifier = Modifier.padding(top = 20.dp, bottom = 4.dp)) {
                Text(
                    "УСІ ПУНКТИ",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.avelren.ink,
                )
                Text(
                    if (current == null) "Оберіть пункт пропуску" else "Змінити пункт",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.avelren.ink2,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
        }

        if (availableFlags.size > 1) {
            item { CountryFilterRow(availableFlags, countryFilter) { countryFilter = it } }
        }

        items(filteredWorkload) { item ->
            CheckpointRow(item) {
                selected = item.checkpoint_id
                DeviceStore.saveSelectedCheckpoint(context, item.checkpoint_id)
            }
        }

        item { Column(modifier = Modifier.padding(bottom = 32.dp)) {} }
    }

    if (showThemeDialog) {
        AlertDialog(
            onDismissRequest = { showThemeDialog = false },
            title = { Text("Тема застосунку") },
            text = { ThemeToggle(mode = themeMode, onChange = onThemeChange) },
            confirmButton = {
                TextButton(onClick = { showThemeDialog = false }) { Text("Готово") }
            },
        )
    }

    if (showEtaDialog && current != null) {
        EtaTargetDialog(
            checkpointTitle = current.title,
            onDismiss = { showEtaDialog = false },
            onConfirm = { isoUtc, human ->
                showEtaDialog = false
                scope.launch {
                    runCatching {
                        installation.authenticatedCall {
                            Api.createEtaTarget(it, current.checkpoint_id, isoUtc)
                        }
                    }
                        .onSuccess { note = "Стежу за в'їздом $human"; reload++ }
                        .onFailure { note = "Не вдалося створити ціль" }
                }
            },
        )
    }
}

/** Шапка: wordmark, пілюля свіжості (зелена крапка / бурштин "застаріло"), іконка теми. */
@Composable
private fun HeaderRow(
    freshness: LiveRefresh.Freshness?,
    errorNote: String?,
    onThemeClick: () -> Unit,
) {
    Column(modifier = Modifier.padding(top = 16.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("AVELREN", style = MaterialTheme.typography.headlineMedium,
                    color = MaterialTheme.avelren.ink)
                if (freshness != null) {
                    Spacer(Modifier.width(10.dp))
                    FreshnessPill(freshness)
                }
            }
            ThemeIconButton(onClick = onThemeClick)
        }
        errorNote?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.avelren.closed,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
private fun FreshnessPill(f: LiveRefresh.Freshness) {
    val dotColor = if (f.stale) MaterialTheme.avelren.warn else MaterialTheme.avelren.go
    val text = if (f.stale) "дані застарілі" else f.label
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .clip(RoadSignShape.Plate)
            .background(MaterialTheme.avelren.panel)
            .plateBorder(MaterialTheme.avelren.line)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    ) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(dotColor))
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.avelren.ink2)
    }
}

/** Проста двоколірна крапка сонце/місяць — без нової залежності на іконки. */
@Composable
private fun ThemeIconButton(onClick: () -> Unit) {
    Box(
        modifier = Modifier
            .size(36.dp)
            .clip(RoadSignShape.Plate)
            .plateBorder(MaterialTheme.avelren.line)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(Modifier.size(16.dp).clip(CircleShape).background(MaterialTheme.avelren.ink))
        Box(
            Modifier
                .size(16.dp)
                .padding(start = 6.dp)
                .clip(CircleShape)
                .background(MaterialTheme.avelren.panel)
        )
    }
}

/**
 * Герой: зелена панель-знак обраного КПП. Число черги — 64sp tabular. Без
 * спарклайна й дельти — даних для тренду ще немає, місця під них не лишаємо.
 * Призупинений КПП (немає entry_eta) — панель у сигнальному червоному.
 */
@Composable
private fun HeroPanel(item: Api.Workload) {
    val avelren = MaterialTheme.avelren
    val paused = item.entry_eta == null
    val fill = if (paused) avelren.closed else avelren.go
    val inner = if (paused) avelren.closed else avelren.goDeep
    val onFill = if (paused) avelren.onClosed else avelren.onGo

    SignPanel(
        fillColor = fill,
        frameColor = avelren.frame,
        innerColor = inner,
        modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
    ) {
        Text(
            "${item.flag_emoji ?: ""} ${item.title}".trim().uppercase(),
            color = onFill,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.Black,
        )
        Spacer(Modifier.height(14.dp))
        Text(
            "${item.vehicles_in_queue}",
            color = onFill,
            style = HeroNumberStyle,
        )
        Text(
            "АВТО В ЧЕРЗІ",
            color = onFill,
            style = MaterialTheme.typography.labelMedium,
        )
        Spacer(Modifier.height(14.dp))
        Box(Modifier.fillMaxWidth().height(1.dp).background(onFill.copy(alpha = 0.35f)))
        Spacer(Modifier.height(12.dp))
        Text(
            if (!paused) {
                "Станеш зараз — в'їзд ${formatEntry(item.entry_eta!!)} →"
            } else {
                "Черга призупинена, прогнозу немає"
            },
            color = onFill,
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}

@Composable
private fun NotificationsCard(
    authReady: Boolean,
    subscriptions: List<Api.Subscription>,
    targets: List<Api.EtaTarget>,
    selectedCheckpointId: Int,
    note: String?,
    onPickThreshold: (Int) -> Unit,
    onOpenEtaDialog: () -> Unit,
    onRemoveSubscription: (Long) -> Unit,
    onRemoveTarget: (Long) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text("СПОВІЩЕННЯ", style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.avelren.ink)

            Spacer(Modifier.height(10.dp))
            Text(
                "Сповістити, коли черга зросте до:",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.avelren.ink2,
            )
            Spacer(Modifier.height(8.dp))
            ThresholdChips(
                selectedThresholds = subscriptions
                    .filter { it.checkpoint_id == selectedCheckpointId }
                    .map { it.threshold }
                    .toSet(),
                enabled = authReady,
                onPick = onPickThreshold,
            )

            Spacer(Modifier.height(12.dp))
            Button(
                onClick = onOpenEtaDialog,
                enabled = authReady,
                shape = RoadSignShape.Plate,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.avelren.panel,
                    contentColor = MaterialTheme.avelren.ink,
                ),
                modifier = Modifier.fillMaxWidth().plateBorder(MaterialTheme.avelren.line),
            ) { Text("В'ЇХАТИ О ПЕВНІЙ ГОДИНІ") }

            if (!authReady) {
                Text(
                    "Підключення…",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.avelren.ink2,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
            note?.let {
                Text(
                    it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.avelren.ink2,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            if (subscriptions.isNotEmpty() || targets.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                subscriptions.forEach { s ->
                    SubscriptionPlateRow(
                        title = "${s.flag_emoji ?: ""} ${s.title}",
                        plateText = "${s.threshold}",
                        enabled = authReady,
                        onRemove = { onRemoveSubscription(s.id) },
                    )
                }
                targets.forEach { t ->
                    SubscriptionPlateRow(
                        title = "${t.flag_emoji ?: ""} ${t.title}",
                        plateText = formatTarget(t.target_at),
                        enabled = authReady,
                        onRemove = { onRemoveTarget(t.id) },
                    )
                }
            }
        }
    }
}

@Composable
private fun SubscriptionPlateRow(
    title: String,
    plateText: String,
    enabled: Boolean,
    onRemove: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            title,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.avelren.ink,
            modifier = Modifier.weight(1f),
        )
        Text(
            plateText,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.avelren.ink,
            modifier = Modifier
                .padding(horizontal = 8.dp)
                .plateBorder(MaterialTheme.avelren.line)
                .padding(horizontal = 8.dp, vertical = 4.dp),
        )
        // Protected-дія: у non-Ready стані видалення неактивне (B4).
        Text(
            "✕",
            color = if (enabled) MaterialTheme.avelren.closed else MaterialTheme.avelren.ink2,
            fontWeight = FontWeight.Black,
            modifier = Modifier
                .clickable(enabled = enabled, onClick = onRemove)
                .padding(6.dp),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThresholdChips(selectedThresholds: Set<Int>, enabled: Boolean, onPick: (Int) -> Unit) {
    // FlowRow сам переносить чипи на потрібну кількість рядів. Раніше тут
    // був вкладений список — саме він і ламав прокручування всього екрана.
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        THRESHOLDS.forEach { t ->
            val active = t in selectedThresholds
            Text(
                "$t",
                color = if (active) MaterialTheme.avelren.onGo else MaterialTheme.avelren.ink,
                style = MaterialTheme.typography.labelMedium,
                modifier = Modifier
                    .clip(RoadSignShape.Plate)
                    .background(if (active) MaterialTheme.avelren.go else MaterialTheme.avelren.panel)
                    .plateBorder(if (active) MaterialTheme.avelren.goDeep else MaterialTheme.avelren.line)
                    .clickable(enabled = enabled) { onPick(t) }
                    .padding(horizontal = 12.dp, vertical = 8.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CountryFilterRow(flags: List<String>, selected: String?, onSelect: (String?) -> Unit) {
    FlowRow(
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        modifier = Modifier.padding(bottom = 10.dp),
    ) {
        FilterChip(label = "УСІ", active = selected == null) { onSelect(null) }
        flags.forEach { flag ->
            FilterChip(label = countryLabel(flag), active = selected == flag) { onSelect(flag) }
        }
    }
}

@Composable
private fun FilterChip(label: String, active: Boolean, onClick: () -> Unit) {
    Text(
        label,
        color = if (active) MaterialTheme.avelren.onGo else MaterialTheme.avelren.ink,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier
            .clip(RoadSignShape.Plate)
            .background(if (active) MaterialTheme.avelren.go else MaterialTheme.avelren.panel)
            .plateBorder(if (active) MaterialTheme.avelren.goDeep else MaterialTheme.avelren.line)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    )
}

@Composable
private fun NotificationBanner(
    state: NotificationPermissionState,
    onRequest: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val channelBlocked = state is NotificationPermissionState.NeedsAlertChannelSettings
    Card(modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                stringResource(
                    if (channelBlocked) R.string.notif_channel_blocked_title
                    else R.string.notif_blocked_title
                ),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.avelren.closed,
            )
            // NeedsRequest — системний діалог ще можливий; решта станів
            // (permanent denial, revoke, вимкнений канал) лікуються лише в
            // налаштуваннях, тож і кнопка веде саме туди.
            val canAskInApp = state is NotificationPermissionState.NeedsRequest
            Button(
                onClick = if (canAskInApp) onRequest else onOpenSettings,
                shape = RoadSignShape.Plate,
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.avelren.warn,
                    contentColor = MaterialTheme.avelren.onWarn,
                ),
                modifier = Modifier.padding(top = 8.dp),
            ) {
                Text(
                    stringResource(
                        if (canAskInApp) R.string.notif_allow else R.string.notif_open_settings
                    )
                )
            }
        }
    }
}

@Composable
private fun CheckpointRow(item: Api.Workload, onClick: () -> Unit) {
    val avelren = MaterialTheme.avelren
    val paused = item.entry_eta == null
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                "${item.flag_emoji ?: ""} ${item.title}",
                style = MaterialTheme.typography.bodyMedium,
                color = avelren.ink,
            )
            Text(
                if (paused) "призупинено" else "в'їзд ${formatEntry(item.entry_eta!!)}",
                style = MaterialTheme.typography.bodySmall,
                color = if (paused) avelren.closed else avelren.ink2,
            )
        }
        Text(
            if (paused) "СТОП" else "${item.vehicles_in_queue}",
            color = if (paused) avelren.onClosed else avelren.ink,
            fontWeight = FontWeight.Black,
            style = MaterialTheme.typography.labelMedium,
            modifier = Modifier
                .clip(RoadSignShape.Plate)
                .background(if (paused) avelren.closed else avelren.panel)
                .plateBorder(if (paused) avelren.closed else avelren.line)
                .padding(horizontal = 10.dp, vertical = 6.dp),
        )
    }
}

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
