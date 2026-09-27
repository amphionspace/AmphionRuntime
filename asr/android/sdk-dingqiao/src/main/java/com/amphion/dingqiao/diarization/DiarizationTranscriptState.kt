package com.amphion.dingqiao.diarization

import kotlin.math.max
import kotlin.math.min

internal data class SpeakerTimelineTurn(
    val beginTime: Int,
    val endTime: Int,
    var speakerId: String,
    var secondarySpeakerIds: List<String>,
    var confidence: Float = 0f,
    val overlap: Boolean = false,
    val evidenceKey: String? = null,
    val secondaryEvidenceKeys: List<String> = emptyList(),
    // Keep one ID per acoustic channel, independently of deduplicated display IDs.
    var secondaryEvidenceSpeakerIds: List<String> = secondarySpeakerIds,
)

internal data class DiarizationTranscriptUpdate(
    val utteranceId: String,
    val revision: Int,
    val speakerId: String,
    val secondarySpeakerIds: List<String>,
    val beginTime: Int,
    val endTime: Int,
    val confidence: Float,
)

internal data class DiarizedTranscriptUtterance(
    val utteranceId: String,
    val rawText: String,
    val text: String,
    val beginTime: Int,
    val endTime: Int,
    val speakerId: String,
    val secondarySpeakerIds: List<String>,
    val confidence: Float,
    val overlap: Boolean,
    val sourceUtteranceId: String = utteranceId,
    val speakerInferred: Boolean = false,
)

private data class StoredUtterance(
    val audioEndTime: Int,
    val utteranceId: String,
    val rawText: String,
    val text: String,
    val tokens: List<String>,
    val tokenTimesMs: List<Int>,
    val beginTime: Int,
    val endTime: Int,
    var revision: Int,
    var speakerId: String,
    var secondarySpeakerIds: List<String>,
)

internal class DiarizationTranscriptState {
    private val utterances = mutableListOf<StoredUtterance>()
    private var nextUtteranceId = 1
    private val turns = mutableListOf<SpeakerTimelineTurn>()

    fun addUtterance(
        rawText: String,
        text: String,
        tokens: List<String>,
        tokenTimesMs: List<Int>,
        beginTime: Int,
        endTime: Int,
        audioEndTime: Int = endTime,
    ): String {
        val id = "u${nextUtteranceId++}"
        val decoded = decodedTranscriptTokens(rawText, tokens, tokenTimesMs)
        val assignment = assignmentFor(beginTime, endTime)
        utterances += StoredUtterance(
            audioEndTime, id, rawText, text, decoded?.first ?: tokens.toList(),
            decoded?.second ?: tokenTimesMs.toList(), beginTime, endTime,
            0, assignment.speakerId, assignment.secondarySpeakerIds,
        )
        return id
    }

    fun currentAssignment(utteranceId: String): DiarizationTranscriptUpdate? {
        val utterance = utterances.find { it.utteranceId == utteranceId } ?: return null
        val assignment = assignmentFor(utterance.beginTime, utterance.endTime)
        return updateFor(utterance, assignment.confidence)
    }

    fun applySpeakerTurns(newTurns: List<SpeakerTimelineTurn>, replace: Boolean = false): List<DiarizationTranscriptUpdate> {
        if (replace) turns.clear()
        if (newTurns.isEmpty() && !replace) return emptyList()
        turns += newTurns.map { it.copy(
            secondarySpeakerIds = it.secondaryEvidenceSpeakerIds.filter { id -> id != it.speakerId }.distinct(),
            secondaryEvidenceKeys = it.secondaryEvidenceKeys.toList(),
            secondaryEvidenceSpeakerIds = it.secondaryEvidenceSpeakerIds.toList()) }
        return refreshUtterances { utterance ->
            replace || newTurns.any { overlapMs(utterance.beginTime, utterance.endTime, it.beginTime, it.endTime) > 0 }
        }
    }

