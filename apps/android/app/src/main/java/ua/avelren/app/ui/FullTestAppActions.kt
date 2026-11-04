package ua.avelren.app.ui

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import ua.avelren.app.BuildConfig
import ua.avelren.app.ui.theme.AppBackground
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.hapticClick

// Share a verified public release page. FullTest is an unpublished, separate package.
private const val PUBLIC_RELEASE_URL = "https://github.com/ikstv/AvelRen/releases/latest"
private const val OFFICIAL_PACKAGE = "ua.avelren.app"

internal fun shareAvelRen(context: Context) {
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/plain"
        putExtra(Intent.EXTRA_SUBJECT, "AvelRen — черги на кордоні")
        putExtra(Intent.EXTRA_TEXT, "AvelRen — стан черг на кордоні, прогнози та сповіщення.\nЗавантажити додаток: $PUBLIC_RELEASE_URL")
    }
    if (!context.tryOpen(Intent.createChooser(send, "Поділитися AvelRen"))) {
        context.actionUnavailable("Не вдалося відкрити меню поширення")
    }
}

internal fun openAvelRenStore(context: Context) {
    val market = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$OFFICIAL_PACKAGE"))
        .setPackage("com.android.vending")
    val web = Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=$OFFICIAL_PACKAGE"))
    if (!context.tryOpen(market) && !context.tryOpen(web)) {
        context.actionUnavailable("Не вдалося відкрити Google Play")
    }
}

internal fun openAvelRenPrivacy(context: Context) {
    if (!context.tryOpen(Intent(Intent.ACTION_VIEW, Uri.parse("https://api.bordersignal.pp.ua/privacy?v=20260924")))) {
        context.actionUnavailable("Не вдалося відкрити політику конфіденційності")
    }
}

private fun Context.tryOpen(intent: Intent): Boolean = try {
    startActivity(intent)
    true
} catch (_: ActivityNotFoundException) {
    false
} catch (_: SecurityException) {
    false
}

private fun Context.actionUnavailable(message: String) {
    Toast.makeText(this, message, Toast.LENGTH_LONG).show()
}

@Composable
internal fun FullTestRatingInfo(onDismiss: () -> Unit, onOpenStore: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = AppBackground,
        titleContentColor = AppInk,
        textContentColor = AppInk,
        title = { Text("Оцінити AvelRen") },
        text = {
            Text(if (BuildConfig.DEBUG) "FullTest — окрема тестова збірка без публічних оцінок. Відкриємо офіційний AvelRen у Google Play." else "Відкриємо сторінку AvelRen у Google Play, де можна оцінити додаток.")
        },
        confirmButton = { TextButton(onClick = hapticClick(onOpenStore)) { Text("Відкрити Google Play") } },
        dismissButton = { TextButton(onClick = hapticClick(onDismiss)) { Text("Назад") } },
    )
}
