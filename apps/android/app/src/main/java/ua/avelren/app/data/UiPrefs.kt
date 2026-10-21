package ua.avelren.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import ua.avelren.app.ui.theme.ThemeChoice
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

// UI preferences. Non-secret, so a plain DataStore is fine (device secrets stay
// in EncryptedSharedPreferences).
private val Context.uiPrefs by preferencesDataStore("ui_prefs")
private val ONBOARDING_KEY = booleanPreferencesKey("onboarding_seen")

private val FORECAST_IDS = stringPreferencesKey("forecast_preview_checkpoints")
private val THEME_KEY = stringPreferencesKey("theme")
private val KEEP_SCREEN_ON_KEY = booleanPreferencesKey("fulltest_keep_screen_on")
private val FAVORITE_IDS = stringPreferencesKey("fulltest_favorite_checkpoints")

object UiPrefs {
    fun favoriteIdsFlow(ctx: Context): Flow<List<Int>> =
        ctx.uiPrefs.data.map { FavoriteCheckpoints.parse(it[FAVORITE_IDS]) }

    suspend fun toggleFavoriteCheckpoint(ctx: Context, id: Int) {
        ctx.uiPrefs.edit { prefs ->
            prefs[FAVORITE_IDS] = FavoriteCheckpoints.toggle(
                FavoriteCheckpoints.parse(prefs[FAVORITE_IDS]), id,
            ).joinToString(",")
        }
    }

    fun keepScreenOnFlow(ctx: Context): Flow<Boolean> =
        ctx.uiPrefs.data.map { it[KEEP_SCREEN_ON_KEY] ?: false }

    suspend fun setKeepScreenOn(ctx: Context, enabled: Boolean) {
        ctx.uiPrefs.edit { it[KEEP_SCREEN_ON_KEY] = enabled }
    }

    fun forecastIdsFlow(ctx: Context): Flow<List<Int>> =
        ctx.uiPrefs.data.map { ForecastSelection.parse(it[FORECAST_IDS]) }

    suspend fun changeForecastCheckpoint(ctx: Context, id: Int, selected: Boolean) {
        ctx.uiPrefs.edit { prefs ->
            val current = ForecastSelection.parse(prefs[FORECAST_IDS])
            val next = if (selected) ForecastSelection.add(current, id) else ForecastSelection.remove(current, id)
            prefs[FORECAST_IDS] = next.joinToString(",")
        }
    }

    fun themeFlow(ctx: Context): Flow<ThemeChoice> =
        ctx.uiPrefs.data.map { ThemeChoice.fromStored(it[THEME_KEY]) }

    suspend fun setTheme(ctx: Context, theme: ThemeChoice) {
        ctx.uiPrefs.edit { it[THEME_KEY] = theme.name }
    }

    fun onboardingSeenFlow(ctx: Context): Flow<Boolean> =
        ctx.uiPrefs.data.map { it[ONBOARDING_KEY] ?: false }

    suspend fun setOnboardingSeen(ctx: Context) {
        ctx.uiPrefs.edit { it[ONBOARDING_KEY] = true }
    }
}
