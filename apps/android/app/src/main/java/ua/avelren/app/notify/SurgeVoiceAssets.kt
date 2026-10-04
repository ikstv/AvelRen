package ua.avelren.app.notify

import android.content.Context
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.AtomicFile
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import ua.avelren.app.data.CheckpointSpeech

@Serializable
data class PreparedVoice(val key: VoiceSoundKey, val text: String, val voiceName: String, val sha256: String, val durationMs: Long)

sealed interface VoicePreparation {
    data class Ready(val voices: List<PreparedVoice>) : VoicePreparation
    data class Failure(val reason: String) : VoicePreparation
}

@Serializable
private data class VoiceRecord(val voice: PreparedVoice, val policy: Int = 1, val pitch: Float = 1f, val rate: Float = .88f)

/** Foreground synthesis only. Delivery reads verified files and never starts TTS. */
class SurgeVoiceAssets(context: Context) {
    private val app = context.applicationContext
    private val root = File(app.filesDir, "surge-voice/v1")
    private fun valid(key: VoiceSoundKey) = VoiceAssetPolicy.parsePath("/v1/${key.checkpointId}/${key.kind}.wav") == key
    private fun file(key: VoiceSoundKey) = File(root, "${key.checkpointId}/${key.kind}.wav")
    private fun metadata(key: VoiceSoundKey) = AtomicFile(File(root, "${key.checkpointId}/${key.kind}.json"))

    fun ready(key: VoiceSoundKey): PreparedVoice? = synchronized(diskLock) {
        if (!valid(key)) return@synchronized null
        runCatching {
            val record = json.decodeFromString<VoiceRecord>(metadata(key).readFully().toString(Charsets.UTF_8))
            val voice = record.voice
            require(record.policy == 1 && record.pitch == 1f && record.rate == .88f && voice.key == key && voice.voiceName.isNotBlank())
            val audio = file(key)
            require(audio.length() in 44..MAX_WAV_BYTES)
            val bytes = audio.readBytes()
            require(sha(bytes) == voice.sha256 && VoiceAssetPolicy.inspectWav(bytes)?.durationMs == voice.durationMs)
            voice
        }.getOrNull()
    }
    fun soundUri(key: VoiceSoundKey): Uri {
        require(valid(key))
        return Uri.Builder().scheme("content").authority("${app.packageName}.surgevoice")
            .path("/v1/${key.checkpointId}/${key.kind}.wav").build()
    }
    fun openReady(key: VoiceSoundKey): ParcelFileDescriptor? = synchronized(diskLock) {
        if (ready(key) == null) null else runCatching {
            ParcelFileDescriptor.open(file(key), ParcelFileDescriptor.MODE_READ_ONLY)
        }.getOrNull()
    }

