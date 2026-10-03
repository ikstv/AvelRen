package ua.avelren.app

import android.app.Activity
import android.app.NotificationManager
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import android.widget.TextView

/** Лише connectedTest: технічна перевірка голосу без push, підписок чи кнопки прикладу. */
class VoiceProbeActivity : Activity() {
    private val handler = Handler(Looper.getMainLooper())
    private var tts: TextToSpeech? = null
    private var focus: AudioFocusRequest? = null
    private lateinit var audio: AudioManager
    private lateinit var status: TextView
    private var closed = false
    private var originalMediaVolume: Int? = null
    private val phrases by lazy {
        if (intent.getStringExtra("scenario") == "yagodyn") listOf(
            ua.avelren.app.data.CheckpointSpeech.message("surge_forecast", 1, "Ягодин – Дорогуськ (для вантажівок ≥ 7,5 тонн)"),
            ua.avelren.app.data.CheckpointSpeech.message("surge_started", 29, "Ягодин – Дорогуськ (для порожніх вантажівок ≥ 7,5 тонн)"),
        ) else listOf(
            ua.avelren.app.data.CheckpointSpeech.message("surge_forecast", 17, "Чоп"),
            ua.avelren.app.data.CheckpointSpeech.message("surge_started", 17, "Чоп"),
        )
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        audio = getSystemService(AudioManager::class.java)
        status = TextView(this).apply {
            text = "Перевірка українського голосу…"
            textSize = 22f
            setTextColor(android.graphics.Color.rgb(255, 215, 0))
            setBackgroundColor(android.graphics.Color.BLACK)
            setPadding(40, 100, 40, 40)
        }
        setContentView(status)
        handler.postDelayed({ report("TIMEOUT"); finish() }, 30_000)
        try {
            tts = TextToSpeech(this) { result -> handler.post { initialize(result) } }
        } catch (_: RuntimeException) { report("TTS_UNAVAILABLE") }
    }

    private fun report(message: String) {
        Log.i("AvelRen/VoiceProbe", message)
        status.text = "Технічна перевірка голосу\n$message"
    }

    private fun initialize(result: Int) {
        if (closed) return
        val engine = tts ?: return
        if (result != TextToSpeech.SUCCESS) { report("TTS_UNAVAILABLE"); return }
        val voices = engine.voices.orEmpty().filter { it.locale.language == "uk" }
        voices.sortedBy { it.name }.forEach {
            Log.i("AvelRen/VoiceProbe", "UK_VOICE name=${it.name} network=${it.isNetworkConnectionRequired} installed=${TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in it.features.orEmpty()}")
        }
        val available = voices.filter {
            !it.isNetworkConnectionRequired && TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in it.features.orEmpty()
        }
        val voice = available.firstOrNull { it.name == "uk-UA-language" }
            ?: available.firstOrNull { it.name == engine.defaultVoice?.name }
            ?: available.sortedBy { it.name }.firstOrNull()
        if (voice == null) { report("UK_OFFLINE_UNAVAILABLE"); return }
        if (engine.setVoice(voice) != TextToSpeech.SUCCESS) { report("VOICE_REJECTED"); return }
        report("SELECTED ${voice.name}")
        if (intent.getBooleanExtra("inspect_only", false)) { finish(); return }
        if (audio.ringerMode != AudioManager.RINGER_MODE_NORMAL ||
            getSystemService(NotificationManager::class.java).currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL) {
            report("SILENT_MODE"); return
        }
        val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_EVENT)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build()
        if (engine.setAudioAttributes(attributes) != TextToSpeech.SUCCESS) {
            report("AUDIO_ATTRIBUTES_REJECTED"); return
        }
        engine.setSpeechRate(0.88f)
        engine.setPitch(1f)
        if (intent.getBooleanExtra("mute_media_test", false)) {
            originalMediaVolume = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, 0, 0)
        }
        Log.i("AvelRen/VoiceProbe", "ROUTE stream=${attributes.volumeControlStream} media=${audio.getStreamVolume(AudioManager.STREAM_MUSIC)} notification=${audio.getStreamVolume(AudioManager.STREAM_NOTIFICATION)} rate=0.88 pitch=1.0")
        val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
            .setAudioAttributes(attributes).setOnAudioFocusChangeListener({ change ->
                if (change < 0) { tts?.stop(); report("AUDIO_FOCUS_LOST"); finish() }
            }, handler).build()
        if (audio.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            report("AUDIO_BUSY"); return
        }
        focus = request
        engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) { Log.i("AvelRen/VoiceProbe", "START $id") }
            override fun onDone(id: String?) { handler.post {
                if (!closed) {
                    report("DONE $id")
                    if (id == "forecast") handler.postDelayed({ speak(1) }, 1500)
                    else handler.postDelayed({ finish() }, 1500)
                }
            } }
            @Deprecated("Platform callback")
            override fun onError(id: String?) { handler.post { report("SPEECH_ERROR $id"); finish() } }
            override fun onError(id: String?, errorCode: Int) { handler.post { report("SPEECH_ERROR $id code=$errorCode"); finish() } }
        })
        speak(0)
    }

    private fun speak(index: Int) {
        if (closed) return
        status.text = "Перевірка голосу\n\n${phrases[index]}"
        val id = if (index == 0) "forecast" else "started"
        if (tts?.speak(phrases[index], TextToSpeech.QUEUE_FLUSH, null, id) != TextToSpeech.SUCCESS)
            report("SPEAK_REJECTED $id")
    }

    override fun onDestroy() {
        closed = true
        handler.removeCallbacksAndMessages(null)
        tts?.stop()
        tts?.shutdown()
        focus?.let { audio.abandonAudioFocusRequest(it) }
        originalMediaVolume?.let {
            audio.setStreamVolume(AudioManager.STREAM_MUSIC, it, 0)
            Log.i("AvelRen/VoiceProbe", "MEDIA_VOLUME_RESTORED $it")
        }
        super.onDestroy()
    }
}
