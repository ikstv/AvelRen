package ua.avelren.app.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.Instant
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import ua.avelren.app.data.*
import ua.avelren.app.notify.*

@Composable
fun SurgeMonitorScreen(
    repository: SurgeMonitorClient,
    onBack: () -> Unit,
    notificationsAllowed: Boolean = false,
    onOpenNotificationSettings: () -> Unit = {},
    onCountForecast: (Int) -> Unit = {},
) {
    MaterialTheme(colorScheme = MaterialTheme.colorScheme.copy(
        primary = Color(0xFFF5C400), onPrimary = Color.Black,
        background = Color.Black, onBackground = Color.White,
        surface = Color(0xFF141414), onSurface = Color.White,
        surfaceVariant = Color(0xFF202020), onSurfaceVariant = Color(0xFFD0D0D0),
        surfaceContainerHighest = Color(0xFF202020),
    )) {
        SurgeMonitorContent(repository, onBack, notificationsAllowed, onOpenNotificationSettings, onCountForecast)
    }
}

@Composable
private fun SurgeMonitorContent(
    repository: SurgeMonitorClient,
    onBack: () -> Unit,
    notificationsAllowed: Boolean = false,
    onOpenNotificationSettings: () -> Unit = {},
    onCountForecast: (Int) -> Unit = {},
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
    var voice by remember { mutableStateOf(local.voiceEnabled()) }
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
        busy = true
        scope.launch {
            try {
                if (remove) repository.removeSubscription(cp.checkpoint_id)
                else {
                    repository.setSubscription(cp.checkpoint_id, forecast, fact)
                    if ((forecast || fact) && local.enableVoiceForFirstMonitoring()) {
                        voice = local.voiceEnabled()
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
    BackHandler(onBack = onBack)
    Scaffold(
        modifier = Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.systemBars),
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        topBar = { Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
            TextButton(onClick = onBack) { Text("← Назад") }
            Text("Прогноз і напливи", Modifier.padding(top = 15.dp), fontWeight = FontWeight.Bold)
        } },
        bottomBar = { Surface(color = Color(0xFF0A0A0A)) {
            Text("Функція в розробці", Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp),
                color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
        } },
    ) { padding ->
        LazyColumn(Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(20.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Text("Виберіть кілька КПП", fontSize = 28.sp, fontWeight = FontWeight.Black)
                Text("Прогноз попереджає про можливий наплив у наступні 24 години. Факт повідомляє, коли різке зростання вже почалося.",
                    Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodyMedium)
            }
            item { SurgePanel { Column(Modifier.padding(16.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("Голосові сповіщення", Modifier.weight(1f).padding(top = 12.dp))
                    Switch(checked = voice, onCheckedChange = { enabled ->
                        if (local.setVoiceEnabled(enabled)) { voice = enabled; voiceProblem = null }
                    })
                }
                Text(SurgePresentation.voiceHint(voice, notificationsAllowed, voiceProblem), style = MaterialTheme.typography.bodySmall)
                if (!notificationsAllowed) TextButton(onClick = onOpenNotificationSettings) { Text("Дозволити повідомлення") }
            } } }
            if (loading) item { CircularProgressIndicator(); Text("Завантажуємо КПП…") }
            error?.let { message -> item { SurgePanel { Column(Modifier.padding(16.dp)) {
                Text(message)
                TextButton(onClick = { scope.launch { refresh() } }) { Text("Оновити") }
                if (subscriptions.isNotEmpty()) Text("Показано попередній вибір. Актуальність даних не підтверджена")
            } } } }
            if (!loading && error == null) item {
                Text("Вибрано КПП: ${subscriptions.size}", fontWeight = FontWeight.Bold)
                if (subscriptions.isEmpty()) Text("Увімкніть потрібні КПП у списку нижче")
            }
            items(checkpoints, key = { it.checkpoint_id }) { cp ->
                val sub = subscriptions.firstOrNull { it.checkpoint_id == cp.checkpoint_id }
                SurgePanel { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Row(Modifier.fillMaxWidth()) {
                        Text("${cp.flag_emoji.orEmpty()} ${cp.title}", Modifier.weight(1f).padding(top = 12.dp), fontWeight = FontWeight.Bold)
                        Checkbox(checked = sub != null, enabled = !busy, onCheckedChange = { selected ->
                            change(cp, cp.forecast_supported, cp.fact_supported, remove = !selected)
                        })
                    }
                    if (sub != null) {
                        Row {
                            Checkbox(checked = sub.forecast_enabled, enabled = !busy && cp.forecast_supported,
                                onCheckedChange = { change(cp, it, sub.fact_enabled) })
                            Text("Можливий наплив — прогноз", Modifier.padding(top = 12.dp))
                        }
                        if (!cp.forecast_supported) Text("Прогноз для цього КПП поки недоступний", style = MaterialTheme.typography.bodySmall)
                        Row {
                            Checkbox(checked = sub.fact_enabled, enabled = !busy && cp.fact_supported,
                                onCheckedChange = { change(cp, sub.forecast_enabled, it) })
                            Text("Початок зростання — факт", Modifier.padding(top = 12.dp))
                        }
                        val cards = SurgePresentation.cards(cp, if (error == null) snapshots[cp.checkpoint_id] else null, now)
                        val active = sub.alerts.filter { alert ->
                            !local.isBlocked(alert.surge_alert_id) &&
                                runCatching { Instant.parse(alert.expires_at) > now }.getOrDefault(false)
                        }
                        val forecastAlert = active.firstOrNull { it.kind == "surge_forecast" }
                        val factAlert = active.firstOrNull { it.kind == "surge_started" }
                        Text("Прогноз", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                        Text(forecastAlert?.body ?: cards.forecast)
                        cards.window?.let { Text("Можливе вікно: $it", style = MaterialTheme.typography.bodySmall) }
                        forecastAlert?.let { alert ->
                            TextButton(onClick = { acknowledge(alert) }) { Text("Зрозуміло") }
                        }
                        Text("Фактичне зростання", color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.Bold)
                        Text(factAlert?.body ?: if (error != null) "Актуальні дані не отримано" else cards.fact)
                        factAlert?.let { alert ->
                            alert.growth_5m?.let { Text("+$it авто за 5 хвилин", style = MaterialTheme.typography.bodySmall) }
                            TextButton(onClick = { acknowledge(alert) }) { Text("Зрозуміло") }
                        }
                        TextButton(onClick = { onCountForecast(cp.checkpoint_id) }) { Text("Орієнтовна черга на добу →") }
                    }
                } }
            }
        }
    }
}


@Composable
private fun SurgePanel(content: @Composable ColumnScope.() -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, Color(0x38FFFFFF)),
        colors = CardDefaults.cardColors(containerColor = Color(0xFF0A0A0A)),
        content = content,
    )
}
