package ua.avelren.app.notify

import android.content.ContentProvider
import android.content.ContentValues
import android.database.Cursor
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import java.io.FileNotFoundException

class SurgeVoiceProvider : ContentProvider() {
    override fun onCreate() = true
    private fun key(uri: Uri): VoiceSoundKey? {
        if (uri.scheme != "content" || uri.authority != "${context!!.packageName}.surgevoice" ||
            uri.query != null || uri.fragment != null) return null
        return VoiceAssetPolicy.parsePath(uri.encodedPath.orEmpty())
    }
    override fun openFile(uri: Uri, mode: String): ParcelFileDescriptor {
        val sound = if (mode == "r") key(uri) else null
        return sound?.let { SurgeVoiceAssets(context!!).openReady(it) } ?: throw FileNotFoundException("Sound unavailable")
    }
    override fun getType(uri: Uri): String? = key(uri)?.let {
        if (SurgeVoiceAssets(context!!).ready(it) != null) "audio/wav" else null
    }
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? {
        if (selection != null || selectionArgs != null || sortOrder != null) return null
        val sound = key(uri) ?: return null
        val columns = projection?.filter { it == OpenableColumns.DISPLAY_NAME || it == OpenableColumns.SIZE }
            ?: listOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)
        val descriptor = SurgeVoiceAssets(context!!).openReady(sound) ?: return null
        val size = descriptor.use { it.statSize }
        return MatrixCursor(columns.toTypedArray()).apply {
            addRow(columns.map { if (it == OpenableColumns.DISPLAY_NAME) "${sound.kind}.wav" else size })
        }
    }
    override fun insert(uri: Uri, values: ContentValues?): Uri = throw UnsupportedOperationException("Read only")
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?): Int = throw UnsupportedOperationException("Read only")
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?): Int = throw UnsupportedOperationException("Read only")
}
