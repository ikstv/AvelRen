package ua.avelren.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBars
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
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import android.view.HapticFeedbackConstants
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import kotlinx.coroutines.launch
import ua.avelren.app.R
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.LiveRefresh
import ua.avelren.app.data.NetworkAvailability
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
fun AvelRenScreen() {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current

    var workload by remember { mutableStateOf<List<Api.Workload>>(emptyList()) }
    var selected by remember { mutableStateOf(DeviceStore.selectedCheckpoint(context)) }
    var loading by remember { mutableStateOf(true) }
    var refreshError by remember { mutableStateOf(false) }
    // Оновлюється КОЖЕН poll (навіть якщо payload не змінився), щоб freshness
    // рухалась і UI переходив у stale, коли collector завис, а API віддає той
    // самий snapshot (B2).
    var freshnessNow by remember { mutableStateOf(Instant.now()) }
    var countryFilter by remember { mutableStateOf<String?>(null) }
    var showPicker by remember { mutableStateOf(false) }
    // Активна вкладка нижньої навігації. Окремого екрана «Моніторинг» ще нема
    // (у макеті теж лише підсвітка), тож поки це тільки стан підсвітки.
    var activeTab by remember { mutableStateOf("home") }
    // Динаміка реєстрацій обраного КПП за останню годину. null — ще не
    // завантажено; порожній список — сервер віддав, але точок замало.
    var history by remember { mutableStateOf<List<Int>?>(null) }

    // Пороги (threshold-підписки) — екран 04, плитка «Пороги». Реальні дані з
    // сервера: subscriptions()/subscribe()/unsubscribe(). Флоу: тап по плитці →
    // пікер КПП → вибір порога (50/100/150/200) → subscribe.
    val scope = rememberCoroutineScope()
    val creds = remember { DeviceStore.credentials(context) }
    var subscriptions by remember { mutableStateOf<List<Api.Subscription>>(emptyList()) }
    var etaTargets by remember { mutableStateOf<List<Api.EtaTarget>>(emptyList()) }
    // Порожній список сам по собі НЕ означає «підписок немає» — рівно так само
    // виглядає список, який ще не вдалося завантажити (офлайн-старт). Без цього
    // прапорця UI стверджував «Нема вибраних вами КПП», хоча підписки є (#107).
    // true лише після успішної відповіді сервера.
    var monitorsLoaded by remember { mutableStateOf(false) }
    var showThresholdCpPicker by remember { mutableStateOf(false) }
    var pendingThresholdCp by remember { mutableStateOf<Api.Workload?>(null) }
    var showEtaCpPicker by remember { mutableStateOf(false) }
    var pendingEtaCp by remember { mutableStateOf<Api.Workload?>(null) }
    // AI-прогноз — читання (не підписка): обрав КПП → показуємо прогноз.
    var showAiCpPicker by remember { mutableStateOf(false) }
    var pendingAiCp by remember { mutableStateOf<Api.Workload?>(null) }
    // Рядок, який ✕ пропонує прибрати — тримаємо до підтвердження (запобіжник
    // від випадкового тапу). Саме видалення — лише після «Прибрати».
    var pendingRemove by remember { mutableStateOf<MonitorRow?>(null) }
    // Одне тіло завантаження моніторингу на всі тригери — старт, зміна вкладки,
    // відновлення мережі, полл, зміни підписок, — щоб вони не розійшлись у
    // поведінці. Прапорець зводиться лише коли ОБИДВА запити вдались: інакше
    // напівпорожній список видавали б за повний.
    val loadMonitors: suspend () -> Unit = {
        creds?.let { c ->
            val subsRes = runCatching { Api.subscriptions(c) }.onSuccess { subscriptions = it }
            val tgtRes = runCatching { Api.etaTargets(c) }.onSuccess { etaTargets = it }
            if (subsRes.isSuccess && tgtRes.isSuccess) monitorsLoaded = true
        }
    }
    val reloadSubs: () -> Unit = { scope.launch { loadMonitors() } }
    val reloadTargets: () -> Unit = { scope.launch { loadMonitors() } }
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
                current = now?.entry_eta?.let { formatEntry(it) } ?: "—",
                kind = MonitorKind.ETA,
                id = t.id,
            )
        }
    }
    val removeRow: (MonitorRow) -> Unit = { row ->
        creds?.let { c ->
            scope.launch {
                runCatching {
                    when (row.kind) {
                        MonitorKind.THRESHOLD -> Api.unsubscribe(c, row.id)
                        MonitorKind.ETA -> Api.deleteEtaTarget(c, row.id)
                    }
                }
                loadMonitors()
            }
        }
    }

    // Одне тіло оновлення на два тригери — цикл і сигнал мережі, — щоб вони не
    // розійшлись у поведінці при майбутніх правках.
    val refresh: suspend () -> Unit = {
        val wlRes = runCatching { Api.workload() }
        workload = LiveRefresh.keepOnError(workload, wlRes)
        wlRes
            .onSuccess { refreshError = false }
            .onFailure { refreshError = true }
        // Моніторинг оновлюємо тим самим тілом, що й чергу. Інакше після
        // відновлення мережі черга оживала, а секція «Ваш моніторинг» лишалась
        // порожньою до випадкового перемикання вкладки (#107).
        loadMonitors()
        // Годинник свіжості рухається щополл, незалежно від payload.
        freshnessNow = Instant.now()
        loading = false
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
    LaunchedEffect(lifecycleOwner, selected) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            launch {
                NetworkAvailability.events(context).collect { refresh() }
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
                runCatching { Api.history(currentId, hours = 1) }
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

    val onMonitor = activeTab == "monitor"

    // Головна — фото на всю площу з `filter:grayscale(100%)` + затемнення згори
    // (190px) і знизу (170px). Екран «Моніторинг» — суцільний темний фон
    // (#0A0A0A), без фото й градієнтів.
    Box(Modifier.fillMaxSize().background(if (onMonitor) MonitorBg else Color.Black)) {
        if (!onMonitor) {
            Image(
                painter = painterResource(R.drawable.onboarding_truck),
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                colorFilter = GrayscaleFilter,
            )
            Box(
                Modifier.fillMaxWidth().height(190.dp).align(Alignment.TopCenter)
                    .background(TopScrim)
            )
            Box(
                Modifier.fillMaxWidth().height(170.dp).align(Alignment.BottomCenter)
                    .background(BottomScrim)
            )
        }

    if (onMonitor) {
        // Екран «Моніторинг»: 4 плитки на всю висоту. Header фіксований зверху,
        // три плитки-дії й «Ваш моніторинг» ділять решту простору вагами (список
        // отримує трохи більше й скролиться, якщо рядків багато).
        Column(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp)
                .padding(bottom = 84.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            HeaderRow(freshness = freshness, hasError = refreshError)
            ActionTile(
                title = "Пороги",
                subtitle = "Сповістити, коли черга сягне певної кількості авто",
                onClick = { showThresholdCpPicker = true },
                modifier = Modifier.fillMaxWidth().weight(1f),
                icon = { TileIcon(Icons.Filled.BarChart) },
            )
            ActionTile(
                title = "Час в'їзду",
                subtitle = "Сповістити, коли черга дійде до бажаного часу в'їзду",
                onClick = { showEtaCpPicker = true },
                modifier = Modifier.fillMaxWidth().weight(1f),
                icon = { TileIcon(Icons.Filled.HourglassEmpty) },
            )
            ActionTile(
                title = "AI-прогноз",
                subtitle = "Прогноз хвиль реєстрацій у чергу від AI-моделі",
                onClick = { showAiCpPicker = true },
                modifier = Modifier.fillMaxWidth().weight(1f),
                icon = { TileIcon(Icons.Filled.AutoAwesome) },
            )
            MonitoringTile(
                rows = monitorRows,
                onRemove = { pendingRemove = it },
                modifier = Modifier.fillMaxWidth().weight(1.5f),
                fill = true,
                loaded = monitorsLoaded,
            )
        }
    } else {
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 20.dp),
            // Нижній відступ, щоб останню плитку не ховала плавуча навпанель.
            contentPadding = PaddingValues(bottom = 84.dp),
        ) {
            item {
                HeaderRow(freshness = freshness, hasError = refreshError)
            }
            if (current != null) {
                item { HeroPanel(current) { showPicker = true } }
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
                        loaded = monitorsLoaded,
                    )
                }
            } else {
                // `tilesHidden` — коли показувати нема чого (keep-last: current
                // null означає, що валідних даних ще НЕ було).
                item { DataUnavailablePanel(Modifier.padding(top = 38.dp)) }
            }
        }
    }

    // Макет: плавуча навпанель — `left:12; right:12; bottom:12; height:60;
    // radius:20`, прибита до низу поверх вмісту (футер «DEVELOPER» на головній
    // прибрано — його місце зайняла панель).
    BottomNavBar(
        activeTab = activeTab,
        onSelect = { activeTab = it },
        modifier = Modifier
            .align(Alignment.BottomCenter)
            .windowInsetsPadding(WindowInsets.systemBars)
            .padding(horizontal = 12.dp)
            .padding(bottom = 12.dp),
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
                creds?.let { c ->
                    scope.launch {
                        runCatching { Api.subscribe(c, cp.checkpoint_id, threshold) }
                        reloadSubs()
                    }
                }
                pendingThresholdCp = null
            },
            onDismiss = { pendingThresholdCp = null },
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
                creds?.let { c ->
                    scope.launch {
                        runCatching { Api.createEtaTarget(c, cp.checkpoint_id, targetAtIso) }
                        reloadTargets()
                    }
                }
                pendingEtaCp = null
            },
            onDismiss = { pendingEtaCp = null },
        )
    }

    // AI, крок 1 — пікер КПП.
    if (showAiCpPicker) {
        CheckpointPickerSheet(
            workload = workload,
            selectedId = -1,
            countryFilter = countryFilter,
            onFilter = { countryFilter = it },
            onPick = { id ->
                pendingAiCp = workload.firstOrNull { it.checkpoint_id == id }
                showAiCpPicker = false
            },
            onDismiss = { showAiCpPicker = false },
        )
    }

    // Крок 2 — показ прогнозу для обраного КПП.
    pendingAiCp?.let { cp ->
        ForecastDialog(
            checkpointTitle = monitorLabel(cp.flag_emoji, cp.title),
            checkpointId = cp.checkpoint_id,
            onDismiss = { pendingAiCp = null },
        )
    }

}

