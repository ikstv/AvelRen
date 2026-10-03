package ua.avelren.app

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.widget.TextView
import com.google.firebase.messaging.FirebaseMessaging
import ua.avelren.app.notify.Notifications
import ua.avelren.app.notify.SurgeLocalStore

/** Debug-only FCM bootstrap. Tokens stay in private app storage, never in UI/logs. */
class PushQaActivity : Activity() {
    private lateinit var status: TextView
    private var tokenReady = false

    private fun showReadiness() {
        if (!tokenReady) return
        status.text = if (Notifications.surgeChannelAllowed(this)) {
            "Перевірка голосових сповіщень\n\nГотово до отримання тестових повідомлень.\n\nЦе окремий тестовий застосунок."
        } else {
            "Перевірка голосових сповіщень\n\nДозвольте сповіщення для цього тестового застосунку в налаштуваннях телефона."
        }
    }

    override fun onResume() {
        super.onResume()
        showReadiness()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        showReadiness()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        status = TextView(this).apply {
            text = "Перевірка голосових сповіщень\n\nПідключення…"
            textSize = 22f
            setTextColor(Color.rgb(245, 196, 0))
            setBackgroundColor(Color.BLACK)
            setPadding(40, 100, 40, 40)
        }
        setContentView(status)
        Notifications.ensureChannel(this)
        SurgeLocalStore(this).enableVoiceForFirstMonitoring()
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        FirebaseMessaging.getInstance().token.addOnCompleteListener(this) { result ->
            if (!result.isSuccessful) {
                status.text = "Не вдалося підключитися. Перевірте інтернет і відкрийте застосунок ще раз."
                return@addOnCompleteListener
            }
            try {
                openFileOutput("push-qa-token", MODE_PRIVATE).use {
                    it.write(result.result.toByteArray(Charsets.UTF_8))
                }
                tokenReady = true
                showReadiness()
            } catch (_: Exception) {
                status.text = "Не вдалося підготувати перевірку. Відкрийте застосунок ще раз."
            }
        }
    }
}
