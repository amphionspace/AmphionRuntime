package com.amphion.asr.sample.plate

/**
 * 从参考句式文本提取期望车牌（与 test_data/generate_kespeech_plate_eval.py 规则一致）。
 */
object PlateTextUtil {

    private const val PROVINCES = "京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领"
    private val PLATE_FIND = Regex("[$PROVINCES][A-HJ-NP-Z][A-HJ-NP-Z0-9]{5}")

    fun extractPlate(text: String): String = PLATE_FIND.find(text)?.value.orEmpty()
}