/**
 * Шапка за макетом: wordmark ліворуч, стан сервера праворуч (крапка + підпис
 * у рамці). Стан виводимо з реальних сигналів, а не з фейкового перемикача
 * макета: помилка оновлення → «НЕМАЄ ЗВʼЯЗКУ», протухлі дані → «ДАНІ
 * ЗАСТАРІЛІ», інакше «СЕРВЕР ОНЛАЙН».
 *
 * Індикатор НЕ клікабельний. У макеті `cycleServer` існує лише щоб гортати
 * три стани у прев'ю Design — у застосунку стан приходить із даних, і тиснути
 * тут нема на що.
 */
@Composable
private fun HeaderRow(
    freshness: LiveRefresh.Freshness?,
    hasError: Boolean,
) {
    val avelren = MaterialTheme.avelren
    // Стан сервера виводимо з реальних сигналів, а не з перемикача-заглушки
    // макета: помилка оновлення → червоний, протухлі дані → жовтий, інакше
    // зелений. Макет: `border:2px solid rgba(255,255,255,.5); border-radius:8px;
    // padding:5px 10px; font:700 10px; letter-spacing:1px` (→ 0.1em),
    // крапка 8×8.
    // Рядки й кольори крапки — точно з SERVER_STATES макета.
    val (dot, label) = when {
        hasError -> Color(0xFFD5382C) to "НЕМАЄ ІНТЕРНЕТУ"
        freshness?.stale == true -> Color(0xFFC9A100) to "СЕРВЕР ПЕРЕЗАПУСКАЄТЬСЯ"
        else -> Color(0xFF0E7A4E) to "СЕРВЕР ОНЛАЙН"
    }
    Row(
        modifier = Modifier.fillMaxWidth().padding(top = 26.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            "AVELREN",
            style = MaterialTheme.typography.headlineMedium,
            color = Color.White,
        )
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .border(2.dp, Color(0x80FFFFFF), RoundedCornerShape(8.dp))
                .padding(horizontal = 10.dp, vertical = 5.dp),
        ) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(dot))
            Spacer(Modifier.width(7.dp))
            Text(
                label,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 0.1.em,
                color = Color.White,
            )
        }
    }
}