    fun resolveUnknownSpan(evidenceKey: String, beginTime: Int, endTime: Int, speakerId: String,
        confidence: Float, remap: Map<String, String>) {
        if (endTime <= beginTime) return
        val revised = turns.flatMap { turn ->
            if (turn.evidenceKey != evidenceKey || (remap[evidenceKey] ?: turn.speakerId) != "UNKNOWN" ||
                turn.overlap || turn.secondaryEvidenceSpeakerIds.isNotEmpty() ||
                overlapMs(beginTime, endTime, turn.beginTime, turn.endTime) <= 0) listOf(turn)
            else {
                val start = maxOf(beginTime, turn.beginTime)
                val end = minOf(endTime, turn.endTime)
                buildList {
                    if (turn.beginTime < start) add(turn.copy(endTime = start))
                    add(turn.copy(beginTime = start, endTime = end, speakerId = speakerId, confidence = confidence, evidenceKey = null))
                    if (end < turn.endTime) add(turn.copy(beginTime = end))
                }
            }
        }
        turns.clear()
        turns.addAll(revised)
    }

    // Only called for evidence available before this unpublished window commits.
    fun refineSingleSpeakerSpan(beginTime: Int, cutTime: Int, endTime: Int,
        leftId: String, rightId: String, leftConfidence: Float, rightConfidence: Float,
        remap: Map<String, String>) {
        if (cutTime <= beginTime || cutTime >= endTime || leftId == rightId) return
        val covered = turns.filter { overlapMs(beginTime, endTime, it.beginTime, it.endTime) > 0 }
        val ids = covered.map { remap[it.evidenceKey] ?: it.speakerId }.toSet()
        if (ids.size != 1 || (leftId !in ids && rightId !in ids) || "UNKNOWN" in ids ||
            covered.any { it.overlap || it.secondaryEvidenceSpeakerIds.isNotEmpty() }) return
        val revised = turns.flatMap { turn ->
            val cuts = (listOf(turn.beginTime, turn.endTime) + listOf(beginTime, cutTime, endTime)
                .filter { it > turn.beginTime && it < turn.endTime }).sorted()
            cuts.zipWithNext { start, end ->
                if (start >= beginTime && end <= endTime) turn.copy(beginTime = start, endTime = end,
                    speakerId = if (start < cutTime) leftId else rightId,
                    confidence = if (start < cutTime) leftConfidence else rightConfidence,
                    evidenceKey = null)
                else turn.copy(beginTime = start, endTime = end)
            }
        }
        turns.clear()
        turns.addAll(revised)
    }

    fun applyEvidenceRemap(remap: Map<String, String>, fromTime: Int = 0,
        confidences: Map<String, Float> = emptyMap()): List<DiarizationTranscriptUpdate> {
        turns.filter { it.endTime >= fromTime }.forEach { turn ->
            turn.evidenceKey?.let {
                turn.speakerId = remap[it] ?: turn.speakerId
                turn.confidence = confidences[it] ?: turn.confidence
            }
            turn.secondaryEvidenceSpeakerIds = turn.secondaryEvidenceSpeakerIds.mapIndexed { index, speakerId ->
                remap[turn.secondaryEvidenceKeys.getOrNull(index)] ?: speakerId
            }
            turn.secondarySpeakerIds = turn.secondaryEvidenceSpeakerIds.filter { it != turn.speakerId }.distinct()
        }
        return refreshUtterances { it.endTime >= fromTime }
    }

    fun applySpeakerRemap(remap: Map<String, String>, fromTime: Int = 0): List<DiarizationTranscriptUpdate> {
        turns.filter { it.endTime >= fromTime }.forEach { turn ->
            turn.speakerId = remap[turn.speakerId] ?: turn.speakerId
            turn.secondaryEvidenceSpeakerIds = turn.secondaryEvidenceSpeakerIds.map { remap[it] ?: it }
            turn.secondarySpeakerIds = turn.secondaryEvidenceSpeakerIds.filter { it != turn.speakerId }.distinct()
        }
        return refreshUtterances { it.endTime >= fromTime }
    }

    // Internal alignment evidence for bounded UNKNOWN backfill, never public pieces.
    fun finalUtterances(throughTime: Int = Int.MAX_VALUE): List<DiarizedTranscriptUtterance> = utterances.filter { it.audioEndTime <= throughTime }.flatMap { utterance ->
        val boundaries = if (utterance.tokens.isNotEmpty() &&
            utterance.tokens.size == utterance.tokenTimesMs.size
        ) tokenTextBoundaries(utterance.tokens, utterance.text) else null
        if (boundaries == null) {
            listOf(unsplit(utterance))
        } else {
            val split = splitByTokenSpeaker(utterance, boundaries)
            if (split.joinToString("") { it.text } == utterance.text) split else listOf(unsplit(utterance))
        }
    }

