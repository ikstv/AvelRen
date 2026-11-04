package ua.avelren.app.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ProvideTextStyle
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.AppOnAccent
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.hapticClick

/** Спільний діалог FullTest; виклик залишається за експериментальним gate батьківського екрана. */
@Composable
internal fun FullTestDialog(
    title: String,
    onDismiss: () -> Unit,
    actions: @Composable ColumnScope.() -> Unit = {},
    content: @Composable ColumnScope.() -> Unit,
) {
    Dialog(
        onDismissRequest = onDismiss,
        properties = DialogProperties(usePlatformDefaultWidth = true, decorFitsSystemWindows = false),
    ) {
        FullTestPickerWindowChrome(preserveDim = true)
        // Native MATCH_PARENT bounds keep the card inside the actual window;
        // retain the platform dim layer for ordinary dialogs.
        Box(Modifier.fillMaxSize()) {
            // Окремий нижній шар не додає дубль кнопки «Закрити» для TalkBack.
            Box(Modifier.matchParentSize().pointerInput(onDismiss) {
                detectTapGestures { onDismiss() }
            })
            BoxWithConstraints(
                modifier = Modifier.fillMaxSize()
                    .windowInsetsPadding(WindowInsets.safeDrawing)
                    .imePadding()
                    .padding(16.dp),
                contentAlignment = Alignment.Center,
            ) {
                // На низькому екрані або з великим шрифтом дії теж можна прокрутити;
                // вони не витісняють текст із доступної висоти.
                val scrollWholeDialog = maxHeight < 480.dp || LocalDensity.current.fontScale >= 1.5f
                val header: @Composable () -> Unit = {
                    Row(
                        modifier = Modifier.fillMaxWidth().padding(start = 20.dp, top = 12.dp, end = 8.dp, bottom = 12.dp),
                        verticalAlignment = Alignment.Top,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            text = title,
                            modifier = Modifier.weight(1f).padding(top = 10.dp).semantics { heading() },
                            color = AppInk,
                            style = MaterialTheme.typography.titleLarge,
                            fontWeight = FontWeight.Bold,
                        )
                        IconButton(onClick = hapticClick(onDismiss), modifier = Modifier.size(48.dp)) {
                            Icon(Icons.Filled.Close, contentDescription = "Закрити", tint = MaterialTheme.avelren.ink2)
                        }
                    }
                }
                val footer: @Composable () -> Unit = {
                    Column(
                        modifier = Modifier.fillMaxWidth().padding(start = 20.dp, top = 12.dp, end = 20.dp, bottom = 20.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                        content = actions,
                    )
                }
                Surface(
                    modifier = Modifier.widthIn(max = 560.dp).fillMaxWidth().heightIn(max = maxHeight)
                        .pointerInput(Unit) {
                            // Порожні ділянки картки не передають тап на задній шар.
                            // Кнопки й прокрутка дочірніх елементів обробляють свої жести.
                            detectTapGestures { }
                        },
                    shape = RoundedCornerShape(24.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    contentColor = AppInk,
                    border = BorderStroke(1.dp, MaterialTheme.avelren.line),
                    tonalElevation = 0.dp,
                    shadowElevation = 0.dp,
                ) {
                    ProvideTextStyle(MaterialTheme.typography.bodyLarge) {
                        if (scrollWholeDialog) {
                            Column(Modifier.verticalScroll(rememberScrollState())) {
                                header()
                                Column(
                                    modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp),
                                    verticalArrangement = Arrangement.spacedBy(12.dp),
                                    content = content,
                                )
                                footer()
                            }
                        } else {
                            Column {
                                header()
                                Column(
                                    modifier = Modifier.weight(1f, fill = false).fillMaxWidth()
                                        .verticalScroll(rememberScrollState()).padding(horizontal = 20.dp),
                                    verticalArrangement = Arrangement.spacedBy(12.dp),
                                    content = content,
                                )
                                footer()
                            }
                        }
                    }
                }
            }
        }
    }
}

/** Повнорозмірна дія діалогу з природним перенесенням довгого підпису. */
@Composable
internal fun FullTestDialogAction(
    label: String,
    onClick: () -> Unit,
    primary: Boolean = false,
    enabled: Boolean = true,
) {
    val modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)
    val shape = RoundedCornerShape(14.dp)
    val padding = PaddingValues(horizontal = 16.dp, vertical = 12.dp)
    val labelContent: @Composable () -> Unit = {
        Text(label, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyLarge,
            fontWeight = FontWeight.Bold)
    }
    if (primary) {
        Button(
            onClick = hapticClick(onClick),
            modifier = modifier,
            enabled = enabled,
            shape = shape,
            colors = ButtonDefaults.buttonColors(
                containerColor = AppAccent, contentColor = AppOnAccent,
                disabledContainerColor = AppInk.copy(alpha = 0.12f),
                disabledContentColor = AppInk.copy(alpha = 0.38f),
            ),
            elevation = null,
            contentPadding = padding,
        ) { labelContent() }
    } else {
        TextButton(
            onClick = hapticClick(onClick),
            modifier = modifier,
            enabled = enabled,
            shape = shape,
            colors = ButtonDefaults.textButtonColors(
                containerColor = Color.Transparent, contentColor = AppAccent,
                disabledContentColor = AppInk.copy(alpha = 0.38f),
            ),
            contentPadding = padding,
        ) { labelContent() }
    }
}