// Колір тексту/іконки порожнього стану — rgba(255,255,255,.6) з макета.
private val EmptyInk = Color(0x99FFFFFF)

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
    Canvas(modifier.size(40.dp)) {
        val s = size.minDimension / 24f       // viewBox макета — 0 0 24 24
        val sw = 1.8f * s
        // Три «хвилі» Wi-Fi (cubic-криві з SVG-шляху), зверху вниз.
        val waves = Path().apply {
            moveTo(1f * s, 9f * s); cubicTo(7f * s, 4f * s, 17f * s, 4f * s, 23f * s, 9f * s)
            moveTo(4.5f * s, 12.5f * s); cubicTo(8.5f * s, 9.5f * s, 15.5f * s, 9.5f * s, 19.5f * s, 12.5f * s)
            moveTo(8f * s, 16f * s); cubicTo(10f * s, 14.5f * s, 14f * s, 14.5f * s, 16f * s, 16f * s)
        }
        drawPath(waves, HeroYellow, style = Stroke(width = sw, cap = StrokeCap.Round))
        // Крапка під хвилями та діагональна риска «перекреслено».
        drawCircle(HeroYellow, radius = sw * 0.6f, center = Offset(12f * s, 19.5f * s))
        drawLine(HeroYellow, Offset(2f * s, 2f * s), Offset(22f * s, 22f * s), sw, cap = StrokeCap.Round)
    }
}