    private data class TranscriptCut(val tokenIndex: Int, val textOffset: Int)

    private fun unambiguousPunctuationCuts(tokens: List<String>, text: String): List<TranscriptCut> {
        val inserted = " ,.!?，。！？、;；:：\t\r\n"
        val raw = tokens.joinToString("").codePoints().toArray()
        val plain = mutableListOf<Int>()
        val offsets = mutableListOf<Int>()
        var offset = 0
        text.codePoints().toArray().forEach { character ->
            if (character > 65535 || character.toChar() !in inserted) { plain += character; offsets += offset }
            offset += Character.charCount(character)
        }
        val fallback = listOf(TranscriptCut(0, 0), TranscriptCut(tokens.size, text.length))
        val width = plain.size + 1
        val cells = (raw.size.toLong() + 1) * width
        if (raw.isEmpty() || plain.isEmpty() || cells > 1_048_576 ||
            raw.any { it <= 65535 && it.toChar() in inserted }) return fallback
        val forward = IntArray(cells.toInt())
        val backward = IntArray(cells.toInt())
        for (i in 0..raw.size) forward[i * width] = i
        for (j in 0..plain.size) forward[j] = j
        for (i in 1..raw.size) for (j in 1..plain.size) forward[i * width + j] = minOf(
            forward[(i - 1) * width + j] + 1, forward[i * width + j - 1] + 1,
            forward[(i - 1) * width + j - 1] + if (raw[i - 1] == plain[j - 1]) 0 else 1)
        for (i in 0..raw.size) backward[i * width + plain.size] = raw.size - i
        for (j in 0..plain.size) backward[raw.size * width + j] = plain.size - j
        for (i in raw.lastIndex downTo 0) for (j in plain.lastIndex downTo 0) backward[i * width + j] = minOf(
            backward[(i + 1) * width + j] + 1, backward[i * width + j + 1] + 1,
            backward[(i + 1) * width + j + 1] + if (raw[i] == plain[j]) 0 else 1)
        val cost = forward.last()
        val owners = IntArray(plain.size) { j ->
            var owner = -1; var ambiguous = false
            for (i in 0..raw.size) {
                val prefix = forward[i * width + j]
                if (prefix + 1 + backward[i * width + j + 1] == cost) ambiguous = true
                if (i == raw.size) continue
                val exact = raw[i] == plain[j]
                if (prefix + (if (exact) 0 else 1) + backward[(i + 1) * width + j + 1] == cost) {
                    if (!exact || (owner >= 0 && owner != i)) ambiguous = true
                    owner = i
                }
            }
            if (ambiguous) -1 else owner
        }
        val tokenAt = mutableMapOf<Int, Int>()
        var characters = 0
        tokens.forEachIndexed { index, token -> tokenAt[characters] = index; characters += token.codePointCount(0, token.length) }
        val cuts = mutableListOf(fallback.first())
        for (j in 1 until plain.size) {
            val gap = text.substring(offsets[j - 1] + Character.charCount(plain[j - 1]), offsets[j])
            val tokenIndex = tokenAt[owners[j]]
            if (gap.any { it in "，。！？；" } && owners[j - 1] >= 0 && owners[j] == owners[j - 1] + 1 &&
                tokenIndex != null && tokenIndex > 0) cuts += TranscriptCut(tokenIndex, offsets[j])
        }
        return cuts + fallback.last()
    }

    private fun punctuationUnits(utterance: StoredUtterance): List<StoredUtterance> {
        if (utterance.tokens.isEmpty() || utterance.tokens.size != utterance.tokenTimesMs.size ||
            utterance.tokens.joinToString("") != utterance.rawText) return listOf(utterance)
        val boundaries = tokenTextBoundaries(utterance.tokens, utterance.text)
        val cuts = if (boundaries == null) unambiguousPunctuationCuts(utterance.tokens, utterance.text) else {
            val values = mutableListOf(TranscriptCut(0, 0))
            for (index in 1 until utterance.tokens.size) {
                val text = utterance.text.substring(boundaries[index - 1], boundaries[index]).trimEnd()
                if (text.lastOrNull()?.let { it in "，。！？；" } == true && boundaries[index] < utterance.text.length)
                    values += TranscriptCut(index, boundaries[index])
            }
            values + TranscriptCut(utterance.tokens.size, utterance.text.length)
        }
        if (cuts.size == 2) return listOf(utterance)
        return cuts.zipWithNext().mapIndexed { index, (cut, next) ->
            val start = cut.tokenIndex; val end = next.tokenIndex
            utterance.copy(utteranceId = if (index == 0) utterance.utteranceId else "${utterance.utteranceId}.${index + 1}",
                text = utterance.text.substring(cut.textOffset, next.textOffset),
                rawText = utterance.tokens.subList(start, end).joinToString(""),
                tokens = utterance.tokens.subList(start, end), tokenTimesMs = utterance.tokenTimesMs.subList(start, end),
                beginTime = if (start == 0) utterance.beginTime else utterance.tokenTimesMs[start],
                endTime = if (end == utterance.tokens.size) utterance.endTime else utterance.tokenTimesMs[end])
        }
    }