    suspend fun prepare(checkpointId: Int, title: String): VoicePreparation = preparationLock.withLock {
        if (checkpointId <= 0 || title.isBlank()) return@withLock VoicePreparation.Failure("voice_not_ready")
        val keys = listOf("surge_forecast", "surge_started").map { VoiceSoundKey(checkpointId, it) }
        val texts = keys.associateWith { CheckpointSpeech.message(it.kind, checkpointId, title) }
        val existing = withContext(Dispatchers.IO) { keys.map { key -> ready(key)?.takeIf { it.text == texts[key] } } }
        if (existing.all { it != null }) return@withLock VoicePreparation.Ready(existing.filterNotNull())
        withContext(Dispatchers.Main.immediate) {
            var engine: TextToSpeech? = null
            var temporary: File? = null
            var complete = false
            try {
                withContext(Dispatchers.IO) { synchronized(diskLock) { keys.forEach { metadata(it).delete() } } }
                val initialized = CompletableDeferred<Int>()
                engine = TextToSpeech(app) { initialized.complete(it) }
                if (withTimeout(10_000) { initialized.await() } != TextToSpeech.SUCCESS)
                    return@withContext VoicePreparation.Failure("tts_unavailable")
                val tts = engine
                val voices = tts.voices.orEmpty().filter {
                    it.locale.language == "uk" && !it.isNetworkConnectionRequired &&
                        TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED !in it.features.orEmpty()
                }
                val voice = voices.firstOrNull { it.name == "uk-UA-language" }
                    ?: voices.firstOrNull { it.name == tts.defaultVoice?.name } ?: voices.sortedBy { it.name }.firstOrNull()
                if (voice == null || tts.setVoice(voice) != TextToSpeech.SUCCESS)
                    return@withContext VoicePreparation.Failure("uk_unavailable")
                if (tts.setPitch(1f) != TextToSpeech.SUCCESS || tts.setSpeechRate(.88f) != TextToSpeech.SUCCESS)
                    return@withContext VoicePreparation.Failure("tts_unavailable")
                val prepared = mutableListOf<PreparedVoice>()
                for (key in keys) {
                    currentCoroutineContext().ensureActive()
                    val target = file(key)
                    withContext(Dispatchers.IO) { check(target.parentFile!!.isDirectory || target.parentFile!!.mkdirs()) }
                    val temp = File.createTempFile("synthesis-", ".wav", target.parentFile)
                    temporary = temp
                    val done = CompletableDeferred<Boolean>()
                    val utterance = UUID.randomUUID().toString()
                    tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) = Unit
                        override fun onDone(utteranceId: String?) { if (utteranceId == utterance) done.complete(true) }
                        @Deprecated("Platform callback")
                        override fun onError(utteranceId: String?) { if (utteranceId == utterance) done.complete(false) }
                        override fun onError(utteranceId: String?, errorCode: Int) { if (utteranceId == utterance) done.complete(false) }
                    })
                    if (tts.synthesizeToFile(texts.getValue(key), null, temp, utterance) != TextToSpeech.SUCCESS ||
                        !withTimeout(30_000) { done.await() }) return@withContext VoicePreparation.Failure("tts_unavailable")
                    val result = withContext(Dispatchers.IO) {
                        require(temp.length() in 44..MAX_WAV_BYTES)
                        val bytes = temp.readBytes()
                        val wav = VoiceAssetPolicy.inspectWav(bytes) ?: error("Invalid synthesized WAV")
                        PreparedVoice(key, texts.getValue(key), voice.name, sha(bytes), wav.durationMs).also { ready ->
                            currentCoroutineContext().ensureActive()
                            synchronized(diskLock) {
                                writeAtomic(AtomicFile(target), bytes)
                                writeAtomic(metadata(key), json.encodeToString(VoiceRecord(ready)).toByteArray())
                            }
                        }
                    }
                    prepared += result
                    temp.delete()
                    temporary = null
                }
                complete = true
                VoicePreparation.Ready(prepared)
            } catch (_: TimeoutCancellationException) {
                synchronized(diskLock) { keys.forEach { metadata(it).delete() } }
                VoicePreparation.Failure("tts_unavailable")
            } catch (cancelled: CancellationException) {
                synchronized(diskLock) { keys.forEach { metadata(it).delete() } }
                throw cancelled
            } catch (_: Exception) {
                synchronized(diskLock) { keys.forEach { metadata(it).delete() } }
                VoicePreparation.Failure("voice_not_ready")
            } finally {
                if (!complete) synchronized(diskLock) { keys.forEach { metadata(it).delete() } }
                runCatching { engine?.stop() }
                runCatching { engine?.shutdown() }
                temporary?.delete()
            }
        }
    }
    private fun writeAtomic(file: AtomicFile, bytes: ByteArray) {
        val stream = file.startWrite()
        try { stream.write(bytes); file.finishWrite(stream) }
        catch (error: Exception) { file.failWrite(stream); throw error }
    }
    companion object {
        private const val MAX_WAV_BYTES = 1_500_000L
        private val diskLock = Any()
        private val preparationLock = Mutex()
        private val json = Json { ignoreUnknownKeys = false }
        private fun sha(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