// --- Плитка «Ваш моніторинг» ----------------------------------------------
// Список того, що користувач моніторить: пороги + час в'їзду. Кожен запис —
// бейдж (поріг «100» / час «06:00»), назва КПП, і ПОТОЧНЕ значення праворуч
// (скільки авто в черзі зараз / поточний час в'їзду) з живих даних, ✕ прибрати.
enum class MonitorKind { THRESHOLD, ETA }

/**
 * @param badge   значення підписки (поріг або час в'їзду).
 * @param label   назва КПП (прапор + до дужки).
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

private val WatchRowBorder = Color(0x24FFFFFF)  // rgba(255,255,255,.14)

@Composable
private fun MonitoringTile(
    rows: List<MonitorRow>,
    onRemove: (MonitorRow) -> Unit,
    modifier: Modifier = Modifier,
    fill: Boolean = false,   // true — заповнити висоту плитки (екран «Моніторинг»)
    loaded: Boolean = true,  // false — список ще не приїхав; НЕ показувати empty-state
) {
    Column(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(HeroGlass)
            .border(1.dp, HeroBorder, RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "Ваш моніторинг",
            color = HeroYellow,
            fontWeight = FontWeight.Black,
            style = MaterialTheme.typography.bodyMedium,
            fontSize = 12.sp,
            letterSpacing = 0.025.em,
        )
        if (rows.isEmpty()) {
            // fill — центр по всій висоті плитки; інакше — природна висота.
            Box(
                if (fill) Modifier.weight(1f).fillMaxWidth() else Modifier.fillMaxWidth(),
                contentAlignment = Alignment.Center,
            ) {
                // Поки список не приїхав — стан очікування, а не твердження
                // «нічого не відстежується». Стверджувати можна лише після
                // успішної відповіді сервера (#107).
                if (!loaded) {
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
                rows.forEach { row -> MonitorRowView(row) { onRemove(row) } }
            }
        }
    }
}

/**
 * Рядок моніторингу: бейдж у жовтій рамці, назва КПП, поточний стан праворуч
 * («зараз N» авто для порога / поточний час в'їзду для eta), ✕ прибрати.
 */