    fun sentenceUtterances(throughTime: Int = Int.MAX_VALUE): List<DiarizedTranscriptUtterance> {
        val result = mutableListOf<DiarizedTranscriptUtterance>()
        for (original in utterances.filter { it.audioEndTime <= throughTime }) {
            for (utterance in punctuationUnits(original)) {
                val boundaries = if (utterance.tokens.isNotEmpty() && utterance.tokens.size == utterance.tokenTimesMs.size)
                    tokenTextBoundaries(utterance.tokens, utterance.text) else null
                val parts = if (boundaries == null) listOf(unsplit(utterance)) else splitByTokenSpeaker(utterance, boundaries)
                val covered = turns.filter { overlapMs(utterance.beginTime, utterance.endTime, it.beginTime, it.endTime) > 0 }
                val participants = covered.flatMap { listOf(it.speakerId) + it.secondarySpeakerIds }.toSortedSet()
                val known = participants.filter { it != "UNKNOWN" && it != "UNKNOWN_SECONDARY" }
                val overlap = covered.any { it.overlap || it.secondarySpeakerIds.isNotEmpty() }
                val unknown = turns.filter { it.speakerId == "UNKNOWN" &&
                    overlapMs(original.beginTime, original.endTime, it.beginTime, it.endTime) > 0 }.sortedBy { it.beginTime }
                var unknownBegin = -1; var unknownEnd = -1; var bounded = true
                for (turn in unknown) {
                    val begin = maxOf(original.beginTime, turn.beginTime); val end = minOf(original.endTime, turn.endTime)
                    if (begin > unknownEnd) unknownBegin = begin
                    unknownEnd = maxOf(unknownEnd, end)
                    if (unknownEnd - unknownBegin > 2500 &&
                        overlapMs(utterance.beginTime, utterance.endTime, unknownBegin, unknownEnd) > 0) bounded = false
                }
                val single = known.size == 1 && !overlap && bounded && parts.isNotEmpty() && parts.all { it.speakerId == known.single() }
                val inferred = single && (covered.any { it.speakerId == "UNKNOWN" } || parts.any { it.speakerInferred })
                val part = DiarizedTranscriptUtterance(utterance.utteranceId, utterance.rawText, utterance.text,
                    utterance.beginTime, utterance.endTime, if (single) known.single() else "UNKNOWN",
                    if (single) emptyList() else participants.toList(),
                    if (single && !inferred) parts.minOf { it.confidence } else 0f, overlap, original.utteranceId, inferred)
                val previous = result.lastOrNull()
                if (previous != null && previous.sourceUtteranceId == part.sourceUtteranceId &&
                    previous.endTime == part.beginTime && previous.speakerId == part.speakerId &&
                    previous.overlap == part.overlap && previous.secondarySpeakerIds == part.secondarySpeakerIds) {
                    result[result.lastIndex] = previous.copy(text = previous.text + part.text,
                        rawText = previous.rawText + part.rawText, endTime = part.endTime,
                        confidence = minOf(previous.confidence, part.confidence),
                        speakerInferred = previous.speakerInferred || part.speakerInferred)
                } else result += part
            }
        }
        return result
    }

    fun commitThrough(endTime: Int): List<DiarizedTranscriptUtterance> {
        val result = sentenceUtterances(endTime)
        utterances.removeAll { it.audioEndTime <= endTime }
        val retainFrom = minOf(endTime, utterances.minOfOrNull { it.beginTime } ?: endTime)
        val retained = turns.filter { it.endTime > retainFrom }.map {
            it.copy(beginTime = maxOf(it.beginTime, retainFrom))
        }
        turns.clear()
        turns.addAll(retained)
        return result
    }

