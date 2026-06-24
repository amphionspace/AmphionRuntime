package com.lits.tts.sdk.internal

import com.lits.tts.sdk.TtsErrorCode
import java.io.BufferedInputStream
import java.io.DataInputStream
import java.io.File
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import org.json.JSONArray
import org.json.JSONObject

internal object LitsTtsFrontend {
    private val resourcesByRoot = ConcurrentHashMap<String, FrontendResources>()
    private val pinyinSyllableRegex = Regex("^[a-z]+[0-6]$")
    private val hanziRegex = Regex("[\\u4e00-\\u9fff]")
    private val punctuation = setOf(',', '.', '!', '?', ';', ':', '\'', '"', '(', ')', '[', ']', '<', '>', '-')
    private val fullwidthPunctuation = mapOf(
        '\uFF0C' to ",",
        '\u3002' to ".",
        '\uFF01' to "!",
        '\uFF1F' to "?",
        '\uFF1B' to ";",
        '\uFF1A' to ":",
        '\u3001' to ",",
        '\u2018' to "'",
        '\u2019' to "'",
        '\u201C' to "\"",
        '\u201D' to "\"",
        '\u3010' to "[",
        '\u3011' to "]",
        '\uFF08' to "(",
        '\uFF09' to ")",
        '\u300A' to "<",
        '\u300B' to ">",
        '\u2014' to "-",
        '\u2013' to "-",
        '\u22EF' to "\u2026",
        '\u00B7' to ".",
    )
    private val englishDigitWordByChar = mapOf(
        '0' to "ZERO",
        '1' to "ONE",
        '2' to "TWO",
        '3' to "THREE",
        '4' to "FOUR",
        '5' to "FIVE",
        '6' to "SIX",
        '7' to "SEVEN",
        '8' to "EIGHT",
        '9' to "NINE",
    )
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
    private val englishMergeRules = listOf(
        listOf("t", "\u0279") to "t\u0279",
        listOf("d", "\u0279") to "d\u0279",
        listOf("t", "s") to "ts",
        listOf("d", "z") to "dz",
        listOf("\u026A", "\u0279") to "\u026A\u0279",
        listOf("o\u02D0", "\u0279") to "o\u02D0\u0279",
    )

    fun encode(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        language: String,
        languageContext: String,
    ): LongArray {
        val resources = resources(layout)
        val rawTokens = tokenize(resources, text, language, languageContext)
        val ids = rawTokens.map { token ->
            resources.symbolToId[token] ?: throw unsupported("frontend token is not in zh_en_symbols.json: $token")
        }
        return intersperseZero(ids)
    }

    fun preload(layout: LitsTtsAssetInstaller.InstalledLayout) {
        resources(layout)
    }

    fun splitForStreaming(
        layout: LitsTtsAssetInstaller.InstalledLayout,
        text: String,
        wordsPerSegment: Int = 7,
    ): List<String> {
        val resources = resources(layout)
        val normalized = normalizeText(text).trim()
        if (normalized.isEmpty()) return emptyList()
        val segments = mutableListOf<String>()
        val current = StringBuilder()
        var words = 0
        var index = 0
        fun flushCurrentSegment() {
            flushSegment(segments, current)
            words = 0
        }
        fun appendWord(word: String, nextIndex: Int) {
            current.append(word)
            words += 1
            if (words >= wordsPerSegment && !nextNonSpaceIsPunctuation(normalized, nextIndex)) {
                flushCurrentSegment()
            }
        }
        while (index < normalized.length) {
            val char = normalized[index]
            when {
                char.isWhitespace() -> {
                    if (current.isNotEmpty() && current.last() != ' ') current.append(' ')
                    index += 1
                }

                isPunctuationChar(char) -> {
                    current.trimTrailingSpace()
                    current.append(char)
                    if (words >= wordsPerSegment) {
                        flushCurrentSegment()
                    }
                    index += 1
                }

                char.isDigit() -> {
                    val end = scanDigits(normalized, index)
                    appendWord(normalized.substring(index, end), end)
                    index = end
                }

                isHanzi(char) -> {
                    val end = scanHanziChunk(normalized, index)
                    val hanziChunk = normalized.substring(index, end)
                    var chunkIndex = 0
                    while (chunkIndex < hanziChunk.length) {
                        val word = longestWord(resources, hanziChunk, chunkIndex)
                        appendWord(word, index + chunkIndex + word.length)
                        chunkIndex += word.length
                    }
                    index = end
                }

                isEnglishLetter(char) -> {
                    val end = scanEnglishWord(normalized, index)
                    appendWord(normalized.substring(index, end), end)
                    index = end
                }

                else -> {
                    current.append(char)
                    index += 1
                }
            }
        }
        flushSegment(segments, current)
        return segments.ifEmpty { listOf(normalized) }
    }

