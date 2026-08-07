package ua.avelren.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch
import androidx.compose.runtime.rememberCoroutineScope
import ua.avelren.app.data.Api
import ua.avelren.app.data.DeviceStore
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val THRESHOLDS = listOf(50, 100, 150, 200, 250, 300, 350, 400, 450, 500)
private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

@Composable
fun AvelRenScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var workload by remember { mutableStateOf<List<Api.Workload>>(emptyList()) }
    var selected by remember { mutableStateOf(DeviceStore.selectedCheckpoint(context)) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showEtaDialog by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
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

    LaunchedEffect(reload) {
        DeviceStore.deviceId(context)?.let { id ->
            subs = runCatching { Api.subscriptions(id) }.getOrDefault(emptyList())
            targets = runCatching { Api.etaTargets(id) }.getOrDefault(emptyList())
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

    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
        Text("AvelRen", style = MaterialTheme.typography.headlineMedium)
        Text(
            "Черги на кордоні — вантажівки",
            style = MaterialTheme.typography.bodySmall,
        )

        when {
            loading -> Row(
                modifier = Modifier.fillMaxSize(),
                horizontalArrangement = Arrangement.Center,
                verticalAlignment = Alignment.CenterVertically,
            ) { CircularProgressIndicator() }

            error != null -> Text(
                "Не вдалося завантажити: $error",
                modifier = Modifier.padding(top = 24.dp),
            )

            else -> {
                if (current != null) {
                    SelectedCard(current)
                    ThresholdRow(
                        onPick = { threshold ->
                            scope.launch {
                                DeviceStore.deviceId(context)?.let {
                                    runCatching { Api.subscribe(it, current.checkpoint_id, threshold) }
                                        .onSuccess { note = "Стежу: поріг $threshold авто"; reload++ }
                                        .onFailure { note = "Не вдалося підписатись" }
                                }
                            }
                        },
                    )

                    Button(
                        onClick = { showEtaDialog = true },
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    ) { Text("Хочу в'їхати о певній годині") }

                    note?.let {
                        Text(it, style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.padding(top = 6.dp))
                    }

                    ForecastCard(forecast)

                    SubscriptionsSection(
                        subscriptions = subs,
                        targets = targets,
                        onRemoveSubscription = { id ->
                            scope.launch {
                                DeviceStore.deviceId(context)?.let {
                                    runCatching { Api.unsubscribe(it, id) }
                                    reload++
                                }
                            }
                        },
                        onRemoveTarget = { id ->
                            scope.launch {
                                DeviceStore.deviceId(context)?.let {
                                    runCatching { Api.deleteEtaTarget(it, id) }
                                    reload++
                                }
                            }
                        },
                    )

                    HorizontalDivider(modifier = Modifier.padding(vertical = 12.dp))
                }

                if (showEtaDialog && current != null) {
                    EtaTargetDialog(
                        checkpointTitle = current.title,
                        onDismiss = { showEtaDialog = false },
                        onConfirm = { isoUtc, human ->
                            showEtaDialog = false
                            scope.launch {
                                DeviceStore.deviceId(context)?.let {
                                    runCatching {
                                        Api.createEtaTarget(it, current.checkpoint_id, isoUtc)
                                    }
                                        .onSuccess { note = "Стежу за в'їздом $human"; reload++ }
                                        .onFailure { note = "Не вдалося створити ціль" }
                                }
                            }
                        },
                    )
                }

                Text(
                    if (current == null) "Оберіть пункт пропуску" else "Змінити пункт",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(vertical = 8.dp),
                )

                LazyColumn {
                    items(workload.sortedByDescending { it.vehicles_in_queue }) { item ->
                        CheckpointRow(item) {
                            selected = item.checkpoint_id
                            DeviceStore.saveSelectedCheckpoint(context, item.checkpoint_id)
                        }
                    }
                }
            }
        }
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

@Composable
private fun ThresholdRow(onPick: (Int) -> Unit) {
    Text("Сповістити, коли черга зросте до:", style = MaterialTheme.typography.bodyMedium)
    LazyColumn(modifier = Modifier.padding(top = 4.dp)) {
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                THRESHOLDS.take(5).forEach { t ->
                    AssistChip(onClick = { onPick(t) }, label = { Text("$t") })
                }
            }
        }
        item {
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(top = 4.dp),
            ) {
                THRESHOLDS.drop(5).forEach { t ->
                    AssistChip(onClick = { onPick(t) }, label = { Text("$t") })
                }
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
            Text("${item.flag_emoji ?: ""} ${item.title}", style = MaterialTheme.typography.bodyMedium)
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