    fun allTurns(): List<SpeakerTimelineTurn> = turns.map {
        it.copy(secondarySpeakerIds = it.secondarySpeakerIds.toList(),
            secondaryEvidenceKeys = it.secondaryEvidenceKeys.toList(),
            secondaryEvidenceSpeakerIds = it.secondaryEvidenceSpeakerIds.toList())
    }

    private data class Assignment(
        val speakerId: String,
        val secondarySpeakerIds: List<String>,
        val confidence: Float,
    )

    private fun assignmentFor(beginTime: Int, endTime: Int): Assignment {
        val participants = sortedSetOf<String>()
        var overlap = false
        var confidence = 1f
        turns.forEach { turn ->
            val duration = overlapMs(beginTime, endTime, turn.beginTime, turn.endTime)
            if (duration <= 0) return@forEach
            participants += turn.speakerId
            participants += turn.secondarySpeakerIds
            overlap = overlap || turn.overlap || turn.secondarySpeakerIds.isNotEmpty()
            confidence = minOf(confidence, turn.confidence)
        }
        val single = participants.size == 1 && "UNKNOWN" !in participants && "UNKNOWN_SECONDARY" !in participants && !overlap
        val speakerId = if (single) participants.single() else "UNKNOWN"
        return Assignment(
            speakerId,
            if (single) emptyList() else participants.toList(),
            if (single) confidence else 0f,
        )
    }

    private fun refreshUtterances(predicate: (StoredUtterance) -> Boolean): List<DiarizationTranscriptUpdate> {
        val updates = mutableListOf<DiarizationTranscriptUpdate>()
        utterances.filter(predicate).forEach { utterance ->
            val assignment = assignmentFor(utterance.beginTime, utterance.endTime)
            if (
                assignment.speakerId == utterance.speakerId &&
                assignment.secondarySpeakerIds == utterance.secondarySpeakerIds
            ) return@forEach
            utterance.speakerId = assignment.speakerId
            utterance.secondarySpeakerIds = assignment.secondarySpeakerIds
            utterance.revision += 1
            updates += updateFor(utterance, assignment.confidence)
        }
        return updates
    }

    private fun updateFor(utterance: StoredUtterance, confidence: Float) = DiarizationTranscriptUpdate(
        utterance.utteranceId,
        utterance.revision,
        utterance.speakerId,
        utterance.secondarySpeakerIds.toList(),
        utterance.beginTime,
        utterance.endTime,
        confidence,
    )

    private fun turnAt(timeMs: Int): SpeakerTimelineTurn? = turns.asReversed().find {
        timeMs >= it.beginTime && timeMs < it.endTime
    }


    // Mirrors sherpa's BBPE alphabet/spacing; require byte-exact agreement with rawText.
    private fun decodedTranscriptTokens(rawText: String, tokens: List<String>,
        times: List<Int>): Pair<List<String>, List<Int>>? {
        if (tokens.size != times.size || tokens.joinToString("") == rawText) return null
        val alphabet = "ĀāĂăĄąĆćĈĉĊċČčĎďĐđĒēĔĕĖėĘęĚěĜĝĞğ !\"#\$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~ĠġĢģĤĥĦħĨĩĪīĬĭĮįİıĴĵĶķĸĹĺĻļĽľŁłŃńŅņŇňŊŋŌōŎŏŐőŒœŔŕŖŗŘřŚśŜŝŞşŠšŢţŤťŦŧŨũŪūŬŭŮůŰűŲųŴŵŶŷŸŹźŻżŽžƀƁƂƃƄƅƆƇƈƉƊƋƌƍƎƏƐƑƒƓƔƕƖƗƘƙƚƛƜƝƞƟƠơƢƣƤƥƦ"
        val bytes = mutableListOf<Int>()
        val owners = mutableListOf<Int>()
        tokens.forEachIndexed { index, token ->
            for (character in token) {
                if (character == '▁') {
                    if ((bytes.lastOrNull() ?: -1) in 33..126) {
                        bytes += 32
                        owners += times[index]
                    }
                    continue
                }
                val value = if (character == '⁇') 32 else alphabet.indexOf(character)
                if (value < 0) return null
                bytes += value
                owners += times[index]
            }
        }
        val decoded = mutableListOf<String>()
        val decodedTimes = mutableListOf<Int>()
        var byteOffset = 0
        var index = 0
        while (index < rawText.length) {
            val point = rawText.codePointAt(index)
            if (point in 0xD800..0xDFFF) return null
            val width = Character.charCount(point)
            val character = rawText.substring(index, index + width)
            val encoded = character.toByteArray(Charsets.UTF_8)
            encoded.forEachIndexed { part, value ->
                if (bytes.getOrNull(byteOffset + part) != (value.toInt() and 255)) return null
            }
            decoded += character
            decodedTimes += owners[byteOffset]
            byteOffset += encoded.size
            index += width
        }
        return if (byteOffset == bytes.size) decoded to decodedTimes else null
    }

