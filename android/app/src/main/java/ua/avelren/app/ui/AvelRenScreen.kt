package ua.avelren.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import ua.avelren.app.AvelRenApp
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.InstallationState
import ua.avelren.app.data.ProtectedLoad
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val THRESHOLDS = listOf(50, 100, 150, 200, 250, 300, 350, 400, 450, 500)
private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

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
    val scope = rememberCoroutineScope()
    val installation = remember { AvelRenApp.from(context).installation }
    val installState by installation.state.collectAsStateWithLifecycle()
    val authReady = installState is InstallationState.Ready

    var workload by remember { mutableStateOf<List<Api.Workload>>(emptyList()) }
    var selected by remember { mutableStateOf(DeviceStore.selectedCheckpoint(context)) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showEtaDialog by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
    var telemetry by remember { mutableStateOf<Api.Telemetry?>(null) }
    var subs by remember { mutableStateOf<List<Api.Subscription>>(emptyList()) }
    var targets by remember { mutableStateOf<List<Api.EtaTarget>>(emptyList()) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(Unit) {
        try {
            workload = Api.workload()
        } catch (e: Exception) {
            error = e.message
        } finally {
            loading = false
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

    // Прогноз залежить від обраного КПП: модель у кожного пункту своя, бо
    // Ягодин з тижнем очікування і порожнє Порубне поводяться несумісно.
    LaunchedEffect(selected) {
        if (selected > 0) {
            forecast = runCatching { Api.forecast(selected) }.getOrNull()
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

    LazyColumn(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        item {
            Column(modifier = Modifier.padding(top = 16.dp)) {
                Text("AvelRen", style = MaterialTheme.typography.headlineMedium)
                Text("Черги на кордоні — вантажівки",
                    style = MaterialTheme.typography.bodySmall)
            }
        }

        error?.let { msg ->
            item {
                Text("Не вдалося завантажити: $msg",
                    modifier = Modifier.padding(top = 24.dp))
            }
        }

        if (current != null) {
            item { SelectedCard(current) }

            item {
                ThresholdRow(enabled = authReady) { threshold ->
                    scope.launch {
                        runCatching {
                            installation.authenticatedCall {
                                Api.subscribe(it, current.checkpoint_id, threshold)
                            }
                        }
                            .onSuccess { note = "Стежу: поріг $threshold авто"; reload++ }
                            .onFailure { note = "Не вдалося підписатись" }
                    }
                }
            }

            item {
                Button(
                    onClick = { showEtaDialog = true },
                    enabled = authReady,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                ) { Text("Хочу в'їхати о певній годині") }
            }

            if (!authReady) {
                item {
                    Text(
                        "Підключення…",
                        style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 6.dp),
                    )
                }
            }

            note?.let { text ->
                item {
                    Text(text, style = MaterialTheme.typography.bodySmall,
                        modifier = Modifier.padding(top = 6.dp))
                }
            }

            item {
                SubscriptionsSection(
                    subscriptions = subs,
                    targets = targets,
                    enabled = authReady,
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

            item { ForecastCard(forecast) }
            item { TelemetryCard(telemetry) }
            item { HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp)) }
        }

        item {
            Text(
                if (current == null) "Оберіть пункт пропуску" else "Змінити пункт",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(vertical = 8.dp),
            )
        }

        items(workload.sortedByDescending { it.vehicles_in_queue }) { item ->
            CheckpointRow(item) {
                selected = item.checkpoint_id
                DeviceStore.saveSelectedCheckpoint(context, item.checkpoint_id)
            }
        }

        item { Column(modifier = Modifier.padding(bottom = 32.dp)) {} }
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

@Composable
private fun SelectedCard(item: Api.Workload) {
    Card(modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                "${item.flag_emoji ?: ""} ${item.title}",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "${item.vehicles_in_queue} авто в черзі",
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(top = 8.dp),
            )
            Text(
                if (item.entry_eta != null) {
                    "Станеш у чергу зараз — в'їзд ${formatEta(item.entry_eta)}"
                } else {
                    "Черга призупинена, прогнозу немає"
                },
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ThresholdRow(enabled: Boolean, onPick: (Int) -> Unit) {
    Column {
        Text("Сповістити, коли черга зросте до:",
            style = MaterialTheme.typography.bodyMedium)
        // FlowRow сам переносить чипи на потрібну кількість рядів. Раніше тут
        // був вкладений список — саме він і ламав прокручування всього екрана.
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            THRESHOLDS.forEach { t ->
                AssistChip(
                    onClick = { onPick(t) },
                    enabled = enabled,
                    label = { Text("$t") },
                )
            }
        }
    }
}

@Composable
private fun CheckpointRow(item: Api.Workload, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text("${item.flag_emoji ?: ""} ${item.title}",
                style = MaterialTheme.typography.bodyMedium)
            Text(
                if (item.entry_eta != null) "в'їзд ${formatEta(item.entry_eta)}" else "призупинено",
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Text("${item.vehicles_in_queue}", fontWeight = FontWeight.Bold)
    }
}

private fun formatEta(iso: String): String =
    runCatching {
        OffsetDateTime.parse(iso).atZoneSameInstant(KYIV).format(FORMAT)
    }.getOrDefault(iso)
