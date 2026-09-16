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
        val assignment = assignmentFor(beginTime, endTime)
        utterances += StoredUtterance(
            audioEndTime, id, rawText, text, tokens.toList(), tokenTimesMs.toList(), beginTime, endTime,
            0, assignment.speakerId, assignment.secondarySpeakerIds,
        )
        return id
    }

    fun currentAssignment(utteranceId: String): DiarizationTranscriptUpdate? {
        val utterance = utterances.find { it.utteranceId == utteranceId } ?: return null
        val assignment = assignmentFor(utterance.beginTime, utterance.endTime)
        return updateFor(utterance, assignment.confidence)
    }

    fun applySpeakerTurns(newTurns: List<SpeakerTimelineTurn>): List<DiarizationTranscriptUpdate> {
        if (newTurns.isEmpty()) return emptyList()
        turns += newTurns.map { it.copy(
            secondarySpeakerIds = it.secondaryEvidenceSpeakerIds.filter { id -> id != it.speakerId }.distinct(),
            secondaryEvidenceKeys = it.secondaryEvidenceKeys.toList(),
            secondaryEvidenceSpeakerIds = it.secondaryEvidenceSpeakerIds.toList()) }
        return refreshUtterances { utterance ->
            newTurns.any { overlapMs(utterance.beginTime, utterance.endTime, it.beginTime, it.endTime) > 0 }
        }
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

    fun commitThrough(endTime: Int): List<DiarizedTranscriptUtterance> {
        val result = finalUtterances(endTime)
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
        val durations = linkedMapOf<String, Int>()
        val secondary = sortedSetOf<String>()
        var covered = 0
        turns.forEach { turn ->
            val duration = overlapMs(beginTime, endTime, turn.beginTime, turn.endTime)
            if (duration <= 0) return@forEach
            durations[turn.speakerId] = (durations[turn.speakerId] ?: 0) + duration
            covered += duration
            secondary += turn.secondarySpeakerIds
        }
        val best = durations.maxByOrNull { it.value }
        val speakerId = best?.key ?: "UNKNOWN"
        secondary.remove(speakerId)
        return Assignment(
            speakerId,
            secondary.toList(),
            if (covered <= 0) 0f else (best?.value ?: 0).toFloat().div(covered).coerceIn(0f, 1f),
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

    // Only punctuation/spacing insertions are alignable; do not guess ITN boundaries.
    private fun tokenTextBoundaries(tokens: List<String>, text: String): List<Int>? {
        val inserted = " ,.!?，。！？、;；:：\t\r\n"
        val boundaries = mutableListOf(0)
        var cursor = 0
        for ((index, token) in tokens.withIndex()) {
            if (token.isEmpty()) return null
            for ((character, value) in token.withIndex()) {
                while (cursor < text.length && text[cursor] != value && text[cursor] in inserted) cursor++
                if (cursor >= text.length || text[cursor] != value) return null
                if (index > 0 && character == 0) boundaries += cursor
                cursor++
            }
        }
        while (cursor < text.length && text[cursor] in inserted) cursor++
        if (cursor != text.length) return null
        boundaries += cursor
        return boundaries
    }

    private fun splitByTokenSpeaker(utterance: StoredUtterance, textBoundaries: List<Int>): List<DiarizedTranscriptUtterance> {
        val result = mutableListOf<DiarizedTranscriptUtterance>()
        var groupStart = 0
        var active = turnAt(utterance.tokenTimesMs[0])
        for (index in 1..utterance.tokens.size) {
            val next = if (index < utterance.tokens.size) turnAt(utterance.tokenTimesMs[index]) else null
            val same = index < utterance.tokens.size &&
                (next?.speakerId ?: "UNKNOWN") == (active?.speakerId ?: "UNKNOWN") &&
                (next?.secondarySpeakerIds ?: emptyList<String>()) ==
                (active?.secondarySpeakerIds ?: emptyList<String>())
            if (same) continue
            val begin = if (groupStart == 0) utterance.beginTime else utterance.tokenTimesMs[groupStart]
            val end = if (index < utterance.tokens.size) utterance.tokenTimesMs[index] else utterance.endTime
            val secondary = active?.secondarySpeakerIds?.toList() ?: emptyList()
            val text = utterance.tokens.subList(groupStart, index).joinToString("")
            result += DiarizedTranscriptUtterance(
                utteranceId = if (result.isEmpty()) utterance.utteranceId else "${utterance.utteranceId}.${result.size + 1}",
                sourceUtteranceId = utterance.utteranceId,
                rawText = text,
                text = utterance.text.substring(textBoundaries[groupStart], textBoundaries[index]),
                beginTime = begin,
                endTime = end,
                speakerId = active?.speakerId ?: "UNKNOWN",
                secondarySpeakerIds = secondary,
                confidence = active?.confidence ?: 0f,
                overlap = active?.overlap ?: secondary.isNotEmpty(),
            )
            groupStart = index
            active = next
        }
        return result
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
