package com.amphion.police.plate

/**
 * Layer 0 校验：省份感知的车牌格式校验（PlateNormalizer V2 用，老方案不引用）。
 *
 * 相比老方案 [PlateNormalizer.isValidPlate] 的「任意省 + 任意字母」正则，本校验会查
 * [PlateKnowledgeBase]：省份简称须已知、发牌机关字母须属于该省（仅对已核验省份强制）。
 *
 * 范围（按本期决定）：仅民用普通号牌(7位) + 新能源号牌(8位)；不含警/学/挂/港澳/使领/台。
 *
 * GA 36-2018 文法：
 * - 普通：省 + 机关字母 + 5 位序号（序号字符 ∈ A–Z 去 I/O 及 0–9）
 * - 新能源(小型)：省 + 机关字母 + [D/F] + 5 位序号字符（能源标识 D/F 居首）
 * - 新能源(大型)：省 + 机关字母 + 5 位数字 + [D/F]
 */
class PlateValidatorV2(private val kb: PlateKnowledgeBase) {

    enum class PlateType { NORMAL, NEW_ENERGY }

    /** 序号体字符集：A–Z 去 I/O，外加 0–9。 */
    private val serialChar = PlateKnowledgeBase.PLATE_ALPHABET + "0123456789"

    /**
     * 校验 [plate] 是否为合法民用车牌。
     *
     * @param strictUnverified 透传给 [PlateKnowledgeBase.isValidAuthorityLetter]；默认 false，
     *   即对未核验省份不强制「字母属于该省」，避免误拒。
     */
    fun isValidPlate(plate: String, strictUnverified: Boolean = false): Boolean =
        classify(plate, strictUnverified) != null

    /** 返回车牌类型；非法返回 null。 */
    fun classify(plate: String, strictUnverified: Boolean = false): PlateType? {
        if (plate.length != 7 && plate.length != 8) return null
        val province = plate[0]
        if (!kb.isProvinceChar(province)) return null
        val authority = plate[1]
        if (!kb.isValidAuthorityLetter(province, authority, strictUnverified)) return null

        val serial = plate.substring(2)
        return when (plate.length) {
            7 -> if (isNormalSerial(serial)) PlateType.NORMAL else null
            8 -> if (isNewEnergySerial(serial)) PlateType.NEW_ENERGY else null
            else -> null
        }
    }

    /** 普通号牌序号：5 位，字符 ∈ [serialChar]。 */
    private fun isNormalSerial(serial: String): Boolean =
        serial.length == 5 && serial.all { it in serialChar }

    /**
     * 新能源序号：6 位。
     * - 小型：能源标识 D/F 居首，后 5 位为序号字符（[serialChar]，含字母/数字）。
     * - 大型：前 5 位数字，能源标识 D/F 居末。
     *
     * 注：小型放宽为「首位 D/F + 5 位序号字符」，与老方案 [PlateNormalizer.isValidPlate]
     * 及团队语料（如 冀RDM235D、辽BFWJ544）一致，避免误拒真实新能源牌。
     */
    private fun isNewEnergySerial(serial: String): Boolean {
        if (serial.length != 6) return false
        val small = serial[0] in "DF" && serial.substring(1).all { it in serialChar }
        val large = serial.substring(0, 5).all { it.isDigit() } && serial[5] in "DF"
        return small || large
    }
}
