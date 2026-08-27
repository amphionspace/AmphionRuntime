package com.amphion.police.person

import org.junit.Assert.assertEquals
import org.junit.Test

class PersonNameMatcherTest {
    @Test
    fun replacesSamePinyinWindowThatOverlapsPersonEntity() {
        val matcher = PersonNameMatcher(
            mapOf(
                "文" to "wen2", "赋" to "fu4", "富" to "fu4",
                "成" to "cheng2", "城" to "cheng2",
                "余" to "yu2", "祁" to "qi2", "其" to "qi2", "根" to "gen1",
            ),
            listOf("文赋成", "余祁根"),
        )
        assertEquals("往往给文赋成发一条信息", matcher.normalize("往往给文富城发一条信息", listOf(PersonSpan(3, 6))))
        assertEquals("给文赋成发短信。", matcher.normalize("给文富成发短信。", listOf(PersonSpan(1, 4))))
        assertEquals("该文赋成发短信。", matcher.normalize("该文富城发短信。", emptyList()))
        assertEquals("给余祁根发一条信息", matcher.normalize("给余其根发一条信息", listOf(PersonSpan(1, 2))))
    }

    @Test
    fun twoCharacterFallbackRequiresPersonAndAmbiguousSignatureIsIgnored() {
        val pinyin = mapOf(
            "文" to "wen2", "赋" to "fu4", "富" to "fu4",
            "成" to "cheng2", "城" to "cheng2",
        )
        assertEquals(
            "文富很好",
            PersonNameMatcher(pinyin, listOf("文赋")).normalize("文富很好", emptyList()),
        )
        assertEquals(
            "给文富城发信息",
            PersonNameMatcher(pinyin, listOf("文赋成", "文富城"))
                .normalize("给文富城发信息", listOf(PersonSpan(1, 4))),
        )
    }

    @Test
    fun ignoresNamesLongerThanThreeCharacters() {
        val matcher = PersonNameMatcher(
            mapOf(
                "三" to "san1", "科" to "ke1", "颗" to "ke1",
                "真" to "zhen1", "澄" to "cheng2", "诚" to "cheng2",
            ),
            listOf("三科真澄"),
        )
        assertEquals("请联系三颗真诚", matcher.normalize("请联系三颗真诚", listOf(PersonSpan(3, 7))))
    }
}