    // Only punctuation/spacing insertions are alignable; do not guess ITN boundaries.
    private fun tokenTextBoundaries(tokens: List<String>, text: String): List<Int>? {
        val inserted = " ,.!?，。！？、;；:：\t\r\n"
        val boundaries = mutableListOf(0)
        var cursor = 0
        for ((index, token) in tokens.withIndex()) {
            if (token.isEmpty()) return null
            for ((character, value) in token.withIndex()) {
                val beforeInserted = cursor
                while (cursor < text.length && text[cursor] != value && text[cursor] in inserted) cursor++
                val matches = cursor < text.length && text[cursor] == value
                val replacedSpace = !matches && value in " \t\r\n" && (cursor == 0 ||
                    text.substring(beforeInserted, cursor).any { it in ",.!?，。！？、;；:：" })
                if (!matches && !replacedSpace) return null
                if (index > 0 && character == 0) boundaries += cursor
                if (matches) cursor++
            }
        }
        while (cursor < text.length && text[cursor] in inserted) cursor++
        if (cursor != text.length) return null
        boundaries += cursor
        return boundaries
    }

    private fun splitByTokenSpeaker(utterance: StoredUtterance, textBoundaries: List<Int>): List<DiarizedTranscriptUtterance> {
        val result = mutableListOf<DiarizedTranscriptUtterance>()
        val unanimous = unanimousSpeakerTurn(utterance)
        var groupStart = 0
        var active = turnAt(utterance.tokenTimesMs[0]) ?: unanimous
        for (index in 1..utterance.tokens.size) {
            val next = if (index < utterance.tokens.size) turnAt(utterance.tokenTimesMs[index]) ?: unanimous else null
            val same = index < utterance.tokens.size &&
                (next?.speakerId ?: "UNKNOWN") == (active?.speakerId ?: "UNKNOWN")
            if (same) continue
            val begin = if (groupStart == 0) utterance.beginTime else utterance.tokenTimesMs[groupStart]
            val end = if (index < utterance.tokens.size) utterance.tokenTimesMs[index] else utterance.endTime
            // Secondary changes annotate speech instead of splitting the primary
            // speaker's words. allTurns() retains their exact time intervals.
            val secondary = (active?.secondarySpeakerIds ?: emptyList()).toMutableSet()
            var overlap = active?.overlap ?: secondary.isNotEmpty()
            for (turn in turns) {
                if (overlapMs(begin, end, turn.beginTime, turn.endTime) <= 0) continue
                secondary.addAll(turn.secondarySpeakerIds.filter {
                    it != (active?.speakerId ?: "UNKNOWN") || (active?.speakerId ?: "UNKNOWN") == "UNKNOWN"
                })
                overlap = overlap || turn.overlap || turn.secondarySpeakerIds.isNotEmpty()
            }
            val text = utterance.tokens.subList(groupStart, index).joinToString("")
            result += DiarizedTranscriptUtterance(
                utteranceId = if (result.isEmpty()) utterance.utteranceId else "${utterance.utteranceId}.${result.size + 1}",
                sourceUtteranceId = utterance.utteranceId,
                rawText = text,
                text = utterance.text.substring(textBoundaries[groupStart], textBoundaries[index]),
                beginTime = begin,
                endTime = end,
                speakerId = active?.speakerId ?: "UNKNOWN",
                secondarySpeakerIds = secondary.toList(),
                confidence = active?.confidence ?: 0f,
                overlap = overlap,
            )
            groupStart = index
            active = next
        }
        return backfillUnknown(result)
    }

