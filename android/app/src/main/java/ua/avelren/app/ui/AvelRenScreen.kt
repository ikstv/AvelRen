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
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

private val THRESHOLDS = listOf(50, 100, 150, 200, 250, 300, 350, 400, 450, 500)
private val KYIV: ZoneId = ZoneId.of("Europe/Kyiv")
private val FORMAT: DateTimeFormatter = DateTimeFormatter.ofPattern("dd.MM 'о' HH:mm")

/**
 * The main screen.
 *
 * All content is a single `LazyColumn`, not a `Column` with nested lists.
 * Otherwise cards that do not fit the screen height are silently clipped: they
 * are drawn, but you cannot see them and cannot scroll to them. This is exactly
 * how the telemetry disappeared once there were more than three cards.
 */
@Composable
fun AvelRenScreen(
    permissionState: NotificationPermissionState = NotificationPermissionState.Granted,
    onRequestPermission: () -> Unit = {},
    onOpenSettings: () -> Unit = {},
    themeMode: ua.avelren.app.ui.theme.ThemeMode = ua.avelren.app.ui.theme.ThemeMode.SYSTEM,
    onThemeChange: (ua.avelren.app.ui.theme.ThemeMode) -> Unit = {},
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
    // Updated on EVERY poll (even if the payload did not change), so that freshness
    // advances and the UI transitions to stale when the collector hangs while the
    // API returns the same snapshot (B2).
    var freshnessNow by remember { mutableStateOf(Instant.now()) }
    var showEtaDialog by remember { mutableStateOf(false) }
    var note by remember { mutableStateOf<String?>(null) }
    var forecast by remember { mutableStateOf<Api.Forecast?>(null) }
    var telemetry by remember { mutableStateOf<Api.Telemetry?>(null) }
    var subs by remember { mutableStateOf<List<Api.Subscription>>(emptyList()) }
    var targets by remember { mutableStateOf<List<Api.EtaTarget>>(emptyList()) }
    var reload by remember { mutableStateOf(0) }

    // Live refresh (AND-4): refresh immediately on entry/return, then every
    // 60 s — but ONLY in the foreground (repeatOnLifecycle(RESUMED) pauses on
    // backgrounding and restarts on return → an immediate refresh). Keyed on
    // `selected`, so a change of checkpoint refreshes the forecast at once,
    // without waiting for the cycle. Workload and forecast are independent: a
    // failure of one does not block the other, and on error the last valid data
    // is NOT erased (keep-last).
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
                    // keep-last only for the same checkpoint: forecast(A) must not
                    // remain under the card of checkpoint B (B1).
                    forecast = LiveRefresh.scopedForecast(forecast, fcRes, selected)
                    forecastError = fcRes.isFailure
                } else {
                    forecast = null
                    forecastError = false
                }
                // The freshness clock advances on every poll, regardless of the payload.
                freshnessNow = Instant.now()
                loading = false
            }
        }
    }

    // Protected data is loaded through the same seam covered by the test
    // (ProtectedLoad.observe): as soon as the installation becomes Ready we load;
    // a new Ready after a recovery re-registration retriggers by itself, without a
    // restart. `reload` restarts the effect (the StateFlow immediately replays the
    // current Ready), so a local mutation also refreshes the data.
    LaunchedEffect(reload) {
        ProtectedLoad.observe(installation.state) {
            subs = runCatching {
                installation.authenticatedCall { Api.subscriptions(it) }
            }.getOrDefault(emptyList())
            targets = runCatching {
                installation.authenticatedCall { Api.etaTargets(it) }
            }.getOrDefault(emptyList())
            // A 403 for an ordinary device — the card simply will not appear.
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

    LazyColumn(modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        item {
            Column(modifier = Modifier.padding(top = 16.dp)) {
                Text("AvelRen", style = MaterialTheme.typography.headlineMedium)
                Text("Черги на кордоні — вантажівки",
                    style = MaterialTheme.typography.bodySmall)
            }
        }

        // AND-2: notifications are blocked — the alert will not arrive. This is the
        // whole point of the app, so we show it explicitly and give a way back (a
        // request or the needed settings).
        if (permissionState !is NotificationPermissionState.Granted) {
            item { NotificationBanner(permissionState, onRequestPermission, onOpenSettings) }
        }

        // Appearance · theme toggle (a Modernist segmented control). The choice
        // applies instantly and survives a restart (DataStore).
        item {
            Column(modifier = Modifier.padding(top = 16.dp)) {
                Text(
                    "ВИГЛЯД · ТЕМА ЗАСТОСУНКУ",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(bottom = 8.dp),
                )
                ThemeToggle(mode = themeMode, onChange = onThemeChange)
            }
        }

        // Freshness by the server observation time of the selected checkpoint (with
        // no selection — the max across the list). If the selected one disappeared
        // from the snapshot — current==null → time==null → stale, we do not
        // substitute someone else's time.
        if (workload.isNotEmpty()) {
            item {
                val obsTime =
                    if (selected > 0) current?.time
                    else workload.mapNotNull { it.time }.maxOrNull()
                val f = LiveRefresh.freshness(obsTime, freshnessNow)
                val suffix = when {
                    refreshError -> " · не вдалося оновити"
                    forecastError -> " · прогноз не оновився"
                    f.stale -> " · дані застарілі"
                    else -> ""
                }
                Text(
                    "Оновлено ${f.label}$suffix",
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }

        // A full-screen error only when there is no data at all yet. If an old
        // valid snapshot exists — we do not overwrite the screen, the status is
        // shown by the line above.
        if (workload.isEmpty()) {
            error?.let { msg ->
                item {
                    Text("Не вдалося завантажити: $msg",
                        modifier = Modifier.padding(top = 24.dp))
                }
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

            // Defense-in-depth (B1): even if a forecast of another checkpoint leaked
            // into the state — we do not show it under the selected one's card.
            item { ForecastCard(forecast?.takeIf { it.checkpoint_id == selected }) }
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
            )
            // NeedsRequest — the system dialog is still possible; the other states
            // (permanent denial, revoke, disabled channel) are cured only in the
            // settings, so the button leads exactly there.
            val canAskInApp = state is NotificationPermissionState.NeedsRequest
            Button(
                onClick = if (canAskInApp) onRequest else onOpenSettings,
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
        // FlowRow wraps the chips onto as many rows as needed by itself. There used
        // to be a nested list here — that is what broke scrolling of the whole screen.
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
