package ua.avelren.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import ua.avelren.app.ui.theme.ThemeMode

// UI preferences (theme choice + onboarding-seen). Non-secret, so a plain
// DataStore is fine (device secrets stay in EncryptedSharedPreferences).
private val Context.uiPrefs by preferencesDataStore("ui_prefs")
private val THEME_KEY = stringPreferencesKey("theme_mode")
private val ONBOARDING_KEY = booleanPreferencesKey("onboarding_seen")

object ThemePrefs {
    fun themeModeFlow(ctx: Context): Flow<ThemeMode> =
        ctx.uiPrefs.data.map { prefs ->
            runCatching { ThemeMode.valueOf(prefs[THEME_KEY] ?: ThemeMode.SYSTEM.name) }
                .getOrDefault(ThemeMode.SYSTEM)
        }

    suspend fun setThemeMode(ctx: Context, mode: ThemeMode) {
        ctx.uiPrefs.edit { it[THEME_KEY] = mode.name }
    }

    fun onboardingSeenFlow(ctx: Context): Flow<Boolean> =
        ctx.uiPrefs.data.map { it[ONBOARDING_KEY] ?: false }

    suspend fun setOnboardingSeen(ctx: Context) {
        ctx.uiPrefs.edit { it[ONBOARDING_KEY] = true }
    }
}