    private fun tokenize(
        resources: FrontendResources,
        text: String,
        language: String,
        languageContext: String,
    ): List<String> {
        val normalized = normalizeText(text).trim()
        if (normalized.isEmpty()) {
            throw unsupported("text must not be empty after trim")
        }
        if (language == "en-US" && normalized.any(::isHanzi)) {
            throw unsupported("en-US mode does not support Chinese input")
        }
        val output = mutableListOf<String>()
        var index = 0
        while (index < normalized.length) {
            val char = normalized[index]
            when {
                char.isWhitespace() -> {
                    appendBoundary(output)
                    index += 1
                }

                isPunctuationChar(char) -> {
                    appendPunctuation(output, char.toString())
                    index += 1
                }

                char.isDigit() -> {
                    val end = scanDigits(normalized, index)
                    val digits = normalized.substring(index, end)
                    if (languageContext == "zh-en") {
                        appendChineseSyllables(
                            output,
                            resources,
                            applyThirdToneSandhi(
                                hanziChunkToPinyin(
                                    resources,
                                    digits.map { chineseDigitTextByChar.getValue(it) }.joinToString(""),
                                ),
                            ),
                        )
                    } else {
                        digits.forEach { digit ->
                            appendBoundary(output)
                            val phones = resources.cmudict[englishDigitWordByChar.getValue(digit)]
                                ?: throw unsupported("english digit is not covered by cmudict.txt: $digit")
                            output += arpabetToTokens(resources, phones)
                        }
                        appendBoundary(output)
                    }
                    index = end
                }

                isHanzi(char) -> {
                    val end = scanHanziChunk(normalized, index)
                    appendChineseSyllables(
                        output,
                        resources,
                        applyThirdToneSandhi(
                            hanziChunkToPinyin(resources, normalized.substring(index, end)),
                        ),
                    )
                    index = end
                }

                char.isLowerCase() -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end > index && end < normalized.length && normalized[end].isDigit()) {
                        val candidate = normalized.substring(index, end + 1)
                        val tokens = resources.pinyinToTokens[candidate]
                        if (tokens != null) {
                            while (output.lastOrNull() == "_") {
                                output.removeAt(output.lastIndex)
                            }
                            output += tokens
                            index = end + 1
                            continue
                        }
                    }
                    val actualEnd = if (end > index) end else throw unsupported("unsupported frontend character: $char")
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(resources, normalized.substring(index, actualEnd))
                    output += arpabetToTokens(resources, phones)
                    appendBoundary(output)
                    index = actualEnd
                }

                isEnglishLetter(char) -> {
                    val end = scanEnglishWord(normalized, index)
                    if (end <= index) throw unsupported("unsupported frontend character: $char")
                    appendBoundary(output)
                    val phones = phonesForEnglishWord(resources, normalized.substring(index, end))
                    output += arpabetToTokens(resources, phones)
                    appendBoundary(output)
                    index = end
                }

                else -> throw unsupported("unsupported frontend character: $char")
            }
        }
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        return output
    }

    private fun normalizeText(text: String): String {
        var normalized = text.replace("...", "\u2026")
            .replace("\u22EF", "\u2026")
            .replace("\u00B7\u00B7\u00B7", "\u2026")
            .replace("\u30FB\u30FB\u30FB", "\u2026")
        normalized = Normalizer.normalize(normalized, Normalizer.Form.NFKC)
        normalized = normalized.replace("...", "\u2026")
            .replace("\u22EF", "\u2026")
            .replace("\u00B7\u00B7\u00B7", "\u2026")
            .replace("\u30FB\u30FB\u30FB", "\u2026")
        val output = StringBuilder(normalized.length)
        for (char in normalized) {
            output.append(fullwidthPunctuation[char] ?: char)
        }
        return output.toString()
    }

    private fun flushSegment(segments: MutableList<String>, current: StringBuilder) {
        current.trimTrailingSpace()
        val segment = current.toString().trim()
        if (segment.isNotEmpty()) {
            segments += segment
        }
        current.clear()
    }

    private fun StringBuilder.trimTrailingSpace() {
        while (isNotEmpty() && last().isWhitespace()) {
            deleteCharAt(lastIndex)
        }
    }

    private fun nextNonSpaceIsPunctuation(text: String, start: Int): Boolean {
        var index = start
        while (index < text.length && text[index].isWhitespace()) {
            index += 1
        }
        return index < text.length && isPunctuationChar(text[index])
    }

    private fun hanziChunkToPinyin(resources: FrontendResources, text: String): List<String> {
        val output = mutableListOf<String>()
        var index = 0
        while (index < text.length) {
            val word = longestWord(resources, text, index)
            output += lexiconPinyinForWord(resources, word)
            index += word.length
        }
        return output
    }

    private fun longestWord(resources: FrontendResources, text: String, start: Int): String {
        val maxLength = minOf(resources.maxWordLength, text.length - start)
        for (length in maxLength downTo 2) {
            val candidate = text.substring(start, start + length)
            if (resources.wordPinyin.containsKey(candidate)) {
                return candidate
            }
        }
        return text[start].toString()
    }

    private fun lexiconPinyinForWord(resources: FrontendResources, word: String): List<String> {
        val direct = resources.wordPinyin[word]
        if (direct != null && word !in resources.polyphonicWords) {
            val syllables = normalizeLexiconPinyin(direct)
            if (syllables.isNotEmpty()) return syllables
        }
        val output = mutableListOf<String>()
        for (char in word) {
            val pinyin = resources.wordPinyin[char.toString()]
                ?: throw unsupported("hanzi is not covered by chinese_lexicon.txt: $char")
            val syllables = normalizeLexiconPinyin(pinyin)
            if (syllables.isEmpty()) {
                throw unsupported("hanzi pinyin is invalid in chinese_lexicon.txt: $char")
            }
            output += syllables
        }
        return output
    }

    private fun normalizeLexiconPinyin(text: String): List<String> = text
        .trim()
        .split(Regex("\\s+"))
        .map { it.replace('\u7709', 'v').replace('\u813A', 'v') }
        .filter { pinyinSyllableRegex.matches(it) }

    private fun applyThirdToneSandhi(tokens: List<String>): List<String> {
        val output = tokens.toMutableList()
        val pinyinIndices = output.indices.filter { pinyinSyllableRegex.matches(output[it]) }
        for (position in 0 until pinyinIndices.lastIndex) {
            val current = pinyinIndices[position]
            val next = pinyinIndices[position + 1]
            if (output[current].last() == '3' && output[next].last() == '3') {
                output[current] = output[current].dropLast(1) + "2"
            }
        }
        return output
    }

    private fun phonesForEnglishWord(resources: FrontendResources, rawWord: String): List<String> {
        val normalized = rawWord.uppercase()
        resources.cmudict[normalized]?.let { return it }
        if ('-' in normalized) {
            val output = mutableListOf<String>()
            for (part in normalized.split('-')) {
                if (part.isEmpty()) continue
                val phones = resources.cmudict[part] ?: spellEnglishWord(resources, part)
                if (phones.isEmpty()) {
                    throw unsupported("english word is not covered by cmudict.txt: $rawWord")
                }
                output += phones
            }
            if (output.isNotEmpty()) return output
        }
        val spelled = spellEnglishWord(resources, normalized)
        if (spelled.isNotEmpty()) return spelled
        throw unsupported("english word is not covered by cmudict.txt: $rawWord")
    }

    private fun spellEnglishWord(resources: FrontendResources, word: String): List<String> {
        val output = mutableListOf<String>()
        for (char in word) {
            if (!isEnglishLetter(char)) continue
            val phones = resources.cmudict[char.toString()] ?: return emptyList()
            output += phones
        }
        return output
    }

    private fun arpabetToTokens(resources: FrontendResources, phones: List<String>): List<String> {
        val rawTokens = buildList {
            for (phone in phones) {
                val tokens = resources.arpabetToTokens[phone]
                    ?: throw unsupported("ARPAbet phone is not supported by Android frontend: $phone")
                addAll(tokens)
            }
        }
        return mergeEnglishTokens(rawTokens)
    }

    private fun mergeEnglishTokens(tokens: List<String>): List<String> {
        val output = mutableListOf<String>()
        var index = 0
        while (index < tokens.size) {
            var merged = false
            for ((pair, replacement) in englishMergeRules) {
                if (tokens.subList(index, minOf(index + pair.size, tokens.size)) == pair) {
                    output += replacement
                    index += pair.size
                    merged = true
                    break
                }
            }
            if (!merged) {
                output += tokens[index]
                index += 1
            }
        }
        return output
    }

    private fun appendBoundary(output: MutableList<String>) {
        if (output.isNotEmpty() && output.last() != "_") {
            output += "_"
        }
    }

    private fun appendPunctuation(output: MutableList<String>, token: String) {
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        output += token
    }

    private fun appendChineseSyllables(
        output: MutableList<String>,
        resources: FrontendResources,
        syllables: List<String>,
    ) {
        while (output.lastOrNull() == "_") {
            output.removeAt(output.lastIndex)
        }
        syllables.forEach { syllable ->
            output += resources.pinyinToTokens[syllable]
                ?: throw unsupported("pinyin is not covered by generated mapping: $syllable")
        }
    }

    private fun intersperseZero(ids: List<Int>): LongArray {
        val output = LongArray(ids.size * 2 + 1)
        output[0] = 0L
        for (index in ids.indices) {
            output[index * 2 + 1] = ids[index].toLong()
            output[index * 2 + 2] = 0L
        }
        return output
    }

    private fun scanDigits(text: String, start: Int): Int {
        var index = start
        while (index < text.length && text[index].isDigit()) {
            index += 1
        }
        return index
    }

    private fun scanHanziChunk(text: String, start: Int): Int {
        var index = start
        while (index < text.length && isHanzi(text[index])) {
            index += 1
        }
        return index
    }

    private fun scanEnglishWord(text: String, start: Int): Int {
        var index = start
        while (index < text.length && isEnglishLetter(text[index])) {
            index += 1
        }
        while (index + 1 < text.length && (text[index] == '\'' || text[index] == '-') && isEnglishLetter(text[index + 1])) {
            index += 1
            while (index < text.length && isEnglishLetter(text[index])) {
                index += 1
            }
        }
        return index
    }

    private fun isHanzi(char: Char): Boolean = hanziRegex.matches(char.toString())

    private fun isEnglishLetter(char: Char): Boolean = char in 'a'..'z' || char in 'A'..'Z'

    private fun isPunctuationChar(char: Char): Boolean = char == '\u2026' || char in punctuation

    private fun resources(layout: LitsTtsAssetInstaller.InstalledLayout): FrontendResources =
        resourcesByRoot.getOrPut(layout.rootDir.absolutePath) {
            val wordPinyin = loadWordPinyin(layout)
            val executor = Executors.newFixedThreadPool(FRONTEND_LOAD_THREADS) { runnable ->
                Thread(runnable, "lits-tts-frontend-load").apply { isDaemon = true }
            }
            try {
                val polyphonicWords = executor.submit(Callable {
                    layout.polychar.readLines(Charsets.UTF_8)
                        .map { it.trim() }
                        .filter { it.isNotEmpty() }
                        .toSet()
                })
                val cmudict = executor.submit(Callable { loadCmudict(layout) })
                val symbolToId = executor.submit(Callable { loadSymbols(layout) })
                val pinyinToTokens = executor.submit(Callable { loadTokenMap(layout.pinyinToTokens, "pinyin_to_tokens") })
                val arpabetToTokens = executor.submit(Callable { loadTokenMap(layout.arpabetToTokens, "arpabet_to_tokens") })
                FrontendResources(
                    wordPinyin = wordPinyin,
                    polyphonicWords = polyphonicWords.get(),
                    maxWordLength = wordPinyin.keys.maxOfOrNull { it.length } ?: 1,
                    cmudict = cmudict.get(),
                    symbolToId = symbolToId.get(),
                    pinyinToTokens = pinyinToTokens.get(),
                    arpabetToTokens = arpabetToTokens.get(),
                )
            } finally {
                executor.shutdown()
            }
        }

    private fun loadWordPinyin(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> =
        if (layout.chineseLexiconBin.isFile) {
            try {
                loadWordPinyinBin(layout.chineseLexiconBin)
            } catch (exception: Exception) {
                loadWordPinyinText(layout)
            }
        } else {
            loadWordPinyinText(layout)
        }

    private fun loadWordPinyinText(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, String> =
        buildMap {
            layout.chineseLexicon.forEachLine(Charsets.UTF_8) { line ->
                val parts = line.trim().split('\t')
                if (parts.size == 2) {
                    put(parts[0], parts[1])
                }
            }
        }

    private fun loadCmudict(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, List<String>> =
        if (layout.cmudictBin.isFile) {
            try {
                loadCmudictBin(layout.cmudictBin)
            } catch (exception: Exception) {
                loadCmudictText(layout)
            }
        } else {
            loadCmudictText(layout)
        }

    private fun loadCmudictText(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, List<String>> =
        buildMap {
            layout.cmudict.forEachLine(Charsets.UTF_8) { line ->
                val trimmed = line.trim()
                if (trimmed.isEmpty()) return@forEachLine
                val parts = trimmed.split('\t', limit = 2)
                if (parts.size != 2) return@forEachLine
                val key = parts[0].substringBefore('(').uppercase()
                if (containsKey(key)) return@forEachLine
                val phones = parts[1].trim().split(Regex("\\s+")).filter { it.isNotEmpty() }
                if (phones.isNotEmpty()) {
                    put(key, phones)
                }
            }
        }

    private fun loadWordPinyinBin(file: File): Map<String, String> =
        DataInputStream(BufferedInputStream(file.inputStream())).use { input ->
            require(input.readInt() == WORD_PINYIN_BIN_MAGIC) { "invalid chinese lexicon bin magic" }
            val count = input.readInt()
            buildMap(count) {
                repeat(count) {
                    put(input.readUtf8String(), input.readUtf8String())
                }
            }
        }

    private fun loadCmudictBin(file: File): Map<String, List<String>> =
        DataInputStream(BufferedInputStream(file.inputStream())).use { input ->
            require(input.readInt() == CMUDICT_BIN_MAGIC) { "invalid cmudict bin magic" }
            val count = input.readInt()
            buildMap(count) {
                repeat(count) {
                    val key = input.readUtf8String()
                    val phones = List(input.readInt()) { input.readUtf8String() }
                    put(key, phones)
                }
            }
        }

    private fun DataInputStream.readUtf8String(): String {
        val length = readInt()
        require(length >= 0) { "negative string length" }
        val bytes = ByteArray(length)
        readFully(bytes)
        return bytes.toString(Charsets.UTF_8)
    }

    private fun loadSymbols(layout: LitsTtsAssetInstaller.InstalledLayout): Map<String, Int> {
        val symbols = JSONObject(layout.symbols.readText(Charsets.UTF_8)).getJSONArray("symbols")
        return buildMap {
            for (index in 0 until symbols.length()) {
                put(symbols.getString(index), index)
            }
        }
    }

    private fun loadTokenMap(file: java.io.File, key: String): Map<String, List<String>> {
        val root = JSONObject(file.readText(Charsets.UTF_8))
        val payload = root.getJSONObject(key)
        return buildMap {
            val iterator = payload.keys()
            while (iterator.hasNext()) {
                val name = iterator.next()
                val values = payload.getJSONArray(name)
                put(name, values.toStringList())
            }
        }
    }

    private fun JSONArray.toStringList(): List<String> = buildList {
        for (index in 0 until length()) {
            add(getString(index))
        }
    }

    private fun unsupported(message: String): IllegalStateException =
        IllegalStateException("${TtsErrorCode.RUNTIME_EXCEPTION}:$message")

    private data class FrontendResources(
        val wordPinyin: Map<String, String>,
        val polyphonicWords: Set<String>,
        val maxWordLength: Int,
        val cmudict: Map<String, List<String>>,
        val symbolToId: Map<String, Int>,
        val pinyinToTokens: Map<String, List<String>>,
        val arpabetToTokens: Map<String, List<String>>,
    )

    private const val FRONTEND_LOAD_THREADS = 4
    private const val WORD_PINYIN_BIN_MAGIC = 0x4C505931
    private const val CMUDICT_BIN_MAGIC = 0x434D4431
}
