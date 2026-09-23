package ua.avelren.app.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

// UI preferences. Non-secret, so a plain DataStore is fine (device secrets stay
// in EncryptedSharedPreferences).
private val Context.uiPrefs by preferencesDataStore("ui_prefs")
private val ONBOARDING_KEY = booleanPreferencesKey("onboarding_seen")

object UiPrefs {
    fun onboardingSeenFlow(ctx: Context): Flow<Boolean> =
        ctx.uiPrefs.data.map { it[ONBOARDING_KEY] ?: false }

    suspend fun setOnboardingSeen(ctx: Context) {
        ctx.uiPrefs.edit { it[ONBOARDING_KEY] = true }
    }
}
