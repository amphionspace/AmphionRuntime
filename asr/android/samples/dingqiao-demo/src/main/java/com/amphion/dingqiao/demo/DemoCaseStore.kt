package com.amphion.dingqiao.demo

import org.json.JSONObject
import java.io.File

data class DemoCaseSaveResult(
    val caseId: String,
    val caseDir: File,
)

class DemoCaseStore(private val root: File) {

    fun save(pcm: ByteArray, note: String, metadata: JSONObject): DemoCaseSaveResult {
        require(pcm.isNotEmpty()) { "case audio is empty" }
        check(root.mkdirs() || root.isDirectory) { "cannot create case root: ${root.absolutePath}" }
        val caseId = allocateCaseId()
        val caseDir = File(root, caseId)
        check(caseDir.mkdir()) { "cannot create case dir: ${caseDir.absolutePath}" }

        val normalizedNote = note.trim()
        WavIo.writePcmBytes(File(caseDir, AUDIO_FILE), pcm)
        File(caseDir, NOTE_FILE).writeText("$normalizedNote\n", Charsets.UTF_8)
        metadata
            .put("caseId", caseId)
            .put("createdAtMs", System.currentTimeMillis())
            .put("audioFile", AUDIO_FILE)
            .put("noteFile", NOTE_FILE)
            .put("note", normalizedNote)
        // Metadata is written last and acts as the completion marker for adb pull tooling.
        File(caseDir, METADATA_FILE).writeText(metadata.toString(2) + "\n", Charsets.UTF_8)
        return DemoCaseSaveResult(caseId, caseDir)
    }

    private fun allocateCaseId(): String {
        val base = "case-${System.currentTimeMillis()}"
        var candidate = base
        var suffix = 0
        while (File(root, candidate).exists()) {
            suffix += 1
            candidate = "$base-$suffix"
        }
        return candidate
    }

    private companion object {
        const val AUDIO_FILE = "audio.wav"
        const val NOTE_FILE = "note.txt"
        const val METADATA_FILE = "metadata.json"
    }
}