@Composable
private fun MonitorRowView(row: MonitorRow, onRemove: () -> Unit) {
    val view = LocalView.current
    Row(
        Modifier
            .fillMaxWidth()
            .border(1.dp, WatchRowBorder, RoundedCornerShape(12.dp))
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(
            row.badge,
            color = HeroYellow,
            fontWeight = FontWeight.Black,
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodyMedium.copy(
                fontFeatureSettings = TabularNumberFeature,
            ),
            modifier = Modifier
                .widthIn(min = 44.dp)
                .border(1.5.dp, HeroYellow, RoundedCornerShape(8.dp))
                .padding(horizontal = 8.dp, vertical = 4.dp),
        )
        Text(
            row.label,
            color = Color.White,
            style = MaterialTheme.typography.bodySmall,
            fontSize = 12.5.sp,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        // Поточний стан цього КПП зараз (жива черга / час в'їзду). Мітка
        // залежить від типу рядка: під «зараз» стояли то авто, то дата, і
        // прочитати 06:00-бейдж поряд із датою було неможливо.
        Column(horizontalAlignment = Alignment.End) {
            Text(
                when (row.kind) {
                    MonitorKind.THRESHOLD -> "зараз, авто"
                    MonitorKind.ETA -> "в'їзд"
                },
                color = EmptyInk,
                fontWeight = FontWeight.Bold,
                fontSize = 8.sp,
                style = MaterialTheme.typography.bodySmall,
            )
            Text(
                row.current,
                color = Color.White,
                fontWeight = FontWeight.Bold,
                fontSize = 12.5.sp,
                style = MaterialTheme.typography.bodySmall.copy(
                    fontFeatureSettings = TabularNumberFeature,
                ),
            )
        }
        Text(
            "✕",
            color = Color(0x80FFFFFF),
            fontSize = 15.sp,
            modifier = Modifier
                .tapNoRipple {
                    view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                    onRemove()
                }
                .padding(2.dp),
        )
    }
}

// --- Екран «Моніторинг»: плитки-дії та додавання порога -------------------
/** Короткий підпис КПП для рядків моніторингу: прапор + назва до дужки. */
private fun monitorLabel(flag: String?, title: String): String =
    "${flag ?: ""} ${title.substringBefore(" (")}".trim()

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
    val view = LocalView.current
    Row(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(HeroGlass)
            .border(1.dp, HeroBorder, RoundedCornerShape(16.dp))
            .tapNoRipple {
                view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
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
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 12.sp,
                letterSpacing = 0.025.em,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                subtitle,
                color = EmptyInk,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 12.sp,
                lineHeight = 16.sp,
            )
        }
        Spacer(Modifier.width(12.dp))
        // «+» намальований штрихами (не гліф шрифту): рівні плечі, круглі кінці,
        // ідеально по центру — чистіший вигляд.
        Canvas(Modifier.size(22.dp)) {
            val c = size.width / 2f
            val arm = size.width * 0.32f
            val sw = 2.2.dp.toPx()
            drawLine(HeroYellow, Offset(c - arm, c), Offset(c + arm, c), sw, cap = StrokeCap.Round)
            drawLine(HeroYellow, Offset(c, c - arm), Offset(c, c + arm), sw, cap = StrokeCap.Round)
        }
    }
}

/** Справжня Material-іконка для плитки-дії — жовта, 26dp. */
@Composable
private fun TileIcon(icon: androidx.compose.ui.graphics.vector.ImageVector) {
    Icon(icon, contentDescription = null, tint = HeroYellow, modifier = Modifier.size(26.dp))
}

/** Крок 2 додавання порога: діалог із чипами 50/100/150/200 для обраного КПП. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThresholdChooserDialog(
    checkpointTitle: String,
    onPick: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    val view = LocalView.current
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
                color = Color.White,
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
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        onPick(v)
                    }
                }
            }
        }
    }
}

// --- Час в'їзду: бейдж, підписи днів та діалог вибору ----------------------
private val ETA_HH_MM: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm")
private val ETA_DAY_FMT: DateTimeFormatter =
    DateTimeFormatter.ofPattern("EE dd.MM", java.util.Locale("uk"))

/** Бейдж eta-рядка — час цілі «HH:mm» у київському поясі. */
private fun etaBadge(iso: String): String = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(ETA_HH_MM)
}.getOrDefault("—")

/** Підпис дня для чипів: СЬОГОДНІ / ЗАВТРА / «ПТ 22.08». */
private fun etaDayLabel(today: java.time.LocalDate, off: Int): String = when (off) {
    0 -> "СЬОГОДНІ"
    1 -> "ЗАВТРА"
    else -> today.plusDays(off.toLong()).format(ETA_DAY_FMT).uppercase()
}

