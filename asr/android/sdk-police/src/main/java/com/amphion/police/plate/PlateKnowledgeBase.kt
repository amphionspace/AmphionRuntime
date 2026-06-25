package com.amphion.police.plate

import android.content.Context
import java.io.BufferedReader
import java.io.InputStreamReader

/**
 * Layer 0：GA 36-2018 车牌知识库（PlateNormalizer V2 用）。
 *
 * 与老方案完全独立：老方案的 [PlateNormalizer] / [PlateHomophoneDict] 不读取本类，
 * 也不读取 assets 下的 `plate/plate_spec_ga36.tsv`。
 *
 * 范围：仅民用「普通号牌(7位)」+「新能源号牌(8位)」。警/学/挂/港澳/使领/台 暂不收录。
 *
 * 数据来源：发牌机关字母表对 12 省（团队测试集已核验）置 [ProvinceSpec.lettersVerified]=true；
 * 其余按 GA 36 补全并置 false，待人工核对。校验逻辑见 [PlateValidatorV2]：
 * 对未核验省份不强制「字母属于该省」约束，避免误拒合法车牌。
 */
class PlateKnowledgeBase private constructor(
    private val byChar: Map<Char, ProvinceSpec>,
) {

    /** 全部省份简称（单字）。 */
    val provinceChars: Set<Char> get() = byChar.keys

    /** 简称 → 省份规格。 */
    fun province(char: Char): ProvinceSpec? = byChar[char]

    /** 是否为已知省份简称。 */
    fun isProvinceChar(char: Char): Boolean = byChar.containsKey(char)

    /**
     * 字母 [letter] 是否可作为省份 [char] 的发牌机关代号。
     *
     * @param strictUnverified 为 false（默认）时，对 [ProvinceSpec.lettersVerified]=false 的省份
     *   只要求字母在合法字母表（不含 I/O）内即可，不强制属于该省，以避免误拒；
     *   为 true 时对所有省份强制按收录字母表校验。
     */
    fun isValidAuthorityLetter(char: Char, letter: Char, strictUnverified: Boolean = false): Boolean {
        val spec = byChar[char] ?: return false
        if (letter !in PLATE_ALPHABET) return false
        return when {
            spec.lettersVerified -> letter in spec.letters
            strictUnverified -> letter in spec.letters
            else -> true
        }
    }

    data class ProvinceSpec(
        val char: Char,
        val name: String,
        /** 带声调的拼音（数字调），用于区分近音省份（吉ji2/冀ji4、津jin1/晋jin4）。 */
        val pinyin: String,
        val polyphone: Boolean,
        /** ASR 常见同音/近音误字。 */
        val homophones: List<Char>,
        /** 发牌机关字母表是否已核验。 */
        val lettersVerified: Boolean,
        /** 合法发牌机关代号字母（不含 I/O）。 */
        val letters: Set<Char>,
        val notes: String,
    )

    companion object {
        /** 资产路径（V2 专用，老方案不引用）。 */
        const val ASSET_PATH = "plate/plate_spec_ga36.tsv"

        /** GA 36 车牌可用字母：A–Z 去除易混的 I、O。 */
        const val PLATE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ"

        fun load(context: Context): PlateKnowledgeBase {
            context.assets.open(ASSET_PATH).use { input ->
                return loadFromReader(BufferedReader(InputStreamReader(input, Charsets.UTF_8)))
            }
        }

        fun loadFromReader(reader: BufferedReader): PlateKnowledgeBase {
            val map = linkedMapOf<Char, ProvinceSpec>()
            reader.forEachLine { line ->
                val s = line.trimEnd()
                if (s.isEmpty() || s.startsWith("#")) return@forEachLine
                val cols = s.split('\t')
                if (cols.size < 7) return@forEachLine
                val char = cols[0].trim()
                if (char.length != 1) return@forEachLine
                val letters = parseList(cols[6]).mapNotNull { it.singleOrNull() }.toSet()
                val spec = ProvinceSpec(
                    char = char[0],
                    name = cols[1].trim(),
                    pinyin = cols[2].trim(),
                    polyphone = cols[3].trim() == "1",
                    homophones = parseList(cols[4]).mapNotNull { it.singleOrNull() },
                    lettersVerified = cols[5].trim() == "1",
                    letters = letters,
                    notes = cols.getOrNull(7)?.trim().orEmpty(),
                )
                map[spec.char] = spec
            }
            require(map.isNotEmpty()) { "empty plate knowledge base" }
            return PlateKnowledgeBase(map)
        }

        private fun parseList(field: String): List<String> =
            field.split(',').map { it.trim() }.filter { it.isNotEmpty() }
    }
}
