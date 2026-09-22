package ua.avelren.app.data

import android.content.Context
import java.time.Instant

/** Лише коротке підтверджене вікно; кеш переживає закриття застосунку. */
class MaintenanceStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences("server_status", Context.MODE_PRIVATE)

    fun read(now: Instant): MaintenanceWindow? {
        val start = prefs.getString("starts_at", null) ?: return null
        val end = prefs.getString("ends_at", null) ?: return null
        return MaintenanceWindow(start, end).takeIf { it.bounds(now) != null }
    }

    fun write(window: MaintenanceWindow?) {
        prefs.edit().apply {
            if (window == null) clear()
            else putString("starts_at", window.starts_at).putString("ends_at", window.ends_at)
        }.apply()
    }
}