/** ISO-8601 з offset для createEtaTarget з обраних дня й часу (київський пояс). */
private fun etaIso(today: java.time.LocalDate, off: Int, hour: String): String {
    val parts = hour.split(":")
    return today.plusDays(off.toLong())
        .atTime(parts[0].toInt(), parts[1].toInt())
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
    val view = LocalView.current
    val today = remember { java.time.LocalDate.now(KYIV) }
    // Усі 24 години (00:00–23:00), а не крок 3 год.
    val hours = remember { (0..23).map { "%02d:00".format(it) } }
    var dayOff by remember { mutableStateOf(1) }        // за замовч. ЗАВТРА
    var hour by remember { mutableStateOf("06:00") }
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
                color = Color.White,
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
                    PickerFilterChip(etaDayLabel(today, off), active = dayOff == off) {
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        dayOff = off
                    }
                }
            }
            Spacer(Modifier.height(14.dp))
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                hours.forEach { h ->
                    PickerFilterChip(h, active = hour == h) {
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        hour = h
                    }
                }
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
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        onPick(etaIso(today, dayOff, hour))
                    }
                    .padding(vertical = 13.dp),
            )
        }
    }
}

// --- AI-прогноз -----------------------------------------------------------
private val AI_DATE: DateTimeFormatter = DateTimeFormatter.ofPattern("d MMMM", java.util.Locale("uk"))
private fun aiReadyDate(iso: String): String = runCatching {
    OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(AI_DATE)
}.getOrDefault(iso)

/**
 * Прогноз хвиль реєстрацій для обраного КПП. Читає `forecast()`:
 * collecting — модель ще вчиться (показуємо прогрес і дату готовності);
 * ready/preliminary — очікуваний пік черги з прогнозних точок.
 */
@Composable
private fun ForecastDialog(
    checkpointTitle: String,
    checkpointId: Int,
    onDismiss: () -> Unit,
) {
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
    var loading by remember { mutableStateOf(true) }
    var failed by remember { mutableStateOf(false) }
    LaunchedEffect(checkpointId) {
        loading = true; failed = false
        runCatching { Api.forecast(checkpointId) }
            .onSuccess { forecast = it; loading = false }
            .onFailure { failed = true; loading = false }
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
                "AI-прогноз",
                color = HeroYellow,
                fontWeight = FontWeight.Black,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 14.sp,
            )
            Spacer(Modifier.height(4.dp))
            Text(
                checkpointTitle,
                color = Color.White,
                style = MaterialTheme.typography.bodySmall,
                fontSize = 13.sp,
            )
            Spacer(Modifier.height(16.dp))
            val f = forecast
            when {
                loading -> ForecastLine("Завантаження…")
                failed || f == null -> ForecastLine("Не вдалося отримати прогноз")
                f.status == "ready" || f.status == "preliminary" -> {
                    val peak = f.points.maxByOrNull { it.vehicles_expected }
                    if (peak != null) {
                        ForecastLine("Очікуваний пік черги:")
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "≈ ${peak.vehicles_expected} авто о ${etaBadge(peak.time)}",
                            color = Color.White,
                            fontWeight = FontWeight.Black,
                            fontSize = 18.sp,
                        )
                        if (f.status == "preliminary") {
                            Spacer(Modifier.height(8.dp))
                            ForecastLine("Прогноз попередній — модель ще вчиться")
                        }
                    } else {
                        ForecastLine("Прогноз ще формується")
                    }
                }
                else -> {
                    // collecting
                    Text(
                        "Модель ще вчиться на зібраних даних",
                        color = Color.White,
                        style = MaterialTheme.typography.bodySmall,
                        fontSize = 13.sp,
                    )
                    Spacer(Modifier.height(8.dp))
                    ForecastLine("Зібрано ${"%.1f".format(f.weeks_collected)} з ${f.weeks_needed} тижнів")
                    f.ready_at?.let {
                        Spacer(Modifier.height(4.dp))
                        Text(
                            "Готово орієнтовно ${aiReadyDate(it)}",
                            color = HeroYellow,
                            fontWeight = FontWeight.Bold,
                            style = MaterialTheme.typography.bodySmall,
                            fontSize = 12.sp,
                        )
                    }
                }
            }
            Spacer(Modifier.height(18.dp))
            val view = LocalView.current
            Text(
                "Закрити",
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
                        view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                        onDismiss()
                    }
                    .padding(vertical = 13.dp),
            )
        }
    }
}

/** Рядок пояснення в AI-діалозі (приглушений). */
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
    val view = LocalView.current
    val desc = when (row.kind) {
        MonitorKind.THRESHOLD -> "Поріг ${row.badge} авто · ${row.label}"
        MonitorKind.ETA -> "Час в'їзду ${row.badge} · ${row.label}"
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
                desc,
                color = Color.White,
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
                            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
                            onConfirm()
                        }
                        .padding(vertical = 12.dp),
                )
            }
        }
    }
}

