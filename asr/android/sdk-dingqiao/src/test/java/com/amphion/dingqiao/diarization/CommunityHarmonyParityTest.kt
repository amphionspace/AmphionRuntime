package com.amphion.dingqiao.diarization

import org.junit.Assert.*
import org.junit.Test

class CommunityHarmonyParityTest {
    @Test fun capturedHarmonyCommitDecisionsMatchAndroid() {
        val identity = CommunitySpeakerIdentity(4)
        val lines = checkNotNull(javaClass.getResourceAsStream("/community-harmony-42911432-commits.txt"))
            .bufferedReader().use { it.readLines() }.filterNot { it.startsWith("#") || it.isBlank() }
        assertEquals(5, lines.size)
        for (line in lines) {
            val fields = line.split('|')
            fun ints(index: Int) = fields[index].split(',').map { it.toInt() }.toIntArray()
            val ids = fields[3].split(',')
            identity.retainWindows(ids.toSet())
            val assignment = identity.assign(ids, ints(4), fields[2].toInt(), ints(5),
                ints(6).map { it == 1 }.toBooleanArray())
            assertArrayEquals("Harmony mapping at ${fields[0]}..${fields[1]}", ints(7), assignment.mapping)
            assertEquals(fields[8].toInt(), assignment.before)
            assertEquals(fields[9].toInt(), assignment.after)
        }
        // Parity is not an accuracy PASS: the final captured clustering lost identities.
        val last = lines.last().split('|')
        assertEquals("preserve the captured failure", 1, last[2].toInt())
        assertTrue(last[8].toInt() > 1)
    }
}
