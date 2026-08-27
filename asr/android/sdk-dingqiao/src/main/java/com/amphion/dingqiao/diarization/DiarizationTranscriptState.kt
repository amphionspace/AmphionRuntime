package com.amphion.dingqiao.diarization

import kotlin.math.max
import kotlin.math.min

internal data class SpeakerTimelineTurn(
    val beginTime: Int,
    val endTime: Int,
    var speakerId: String,
    var secondarySpeakerIds: List<String>,
    val confidence: Float = 0f,
    val overlap: Boolean = false,
    val evidenceKey: String? = null,
    val secondaryEvidenceKeys: List<String> = emptyList(),
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
)

private data class StoredUtterance(
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
    private val turns = mutableListOf<SpeakerTimelineTurn>()

    fun addUtterance(
        rawText: String,
        text: String,
        tokens: List<String>,
        tokenTimesMs: List<Int>,
        beginTime: Int,
        endTime: Int,
    ): String {
        val id = "u${utterances.size + 1}"
        val assignment = assignmentFor(beginTime, endTime)
        utterances += StoredUtterance(
            id, rawText, text, tokens.toList(), tokenTimesMs.toList(), beginTime, endTime,
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
        turns += newTurns.map { it.copy(secondarySpeakerIds = it.secondarySpeakerIds.toList()) }
        return refreshUtterances { utterance ->
            newTurns.any { overlapMs(utterance.beginTime, utterance.endTime, it.beginTime, it.endTime) > 0 }
        }
    }

    fun applyEvidenceRemap(remap: Map<String, String>, fromTime: Int = 0): List<DiarizationTranscriptUpdate> {
        turns.filter { it.endTime >= fromTime }.forEach { turn ->
            turn.evidenceKey?.let { turn.speakerId = remap[it] ?: turn.speakerId }
            turn.secondarySpeakerIds = turn.secondarySpeakerIds.mapIndexed { index, speakerId ->
                remap[turn.secondaryEvidenceKeys.getOrNull(index)] ?: speakerId
            }.filter { it != turn.speakerId }.distinct()
        }
        return refreshUtterances { it.endTime >= fromTime }
    }

    fun applySpeakerRemap(remap: Map<String, String>, fromTime: Int = 0): List<DiarizationTranscriptUpdate> {
        turns.filter { it.endTime >= fromTime }.forEach { turn ->
            turn.speakerId = remap[turn.speakerId] ?: turn.speakerId
            turn.secondarySpeakerIds = turn.secondarySpeakerIds.map { remap[it] ?: it }
                .filter { it != turn.speakerId }.distinct()
        }
        return refreshUtterances { it.endTime >= fromTime }
    }

    fun finalUtterances(): List<DiarizedTranscriptUtterance> = utterances.flatMap { utterance ->
        if (
            utterance.tokens.isEmpty() ||
            utterance.tokens.size != utterance.tokenTimesMs.size ||
            utterance.tokens.joinToString("") != utterance.text
        ) {
            listOf(unsplit(utterance))
        } else {
            val split = splitByTokenSpeaker(utterance)
            if (split.joinToString("") { it.text } == utterance.text) split else listOf(unsplit(utterance))
        }
    }

    fun allTurns(): List<SpeakerTimelineTurn> = turns.map {
        it.copy(secondarySpeakerIds = it.secondarySpeakerIds.toList())
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

    private fun splitByTokenSpeaker(utterance: StoredUtterance): List<DiarizedTranscriptUtterance> {
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
                rawText = text,
                text = text,
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
