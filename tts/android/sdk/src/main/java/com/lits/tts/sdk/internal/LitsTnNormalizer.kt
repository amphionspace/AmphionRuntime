package com.lits.tts.sdk.internal

import android.util.Log
import java.io.BufferedReader
import java.io.BufferedWriter
import java.io.File
import java.io.InputStreamReader
import java.io.OutputStreamWriter
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

internal object LitsTnNormalizer {
    private val normalizersByRoot = ConcurrentHashMap<String, LayoutNormalizer>()

    fun normalize(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String,
        languageContext: String,
    ): String {
        val normalizer = normalizersByRoot.getOrPut(layout.rootDir.absolutePath) {
            LayoutNormalizer(layout)
        }
        return normalizer.normalize(text, language, languageContext)
    }

    fun shutdown(layout: LitsTtsAssetInstaller.InstalledLayout) {
        normalizersByRoot.remove(layout.rootDir.absolutePath)?.close()
        NativeTnNormalizer.clear(layout.rootDir)
    }

    private class LayoutNormalizer(private val layout: LitsTtsAssetInstaller.InstalledLayout) {
        private val processes = mutableMapOf<String, TnProcess>()
        private val disabledLanguages = mutableSetOf<String>()
        private val frontendRules = FrontendRuleSet.load(layout.frontendRules)

        @Synchronized
        fun normalize(text: String, language: String, languageContext: String): String {
            val input = prepareInputForTn(Normalizer.normalize(text, Normalizer.Form.NFKC)
                .replace(Regex("[\\x00-\\x1f\\x7f-\\x9f]"), "")
                .replace(Regex("\\s+"), " ")
                .trim())
            if (input.isEmpty() || !hasTnRules()) return text
            return if (language == "en-US" || languageContext == "en-US") {
                normalizeSegment(input, "en")
            } else {
                segmentZhEn(input).joinToString("") { (segment, lang) ->
                    preserveSegmentWhitespace(segment, normalizeSegment(segment, lang))
                }
            }
        }

        private fun prepareInputForTn(text: String): String {
            var output = hanziClockMinuteLeadingZeroRegex.replace(text) { match ->
                "${match.groupValues[1]}点零${chineseDigitTextByChar.getValue(match.groupValues[2].single())}分"
            }
            output = frontendRules.apply("pre_tn", output)
            output = protectVinCodes(output)
            output = protectProductCodes(output)
            output = serialCodeRegex.replace(output) { match ->
                match.groupValues[1] + match.groupValues[2] + normalizeSerialCode(match.groupValues[3])
            }
            return output
        }

        private fun protectVinCodes(text: String): String =
            vinCodeRegex.replace(text) { match ->
                match.groupValues[1] + normalizeSerialCode(match.groupValues[2])
            }

        private fun protectProductCodes(text: String): String =
            productCodeRegex.replace(text) { match ->
                match.groupValues[1] + normalizeSerialCode(match.groupValues[2]) + match.groupValues[3]
            }

        private fun normalizeSerialCode(code: String): String = buildString {
            code.forEach { char ->
                append(chineseDigitTextByChar[char] ?: char)
            }
        }

