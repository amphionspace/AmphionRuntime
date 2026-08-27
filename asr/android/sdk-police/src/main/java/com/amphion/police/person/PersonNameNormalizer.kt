package com.amphion.police.person

import android.content.Context
import java.io.File
import java.io.FileOutputStream

/** LAC PER detection plus tone-aware exact-pinyin matching against configured hotwords. */
internal class PersonNameNormalizer(
    context: Context,
    customHotwords: List<String>,
) : AutoCloseable {
    private val ner: LacPersonNer
    private val matcher: PersonNameMatcher

    init {
        val root = installAssets(context)
        ner = LacPersonNer(
            File(root, "lac_encoder.onnx").absolutePath,
            File(root, "lac_crf_transitions.npy").absolutePath,
            File(root, "word.dic").absolutePath,
            File(root, "tag.dic").absolutePath,
            File(root, "q2b.dic").absolutePath,
        )
        val names = customHotwords.map(String::trim).filter { it.length in 2..3 }
        matcher = PersonNameMatcher(loadPinyin(context), names)
    }

    fun normalize(text: String): String {
        if (text.isEmpty()) return text
        val spans = ner.findPersonSpans(text).map { PersonSpan(it.start, it.end) }
        return matcher.normalize(text, spans)
    }

    override fun close() = ner.close()

    private fun installAssets(context: Context): File {
        val root = File(context.filesDir, ASSET_ROOT)
        check(root.mkdirs() || root.isDirectory) { "cannot create ${root.absolutePath}" }
        LAC_FILES.forEach { name ->
            val target = File(root, name)
            if (target.isFile && target.length() > 0) return@forEach
            val temporary = File(root, "$name.tmp")
            try {
                context.assets.open("$ASSET_ROOT/$name").use { input ->
                    FileOutputStream(temporary).use { output ->
                        input.copyTo(output, 64 * 1024)
                        output.fd.sync()
                    }
                }
                check(temporary.length() > 0) { "empty LAC asset: $name" }
                if (target.exists()) check(target.delete()) { "cannot replace ${target.absolutePath}" }
                check(temporary.renameTo(target)) { "cannot install ${target.absolutePath}" }
            } finally {
                temporary.delete()
            }
        }
        return root
    }

    private fun loadPinyin(context: Context): Map<String, String> = buildMap {
        context.assets.open("$ASSET_ROOT/pinyin.tsv").bufferedReader().useLines { lines ->
            lines.forEach { line ->
                val tab = line.indexOf('\t')
                if (tab <= 0) return@forEach
                val character = line.substring(0, tab)
                val syllable = line.substring(tab + 1).trim().lowercase()
                if (character.length == 1 && syllable.isNotEmpty() && character !in this) {
                    put(character, syllable)
                }
            }
        }
    }

    private companion object {
        const val ASSET_ROOT = "lac/v1"
        val LAC_FILES = listOf(
            "lac_encoder.onnx",
            "lac_crf_transitions.npy",
            "word.dic",
            "tag.dic",
            "q2b.dic",
        )
    }
}
