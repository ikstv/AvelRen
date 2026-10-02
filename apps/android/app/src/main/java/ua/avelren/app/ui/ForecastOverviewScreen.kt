package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import java.time.Instant
import androidx.activity.compose.BackHandler
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import ua.avelren.app.data.*
import ua.avelren.app.notify.*
import ua.avelren.app.data.ForecastSelection
import ua.avelren.app.ui.theme.*

/** Серверні підписки та підтвердження реальних подій у погодженому інтерфейсі. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ForecastOverviewScreen(
    repository: SurgeMonitorClient, onBack: () -> Unit,
    notificationsAllowed: Boolean, onOpenNotificationSettings: () -> Unit,
    onCountForecast: (Int) -> Unit,
) {
    val context = LocalContext.current
    val local = remember { SurgeLocalStore(context) }
    val scope = rememberCoroutineScope()
    val mutex = remember { Mutex() }
    var checkpoints by remember { mutableStateOf<List<SurgeCheckpoint>>(emptyList()) }
    var subscriptions by remember { mutableStateOf<List<SurgeSubscription>>(emptyList()) }
    var snapshots by remember { mutableStateOf<Map<Int, SurgeStatus>>(emptyMap()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    var voiceProblem by remember { mutableStateOf(local.voiceProblem()) }
    var now by remember { mutableStateOf(Instant.now()) }
    suspend fun refresh() = mutex.withLock {
        try {
            val cps = repository.checkpoints()
            val subs = repository.subscriptions()
            val states = mutableMapOf<Int, SurgeStatus>()
            for (sub in subs) {
                try { states[sub.checkpoint_id] = repository.snapshot(sub.checkpoint_id) }
                catch (e: CancellationException) { throw e }
                catch (_: Exception) { }
            }
            checkpoints = cps
            subscriptions = subs
            snapshots = states
            now = Instant.now()
            error = null
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { error = "Не вдалося оновити моніторинг. Перевірте інтернет або спробуйте пізніше" }
        finally { loading = false; voiceProblem = local.voiceProblem() }
    }
    fun change(cp: SurgeCheckpoint, forecast: Boolean, fact: Boolean, remove: Boolean = false) {
        if (busy) return
        if (!remove && subscriptions.none { it.checkpoint_id == cp.checkpoint_id } && subscriptions.size >= ForecastSelection.MAX) return
        busy = true
        scope.launch {
            try {
                if (remove) repository.removeSubscription(cp.checkpoint_id)
                else {
                    repository.setSubscription(cp.checkpoint_id, forecast, fact)
                    if ((forecast || fact) && local.enableVoiceForFirstMonitoring()) {
                        voiceProblem = local.voiceProblem()
                    }
                }
                refresh()
            } catch (e: CancellationException) { throw e }
            catch (_: Exception) { error = "Не вдалося зберегти вибір КПП. Попередні налаштування залишились" }
            finally { busy = false }
        }
    }
    fun acknowledge(alert: SurgeAlert) {
        val actions = SurgeMonitorActions(local) { id, kind ->
            Notifications.cancel(context, kind, id)
            SurgeVoiceService.stopAlert(context, id)
            scope.launch { runCatching { SurgeAckWorker.enqueue(context, id) } }
        }
        if (actions.acknowledge(alert.surge_alert_id, alert.kind)) {
            subscriptions = subscriptions.map { current ->
                current.copy(alerts = current.alerts.filterNot {
                    it.surge_alert_id == alert.surge_alert_id
                })
            }
        } else error = "Не вдалося зберегти підтвердження. Спробуйте ще раз"
    }
    LaunchedEffect(repository) {
        while (true) { refresh(); delay(60_000) }
    }
    val ids = subscriptions.map { it.checkpoint_id }
    var picker by remember { mutableStateOf(false) }
    var pendingRemove by remember { mutableStateOf<Int?>(null) }
    var countryFilter by remember { mutableStateOf<String?>(null) }
    fun select(id: Int, enabled: Boolean) {
        checkpoints.firstOrNull { it.checkpoint_id == id }?.let { cp ->
            change(cp, cp.forecast_supported, cp.fact_supported, remove = !enabled)
        }
    }
    BackHandler { if (picker) picker = false else onBack() }
    Column(Modifier.fillMaxSize().background(AppBackground).windowInsetsPadding(WindowInsets.systemBars)) {
        Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 20.dp, top = 18.dp),
            verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Назад до Моніторингу", tint = AppAccent) }
            Text("Прогноз черги", color = AppInk, style = MaterialTheme.typography.headlineMedium)
        }
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    Text("Оберіть КПП — про зміни повідомить телефон", color = AppAccent,
                        style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Text("Відстежуйте до 5 КПП. Телефон голосом попередить про можливий початок масової реєстрації протягом наступних 24 годин та окремо — про початок зростання черги.",
                        color = AppInk, style = MaterialTheme.typography.bodyMedium)
                }
            }
            item { Text("Вибрано ${ids.size} із 5", color = AppAccent, fontWeight = FontWeight.Bold) }
            item {
                if (ids.size < ForecastSelection.MAX) {
                    OutlinedButton(enabled = !busy && !loading && error == null, onClick = { picker = true }, modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(16.dp), border = BorderStroke(1.5.dp, AppAccent.copy(alpha = 0.5f)),
                        contentPadding = PaddingValues(16.dp)) { Text("Додати КПП", fontWeight = FontWeight.Bold) }
                } else { Text("Щоб додати інший КПП, приберіть один із вибраних", color = AppInk,
                    style = MaterialTheme.typography.bodySmall) }
            }
            if (loading) item { CircularProgressIndicator(color = AppAccent) }
            if (!notificationsAllowed && ids.isNotEmpty()) item {
                Text("Дозвольте сповіщення, щоб телефон міг попереджати", color = MaterialTheme.colorScheme.error)
                TextButton(onClick = onOpenNotificationSettings) { Text("Дозволити повідомлення") }
            }
            if (voiceProblem != null && ids.isNotEmpty()) item {
                Text(SurgePresentation.voiceHint(true, notificationsAllowed, voiceProblem), color = MaterialTheme.colorScheme.error)
            }
            error?.let { message -> item {
                Text(message, color = MaterialTheme.colorScheme.error)
                TextButton(enabled = !busy, onClick = { scope.launch { refresh() } }) { Text("Оновити") }
            } }
            if (!loading && error == null && ids.isEmpty()) item { Text("Ще немає вибраних КПП. Натисніть «Додати КПП», щоб почати.",
                color = MaterialTheme.colorScheme.onSurfaceVariant) }
            items(ids, key = { it }) { id ->
                val cp = checkpoints.firstOrNull { it.checkpoint_id == id }
                Surface(modifier = Modifier.fillMaxWidth(), color = AppBackground,
                    shape = RoundedCornerShape(16.dp), border = BorderStroke(1.5.dp, AppAccent.copy(alpha = 0.5f))) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(cp?.let { "${it.flag_emoji.orEmpty()} ${it.title}" } ?: "КПП №$id",
                            Modifier.fillMaxWidth(), color = AppAccent, fontWeight = FontWeight.Bold)
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text(if (error == null) "Відстежується" else "Немає зв’язку", Modifier.weight(1f), color = AppInk, fontWeight = FontWeight.Bold)
                            TextButton(enabled = !busy, onClick = { pendingRemove = id }) { Text("Прибрати") }
                        }
                        cp?.let {
                            SurgePresentation.availabilityHint(it, if (error == null) snapshots[id] else null)?.let { message ->
                                Text(message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                        if (cp != null && !cp.forecast_supported) {
                            Text("Доступне сповіщення про початок зростання. Прогноз для цього КПП ще недоступний.",
                                color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
                        }
                        subscriptions.firstOrNull { it.checkpoint_id == id }?.alerts.orEmpty()
                            .filter { !local.isBlocked(it.surge_alert_id) &&
                                runCatching { Instant.parse(it.expires_at) > now }.getOrDefault(false) }
                            .forEach { alert ->
                                HorizontalDivider(color = AppAccent.copy(alpha = 0.3f))
                                Text(if (alert.kind == "surge_forecast") "Прогноз" else "Фактичне зростання",
                                    color = AppAccent, fontWeight = FontWeight.Bold)
                                Text(alert.body, color = AppInk)
                                if (alert.kind == "surge_forecast" && cp != null) {
                                    SurgePresentation.cards(cp, snapshots[id], now).window?.let { window ->
                                        Text("Можливе вікно: $window", color = AppInk, style = MaterialTheme.typography.bodySmall)
                                    }
                                }
                                if (alert.kind == "surge_started") alert.growth_5m?.let { growth ->
                                    Text("+$growth авто за 5 хвилин", color = AppInk, style = MaterialTheme.typography.bodySmall)
                                }
                                TextButton(onClick = { acknowledge(alert) }) { Text("Зрозуміло") }
                            }
                        TextButton(onClick = { onCountForecast(id) }) { Text("Черга на добу →") }
                    }
                }
            }

        }
        Text("Функція в розробці", Modifier.fillMaxWidth().padding(20.dp),
            color = AppAccent, fontWeight = FontWeight.Bold, fontSize = 12.sp)
    }
    if (picker) Dialog(onDismissRequest = { picker = false },
        properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.systemBars), color = AppBackground) {
            Column(Modifier.padding(20.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Виберіть КПП", Modifier.weight(1f), color = AppInk,
                        style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                    TextButton(onClick = { picker = false }) { Text("Готово") }
                }
                Text("Вибрано ${ids.size} із 5", color = AppAccent, fontWeight = FontWeight.Bold)
                if (ids.size >= ForecastSelection.MAX) Text("Щоб додати інший КПП, приберіть один із вибраних",
                    Modifier.padding(top = 8.dp), color = AppInk, style = MaterialTheme.typography.bodySmall)
                if (checkpoints.isEmpty()) Text("Список КПП ще не завантажено. Поверніться до Моніторингу та перевірте інтернет.",
                    Modifier.padding(top = 20.dp), color = AppInk)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
                val chipColors = FilterChipDefaults.filterChipColors(
                    containerColor = AppBackground, labelColor = AppInk,
                    selectedContainerColor = AppAccent, selectedLabelColor = AppOnAccent,
                )
                val chipBorder = BorderStroke(1.5.dp, AppAccent.copy(alpha = 0.5f))
                FlowRow(Modifier.fillMaxWidth().padding(top = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilterChip(selected = countryFilter == null, onClick = { countryFilter = null }, label = { Text("Всі") },
                        colors = chipColors, border = chipBorder, shape = RoundedCornerShape(20.dp))
                    checkpoints.mapNotNull { it.flag_emoji }.distinct().sorted().forEach { flag ->
                        FilterChip(selected = countryFilter == flag, onClick = { countryFilter = flag },
                            label = { Text(countryLabel(flag)) }, colors = chipColors, border = chipBorder, shape = RoundedCornerShape(20.dp))
                    }
                }
                val visible = if (countryFilter == null) checkpoints else checkpoints.filter { it.flag_emoji == countryFilter }
                LazyColumn(Modifier.padding(top = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(visible, key = { it.checkpoint_id }) { cp ->
                        val checked = cp.checkpoint_id in ids
                        val enabled = !busy && (checked || ids.size < ForecastSelection.MAX)
                        Row(Modifier.fillMaxWidth().border(1.5.dp, AppAccent.copy(alpha = if (enabled) 0.5f else 0.2f), RoundedCornerShape(16.dp))
                            .toggleable(value = checked, enabled = enabled, role = Role.Checkbox) {
                                if (checked) pendingRemove = cp.checkpoint_id else select(cp.checkpoint_id, true)
                            }.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
                                Surface(Modifier.size(24.dp), shape = CircleShape,
                                    color = if (checked) AppAccent else AppBackground,
                                    border = BorderStroke(2.dp, AppAccent.copy(alpha = if (enabled) 0.7f else 0.25f))) {
                                    if (checked) Box(contentAlignment = Alignment.Center) {
                                        Icon(Icons.Filled.Check, contentDescription = null,
                                            modifier = Modifier.size(18.dp), tint = AppOnAccent)
                                    }
                                }
                            }
                            Text("${cp.flag_emoji.orEmpty()} ${cp.title}", color = AppInk.copy(alpha = if (enabled) 1f else 0.45f))
                        }
                    }
                }
            }
        }
    }
    pendingRemove?.let { id ->
        val cp = checkpoints.firstOrNull { it.checkpoint_id == id }
        ConfirmRemoveDialog(
            description = cp?.let { "Прогноз черги · ${it.flag_emoji.orEmpty()} ${it.title}" } ?: "Прогноз черги · КПП №$id",
            onConfirm = { select(id, false); pendingRemove = null },
            onDismiss = { pendingRemove = null },
        )
    }

}
