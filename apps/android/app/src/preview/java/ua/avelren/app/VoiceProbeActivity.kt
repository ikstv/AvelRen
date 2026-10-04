package ua.avelren.app

import android.app.Activity
import android.os.Bundle
import android.widget.TextView
import kotlinx.coroutines.*
import ua.avelren.app.notify.*

/** Local-only preparation of the product assets; events arrive through the debug receiver. */
class VoiceProbeActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val status = TextView(this).apply {
            text = "Підготовка системного голосу…"; textSize = 22f
            setPadding(40, 100, 40, 40)
        }
        setContentView(status)
        scope.launch {
            Notifications.ensureChannel(this@VoiceProbeActivity)
            SurgeLocalStore(this@VoiceProbeActivity).enableVoiceForFirstMonitoring()
            for ((id, title) in listOf(17 to "Чоп", 6 to "Краківець", 1 to "Ягодин", 29 to "Ягодин для порожніх вантажівок", 5 to "Рава-Руська")) {
                when (val result = SurgeVoiceAssets(this@VoiceProbeActivity).prepare(id, title)) {
                    is VoicePreparation.Ready -> result.voices.forEach { SurgeVoiceChannels.ensure(this@VoiceProbeActivity, it, title) }
                    is VoicePreparation.Failure -> { status.text = "Голос не готовий: ${result.reason}"; return@launch }
                }
            }
            openFileOutput("system-voice-ready", MODE_PRIVATE).use { it.write("ready-v1".toByteArray()) }
            status.text = "Голос готовий. Тестові події запускаються окремо."
        }
    }
    override fun onStop() { scope.coroutineContext.cancelChildren(); super.onStop() }
    override fun onDestroy() { scope.cancel(); super.onDestroy() }
}
