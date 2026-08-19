package com.amphion.police

import java.security.MessageDigest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PoliceHotwordProfileTest {

    @Test
    fun parserDefaultsToFullAndRejectsUnknownValues() {
        assertEquals(PoliceHotwordProfile.FULL, PoliceHotwordProfile.parse(null))
        assertEquals(PoliceHotwordProfile.FULL, PoliceHotwordProfile.parse("full"))
        assertEquals(PoliceHotwordProfile.PRUNE_UI30, PoliceHotwordProfile.parse("prune_ui30"))
        assertEquals(PoliceHotwordProfile.NONE, PoliceHotwordProfile.parse("none"))
        assertTrue(runCatching { PoliceHotwordProfile.parse("unknown") }.isFailure)
    }

    @Test
    fun fullProfileLocksCurrentDeliveryOrderAndCount() {
        val words = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = PoliceHotwordProfile.FULL,
        )

        assertEquals(370, words.size)
        assertEquals(370, words.toSet().size)
        assertEquals(FULL_ORDERED_SHA256, sha256(words.joinToString("\n", postfix = "\n")))
    }

    @Test
    fun noneProfileKeepsCustomerWordsAndDeduplicatesThem() {
        val words = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = listOf(" 甲方热词 ", "甲方热词", "另一个热词"),
            profile = PoliceHotwordProfile.NONE,
        )

        assertEquals(listOf("甲方热词", "另一个热词"), words)
        assertFalse(words.contains("警鉴"))
    }

    @Test
    fun pruneUi30RemovesExactlyTheFirstCandidateBatch() {
        val full = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = PoliceHotwordProfile.FULL,
        )
        val candidate = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = PoliceHotwordProfile.PRUNE_UI30,
        )
        val removed = PoliceHotwordPruningCandidates.UI30_REMOVED_TERMS

        assertEquals(30, removed.size)
        assertTrue(full.containsAll(removed))
        assertEquals(340, candidate.size)
        assertEquals(full.filterNot { it in removed }, candidate)
        assertTrue(candidate.contains("警鉴"))
        assertTrue(candidate.contains("签收警单"))
        assertTrue(candidate.contains("车牌"))
        assertTrue(candidate.contains("派出所"))
    }

    @Test
    fun customerCanReAddAWordRemovedByPruneUi30() {
        val words = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = listOf("任务管理"),
            profile = PoliceHotwordProfile.PRUNE_UI30,
        )

        assertEquals("任务管理", words.first())
        assertEquals(341, words.size)
        assertEquals(1, words.count { it == "任务管理" })
    }

    @Test
    fun noneProfileWithoutCustomerWordsUsesPlaceholder() {
        assertEquals(
            listOf(PoliceEngineConfig.HOTWORD_POOL_PLACEHOLDER),
            PoliceEngineConfig.effectiveHotwordsForProfile(
                userHotwords = emptyList(),
                profile = PoliceHotwordProfile.NONE,
            ),
        )
    }

    @Test
    fun explicitFullAndDefaultDeliveryAssemblyMatch() {
        val defaultWords = PoliceEngineConfig.effectiveHotwords(userHotwords = emptyList())
        val profileWords = PoliceEngineConfig.effectiveHotwordsForProfile(
            userHotwords = emptyList(),
            profile = PoliceHotwordProfile.FULL,
        )

        assertEquals(defaultWords, profileWords)
        assertTrue(profileWords.contains("警鉴"))
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it.toInt() and 0xff) }

    companion object {
        private const val FULL_ORDERED_SHA256 =
            "b45d189b7e3add1b1e5cc002fdb564f97d266f1b794ae16d7a711bbc6eb40e07"
    }
}