    private fun backfillUnknown(parts: List<DiarizedTranscriptUtterance>): List<DiarizedTranscriptUtterance> {
        // One current inference hop; operating points are recorded in
        // delivery/harmony-dingqiao/docs/UNKNOWN_SPEAKER_BACKFILL.md.
        val resolved = parts.mapIndexed { index, part ->
            val duration = part.endTime - part.beginTime
            if (part.speakerId != "UNKNOWN" || duration !in 0..2_500 ||
                blocksBackfill(part.secondarySpeakerIds, part.overlap)) return@mapIndexed part
            val previous = parts.getOrNull(index - 1)
            val next = parts.getOrNull(index + 1)
            if (previous != null && next != null && previous.speakerId != next.speakerId) return@mapIndexed part
            if (listOfNotNull(previous, next).any { blocksBackfill(it.secondarySpeakerIds, it.overlap) }) {
                return@mapIndexed part
            }
            val speakerId = previous?.speakerId ?: next?.speakerId ?: return@mapIndexed part
            if (speakerId == "UNKNOWN") return@mapIndexed part
            var evidenceBegin = part.beginTime
            if (duration == 0) {
                // A terminal token may start at the public end timestamp. Only
                // recent acoustic support can attach this text to its neighbour.
                if (next != null || previous == null || previous.endTime != part.beginTime) return@mapIndexed part
                evidenceBegin = max(previous.beginTime, part.beginTime - 2_500)
                if (turns.none { it.speakerId == speakerId &&
                    overlapMs(evidenceBegin, part.endTime, it.beginTime, it.endTime) > 0 }) return@mapIndexed part
            }
            if (turns.any { overlapMs(evidenceBegin, part.endTime, it.beginTime, it.endTime) > 0 &&
                ((it.speakerId != "UNKNOWN" && it.speakerId != speakerId) ||
                    blocksBackfill(it.secondarySpeakerIds, it.overlap)) }) return@mapIndexed part
            part.copy(speakerId = speakerId, confidence = 0f, speakerInferred = true)
        }
        val merged = mutableListOf<DiarizedTranscriptUtterance>()
        for (part in resolved) {
            val previous = merged.lastOrNull()
            if (previous != null && previous.speakerId == part.speakerId) {
                merged[merged.lastIndex] = previous.copy(
                    rawText = previous.rawText + part.rawText,
                    text = previous.text + part.text,
                    endTime = part.endTime,
                    confidence = min(previous.confidence, part.confidence),
                    speakerInferred = previous.speakerInferred || part.speakerInferred,
                    overlap = previous.overlap || part.overlap,
                    secondarySpeakerIds = (previous.secondarySpeakerIds + part.secondarySpeakerIds).distinct(),
                )
            } else {
                merged += part.copy(utteranceId = if (merged.isEmpty()) part.sourceUtteranceId
                    else "${part.sourceUtteranceId}.${merged.size + 1}")
            }
        }
        return merged
    }

    private fun blocksBackfill(secondary: List<String>, overlap: Boolean): Boolean =
        secondary.any { it != "UNKNOWN" && it != "UNKNOWN_SECONDARY" } || (overlap && secondary.isEmpty())

    private fun unanimousSpeakerTurn(utterance: StoredUtterance): SpeakerTimelineTurn? {
        var candidate: SpeakerTimelineTurn? = null
        for (turn in turns) {
            if (overlapMs(utterance.beginTime, utterance.endTime, turn.beginTime, turn.endTime) <= 0) continue
            // No acoustic coverage is not the same as explicit uncertainty or overlap.
            if (turn.speakerId == "UNKNOWN" || turn.overlap || turn.secondarySpeakerIds.isNotEmpty() ||
                (candidate != null && candidate.speakerId != turn.speakerId)) return null
            candidate = turn
        }
        return candidate
    }

    private fun unsplit(utterance: StoredUtterance): DiarizedTranscriptUtterance {
        val assignment = assignmentFor(utterance.beginTime, utterance.endTime)
        return DiarizedTranscriptUtterance(
            utterance.utteranceId,
            utterance.rawText,
            utterance.text,
            utterance.beginTime,
            utterance.endTime,
            utterance.speakerId,
            utterance.secondarySpeakerIds.toList(),
            assignment.confidence,
            turns.any { it.overlap && overlapMs(utterance.beginTime, utterance.endTime, it.beginTime, it.endTime) > 0 },
        )
    }
}

private fun overlapMs(beginA: Int, endA: Int, beginB: Int, endB: Int): Int =
    max(0, min(endA, endB) - max(beginA, beginB))
