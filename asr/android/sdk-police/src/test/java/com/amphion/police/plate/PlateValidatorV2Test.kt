package com.amphion.police.plate

import com.amphion.police.test.TestAssets
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.io.BufferedReader
import java.io.FileReader

class PlateValidatorV2Test {

    private lateinit var kb: PlateKnowledgeBase
    private lateinit var validator: PlateValidatorV2

    @Before
    fun setUp() {
        val file = TestAssets.resolve(PlateKnowledgeBase.ASSET_PATH)
        kb = BufferedReader(FileReader(file)).use { PlateKnowledgeBase.loadFromReader(it) }
        validator = PlateValidatorV2(kb)
    }

    @Test
    fun knowledgeBaseLoadsAll31Provinces() {
        assertEquals(31, kb.provinceChars.size)
    }

    @Test
    fun toneDistinguishesNearHomophoneProvinces() {
        assertEquals("ji2", kb.province('吉')!!.pinyin)
        assertEquals("ji4", kb.province('冀')!!.pinyin)
        assertEquals("jin1", kb.province('津')!!.pinyin)
        assertEquals("jin4", kb.province('晋')!!.pinyin)
        assertEquals("yu2", kb.province('渝')!!.pinyin)
        assertEquals("yu4", kb.province('豫')!!.pinyin)
    }

    @Test
    fun polyphoneProvincesFlagged() {
        assertTrue(kb.province('蒙')!!.polyphone)
        assertTrue(kb.province('藏')!!.polyphone)
        assertTrue(kb.province('宁')!!.polyphone)
        assertFalse(kb.province('京')!!.polyphone)
    }

    @Test
    fun acceptsValidNormalPlatesNationwide() {
        assertTrue(validator.isValidPlate("冀R12345"))
        assertTrue(validator.isValidPlate("辽B88888"))
        assertTrue(validator.isValidPlate("京AF0236"))
        assertTrue(validator.isValidPlate("鲁A12B34"))
        assertTrue(validator.isValidPlate("沪WD1234")) // 沪 含 W
    }

    @Test
    fun rejectsAuthorityLetterNotInVerifiedProvince() {
        // 辽 已核验，合法字母不含 X
        assertNull(validator.classify("辽X12345"))
        assertFalse(validator.isValidPlate("辽X12345"))
        // 晋 已核验，无 G
        assertFalse(validator.isValidPlate("晋G1234A"))
    }

    @Test
    fun rejectsLetterIandO() {
        assertFalse(validator.isValidPlate("京I12345"))
        assertFalse(validator.isValidPlate("京O12345"))
    }

    @Test
    fun rejectsUnknownProvince() {
        assertFalse(validator.isValidPlate("X12345A"))
        assertFalse(validator.isValidPlate("国A12345"))
    }

    @Test
    fun newEnergySmallAndLargeFormats() {
        assertEquals(PlateValidatorV2.PlateType.NEW_ENERGY, validator.classify("京AD12345"))
        assertEquals(PlateValidatorV2.PlateType.NEW_ENERGY, validator.classify("京AF12345"))
        assertEquals(PlateValidatorV2.PlateType.NEW_ENERGY, validator.classify("京A12345D"))
        // 8 位但序号既非 D/F 开头也非 D/F 结尾 → 非新能源
        assertNull(validator.classify("京A123456"))
    }

    @Test
    fun unverifiedProvinceFallsBackToAlphabetOnly() {
        // 用合成知识库验证「未核验省份回退」逻辑（实际数据中 31 省均已核验）。
        // 列：char,name,pinyin,polyphone,homophones,letters_verified,letters,notes
        val row = listOf("测", "测试省", "ce4", "0", "", "0", "A,B,C", "未核验示例").joinToString("\t")
        val syntheticKb = BufferedReader(java.io.StringReader(row)).use {
            PlateKnowledgeBase.loadFromReader(it)
        }
        val v = PlateValidatorV2(syntheticKb)
        // Z 不在收录字母表(A,B,C)：默认不强制 → 放行
        assertTrue(v.isValidPlate("测Z12345"))
        // strict 模式下 Z 不属于该省 → 拒绝
        assertFalse(v.isValidPlate("测Z12345", strictUnverified = true))
        // 收录内字母两种模式都合法
        assertTrue(v.isValidPlate("测A12345", strictUnverified = true))
    }

    @Test
    fun allProvincesVerified() {
        // 31 省发牌字母表均已核验（团队测试集 + GA36 + 真实数据交叉核对）。
        assertEquals(31, kb.provinceChars.size)
        for (ch in kb.provinceChars) {
            assertTrue("province $ch should be verified", kb.province(ch)!!.lettersVerified)
        }
    }

    @Test
    fun dataVerifiedLetterAdditions() {
        // 与真实数据交叉核对后补入的字母
        assertTrue(kb.province('渝')!!.letters.contains('D'))
        assertTrue(kb.province('鄂')!!.letters.contains('W'))
        assertTrue(kb.province('皖')!!.letters.contains('Q'))
    }
}