// --- Нижня навігація (з Design) -------------------------------------------
// Плавуча закруглена панель поверх вмісту: `bottom:12; height:60; radius:20;
// bg rgba(10,10,10,.72); border rgba(255,255,255,.14); shadow`. Дві вкладки —
// Головна / Моніторинг; активна жовта (#F5C400), неактивна rgba(255,255,255,.45).
private val MonitorBg = Color(0xFF0A0A0A)    // суцільний фон екрана «Моніторинг»
private val NavGlass = Color(0xB80A0A0A)     // rgba(10,10,10,.72)
private val NavBorder = Color(0x24FFFFFF)    // rgba(255,255,255,.14)
private val NavInactive = Color(0x73FFFFFF)  // rgba(255,255,255,.45)

@Composable
private fun BottomNavBar(
    activeTab: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier
            .fillMaxWidth()
            .height(60.dp)
            .shadow(8.dp, RoundedCornerShape(20.dp))
            .background(NavGlass, RoundedCornerShape(20.dp))
            .border(1.dp, NavBorder, RoundedCornerShape(20.dp)),
    ) {
        NavTab("Головна", activeTab == "home", { onSelect("home") }, Modifier.weight(1f)) { HomeIcon(it) }
        NavTab("Моніторинг", activeTab == "monitor", { onSelect("monitor") }, Modifier.weight(1f)) { MonitorIcon(it) }
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
    val view = LocalView.current
    Column(
        modifier.fillMaxHeight().tapNoRipple {
            view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
            onClick()
        },
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
            style = MaterialTheme.typography.labelSmall,
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

// Жовтий контент-колір hero — #F5C400 (той самий --warn, але тут це колір
// ТЕКСТУ на темному склі, не заливка).
private val HeroYellow = Color(0xFFF5C400)
// Макет: `background:rgba(10,10,10,.42)` РАЗОМ із `backdrop-filter:blur(18px)`.
// Compose не вміє розмивати фон під елементом, тож буквальні 42% на світлому
// небі у верхній частині фото лишають панель напівпрозорою й нечитабельною.
// Піднято до ~72%, щоб дати ту саму візуальну вагу, що дає blur у браузері.
private val HeroGlass = Color(0xB80A0A0A)
private val HeroBorder = Color(0x38FFFFFF)   // rgba(255,255,255,.22)
private val HeroLine = Color(0x59FFFFFF)      // rgba(255,255,255,.35)

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
            .background(HeroGlass)
            .border(1.dp, HeroBorder, RoundedCornerShape(16.dp))
            .tapNoRipple(onClick = onOpenPicker)
            .padding(16.dp),
    ) {
        // Макет: `font:700 13px`, назва — ВЕЛИКИМИ (`title.toUpperCase()`).
        // Без «ЗМІНИТИ»: уся плитка клікабельна (`onOpenPicker`), тож окрема
        // підказка зайва. Іконка паузи — після назви, коли пункт призупинено.
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "${item.flag_emoji ?: ""} ${item.title}".trim().uppercase(),
                color = HeroYellow,
                style = MaterialTheme.typography.bodyMedium,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f, fill = false),
            )
            if (item.is_paused) {
                Spacer(Modifier.width(8.dp))
                PauseBadge(size = 20.dp)
            }
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
        // Макет: `≈ {wait} очікування` — рядок часу очікування, коли він є.
        formatWait(item.wait_time_seconds)?.let { wait ->
            Text(
                "≈ $wait очікування",
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
        if (item.entry_eta != null) {
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
                formatHeroEta(item.entry_eta),
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
private val PickerSheetBg = Color(0xFF0A0A0A)   // тло аркуша
private val PickerRowBg = Color(0xFF1A1B1D)     // необрана картка
private val PickerInk = Color(0xFF1C1E20)       // текст/рамка на жовтому
private val PickerSubOnYellow = Color(0xB31C1E20) // підпис на обраній картці (.7)
private val PickerYellowHalf = Color(0x80F5C400)  // рамка неактивної пігулки (.5)
// Назви КПП і країн — білі, а не жовті: у списку з ~40 рядків жовтий текст на
// темному читається гірше за білий, а сам жовтий лишається носієм сигналу
// (табличка з чергою, обрана картка, активна пігулка) — там, де він щось
// означає, а не просто фарбує назву.
private val PickerNameInk = Color(0xFFFFFFFF)

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
        properties = DialogProperties(usePlatformDefaultWidth = false),
    ) {
        Column(
            Modifier
                .fillMaxSize()
                .background(PickerSheetBg)
                .windowInsetsPadding(WindowInsets.systemBars)
                .padding(horizontal = 14.dp, vertical = 16.dp),
        ) {
            Row(
                Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
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
            Spacer(Modifier.height(12.dp))

            LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
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
                item { Spacer(Modifier.height(14.dp)) }
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
    // Дата в'їзду парситься раз на КПП (ключ — entry_eta), а не на кожен кадр
    // скролу: OffsetDateTime.parse + форматер помітно дорожчі за решту рядка.
    val entrySub = remember(item.entry_eta) {
        item.entry_eta?.let { "в'їзд ${formatEntry(it)}" }
    }
    // Тактильний «тік» на вибір КПП — як на навпанелі; поважає системне вібро.
    val view = LocalView.current
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoadSignShape.Card)
            .background(bg)
            .border(2.dp, borderColor, RoadSignShape.Card)
            .tapNoRipple {
                view.performHapticFeedback(HapticFeedbackConstants.VIRTUAL_KEY)
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
private val ChartAxis = Color(0x99FFFFFF)     // осі/підписи — світлі напівпрозорі
private val ChartGrid = Color(0x80FFFFFF)     // пунктирна сітка (біла 50%)
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
    val axisStyle = MaterialTheme.typography.bodySmall.copy(
        fontSize = 8.sp, fontWeight = FontWeight.Bold, color = ChartAxis,
    )
    Column(
        modifier
            .clip(RoundedCornerShape(16.dp))
            .background(HeroGlass)
            .border(1.dp, HeroBorder, RoundedCornerShape(16.dp))
            .padding(horizontal = 16.dp, vertical = 14.dp),
    ) {
        Text(
            "Динаміка реєстрацій",
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
                    drawLine(ChartGrid, Offset(0f, gy), Offset(w, gy), 1f, pathEffect = dash)
                }

                // Колір кожного відрізка — за темпом реєстрацій (приростом
                // черги за хвилину), а НЕ за позицією в часі: черга не росте →
                // зелений; поодинокі реєстрації → жовтий; масовий наплив →
                // червоний. Заливка під відрізком — того ж кольору, згасає вниз.
                // Лінія ПРЯМА: точки з'єднані навскіс (не сходинками) — так менше
                // «сходів», особливо на вищому полотні.
                val strokeW = 2.5.dp.toPx()
                for (i in 1 until n) {
                    val c = colorForRate(data[i] - data[i - 1])
                    val x0 = x(i - 1); val x1 = x(i)
                    val yPrev = y(data[i - 1]); val yCur = y(data[i])
                    // Заливка — трапеція під діагональним відрізком до низу.
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
                    // Сам відрізок — прямою від точки до точки.
                    drawLine(c, Offset(x0, yPrev), Offset(x1, yCur), strokeW, cap = StrokeCap.Round)
                }

                // Крапка «Зараз» — кольором ПОТОЧНОГО темпу реєстрацій.
                val cx = x(n - 1)
                val cy = y(data[n - 1])
                val nowColor = colorForRate(data[n - 1] - data[n - 2])
                drawCircle(nowColor, radius = 4.5.dp.toPx(), center = Offset(cx, cy))
                drawCircle(Color.White, radius = 4.5.dp.toPx(), center = Offset(cx, cy), style = Stroke(2.dp.toPx()))
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

// Позначка паузи (з Design): кругла ЖОВТА (#F5C400) іконка з символом «пауза» —
// дві вертикальні білі смужки. Показується біля назви пункту, коли рух через
// КПП тимчасово зупинено (єЧерга: «Черга затримується» — закриття МАПП через
// негоду/технічні причини/дії сусідньої країни; місце в черзі зберігається,
// але заїзд наразі не відбувається).
private val PauseYellow = Color(0xFFF5C400)

@Composable
private fun PauseBadge(size: Dp = 20.dp) {
    Box(
        Modifier.size(size).clip(CircleShape).background(PauseYellow),
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