        private fun hasTnRules(): Boolean =
            layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_V2_ZH).isFile &&
                layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_V2_EN).isFile &&
                layout.rootDir.resolve(LitsTtsAssetRegistry.TN_RULES_V2_ZH_PINYIN).isFile

        private fun normalizeSegment(text: String, lang: String): String {
            if (text.isBlank()) return text
            if (lang in disabledLanguages) return text
            try {
                NativeTnNormalizer.normalize(layout.rootDir, lang, text)?.let { normalized ->
                    return normalized
                }
            } catch (error: Throwable) {
                logWarning("native TN normalize failed; falling back to process lang=$lang", error)
            }
            val binary = when (lang) {
                "en" -> layout.tnEnTts
                else -> layout.tnZhTts
            }
            return try {
                val process = processes.getOrPut(lang) {
                    TnProcess.start(binary, layout.rootDir)
                }
                process.normalize(text)
            } catch (error: Throwable) {
                logWarning("TN normalize failed; restarting lang=$lang binary=${binary.absolutePath}", error)
                processes.remove(lang)?.close()
                try {
                    val restarted = TnProcess.start(binary, layout.rootDir)
                    processes[lang] = restarted
                    restarted.normalize(text)
                } catch (retryError: Throwable) {
                    logError("TN normalize retry failed; disabling TN for lang=$lang", retryError)
                    processes.remove(lang)?.close()
                    disabledLanguages += lang
                    text
                }
            }
        }

        @Synchronized
        fun close() {
            processes.values.forEach { process ->
                runCatching { process.close() }
            }
            processes.clear()
            disabledLanguages.clear()
        }

        private fun segmentZhEn(text: String): List<Pair<String, String>> {
            val segments = mutableListOf<Pair<String, String>>()
            var index = 0
            while (index < text.length) {
                val char = text[index]
                if (isAsciiLetter(char)) {
                    val end = scanAsciiRun(text, index)
                    val segment = text.substring(index, end)
                    val lang = protectedAsciiRunLang(text, index, end) ?: "en"
                    segments += segment to lang
                    index = end
                } else {
                    val end = scanNonAsciiRun(text, index)
                    segments += text.substring(index, end) to "zh"
                    index = end
                }
            }
            return segments
        }

        private fun scanAsciiRun(text: String, start: Int): Int {
            var index = start
            while (index < text.length) {
                val char = text[index]
                val allowedPunctuation = char in charArrayOf('\'', '.', '_', '-')
                if (!isAsciiLetter(char) && !char.isDigit() && !allowedPunctuation) break
                index += 1
            }
            return index
        }

        private fun scanNonAsciiRun(text: String, start: Int): Int {
            var index = start
            while (index < text.length && (!isAsciiLetter(text[index]) || isAsciiCelsiusUnit(text, index))) {
                index += 1
            }
            return index
        }

        private fun isAsciiCelsiusUnit(text: String, index: Int): Boolean =
            index > 0 && text[index - 1] == '°' && (text[index] == 'C' || text[index] == 'c')

        private fun protectedAsciiRunLang(text: String, start: Int, end: Int): String? {
            val run = text.substring(start, end)
            if (isProtectedChemicalFormula(run)) return "en"
            if (isChineseContextCode(text, start, end, run)) return "zh"
            return null
        }

        private fun isProtectedChemicalFormula(run: String): Boolean =
            run == "SO2" || run == "CO2" || run == "C6H12O6"

        private fun isChineseContextCode(text: String, start: Int, end: Int, run: String): Boolean {
            val touchesChinese = (start > 0 && isCjk(text[start - 1])) || (end < text.length && isCjk(text[end]))
            if (!touchesChinese) return false
            val hasDigit = run.any { it.isDigit() }
            val upperCount = run.count { it in 'A'..'Z' }
            val hasLower = run.any { it in 'a'..'z' }
            val followsPlateProvince = start > 0 && text[start - 1] in PLATE_PROVINCES
            val isPercentileCode = run.matches(PERCENTILE_CODE)
            return hasDigit && !hasLower && (upperCount >= 1 || followsPlateProvince || isPercentileCode)
        }

        private fun isCjk(char: Char): Boolean =
            char in '\u4e00'..'\u9fff'

        private fun isAsciiLetter(char: Char): Boolean =
            char in 'a'..'z' || char in 'A'..'Z'

        companion object {
            private const val PLATE_PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼"
            private val PERCENTILE_CODE = Regex("P\\d{1,3}")
            private val hanziClockMinuteLeadingZeroRegex = Regex("([零一二三四五六七八九十两]+)点0([1-9])分")
            private val vinCodeRegex = Regex("((?:车架号\\s*)?(?:VIN\\s+))([A-HJ-NPR-Z0-9]{8,17})(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
            private val productCodeRegex = Regex("(?<![A-Za-z0-9])(vocos|Office)(\\d+)(k?)(?![A-Za-z0-9])", RegexOption.IGNORE_CASE)
            private val serialCodeRegex = Regex("((?:设备)?(?:序列号|编号)|S/N|SN)(\\s*)([A-Z0-9]*[A-Z][A-Z0-9]*\\d[A-Z0-9]*)")
            private val chineseDigitTextByChar = mapOf(
                '0' to "零",
                '1' to "一",
                '2' to "二",
                '3' to "三",
                '4' to "四",
                '5' to "五",
                '6' to "六",
                '7' to "七",
                '8' to "八",
                '9' to "九",
            )
        }
    }

    private class TnProcess private constructor(
        private val process: Process,
        private val writer: BufferedWriter,
        private val reader: BufferedReader,
    ) {
        @Synchronized
        fun normalize(text: String): String {
            if (!process.isAlive) {
                throw IllegalStateException("TN process exited before normalize")
            }
            writer.write(text)
            writer.newLine()
            writer.flush()
            val normalized = reader.readLine()
                ?: throw IllegalStateException("TN process exited without output")
            return normalized.trim().takeUnless { it.isEmpty() } ?: text
        }

        @Synchronized
        fun close() {
            runCatching { writer.close() }
            runCatching { reader.close() }
            if (process.isAlive) {
                process.destroy()
                runCatching {
                    if (!process.waitFor(200, TimeUnit.MILLISECONDS)) {
                        process.destroyForcibly()
                    }
                }
            }
        }

        companion object {
            fun start(binary: File, workingDir: File): TnProcess {
                binary.setExecutable(true, true)
                val process = ProcessBuilder(binary.absolutePath)
                    .directory(workingDir)
                    .apply {
                        environment()["TTS_RULES_ROOT"] = workingDir.absolutePath
                        environment()["TTS_RULES_FORMAT"] = "v2"
                    }
                    .start()
                Thread({
                    process.errorStream.bufferedReader().use { error ->
                        while (error.readLine() != null) {
                            // Drain stderr so the TN process cannot block on a full error pipe.
                        }
                    }
                }, "lits-tts-tn-stderr-${binary.name}").apply {
                    isDaemon = true
                    start()
                }
                return TnProcess(
                    process = process,
                    writer = BufferedWriter(OutputStreamWriter(process.outputStream, Charsets.UTF_8)),
                    reader = BufferedReader(InputStreamReader(process.inputStream, Charsets.UTF_8)),
                )
            }
        }
    }

    internal fun preserveSegmentWhitespace(segment: String, normalized: String): String {
        var output = normalized
        if (segment.firstOrNull()?.isWhitespace() == true && output.firstOrNull()?.isWhitespace() != true) {
            output = " $output"
        }
        if (segment.lastOrNull()?.isWhitespace() == true && output.lastOrNull()?.isWhitespace() != true) {
            output += " "
        }
        return output
    }

    private fun logWarning(message: String, error: Throwable) {
        try {
            Log.w(TAG, message, error)
        } catch (_: Throwable) {
            // Android Log is not mocked in local JVM tests; TN should still be testable there.
        }
    }

    private fun logError(message: String, error: Throwable) {
        try {
            Log.e(TAG, message, error)
        } catch (_: Throwable) {
            // Android Log is not mocked in local JVM tests; TN should still be testable there.
        }
    }

    private const val TAG = "LitsTn"
}
