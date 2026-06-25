package com.lits.tts.sdk.internal

/**
 * 解析自 `.lic` 文件 payload 的授权声明（不含签名）。仅内部使用。
 *
 * 与签发端（`tools/license/issue_license.py`）的 payload JSON 字段一一对应。
 *
 * @property licenseId 授权编号
 * @property customer 客户名
 * @property applicationId Android 宿主 applicationId；兼容旧 license 字段
 * @property bundleName HarmonyOS 应用 bundleName；Android 可用 applicationId 兼容
 * @property signingCertDigest 绑定的签名证书 SHA-256（大写、可含冒号）；空表示不绑证书
 * @property certSha256 旧 license 字段；新签发使用 signingCertDigest
 * @property deviceIdHashAlg 设备 ID 哈希算法；当前支持 SHA-256
 * @property deviceIdSaltId 设备 ID 哈希盐编号；当前实现也作为哈希盐材料
 * @property authorizedDeviceHashes 已授权 SN 哈希白名单；空表示不绑设备
 * @property deviceSha256 旧单机绑定字段；新签发不再使用
 * @property issuedAt 签发日期 `yyyy-MM-dd`
 * @property expiresAt 到期日期 `yyyy-MM-dd`；空表示永久
 * @property maintenanceUntil 可升级维护期截止日 `yyyy-MM-dd`；空表示不限制
 * @property installTier 装机量档位（声明性）
 * @property features 授权能力；当前仅允许 ASR / TTS
 * @property sdkMajor 兼容的 SDK 大版本；-1 表示未声明
 */
internal data class LicenseClaims(
    val licenseId: String,
    val customer: String,
    val applicationId: String,
    val bundleName: String,
    val signingCertDigest: String,
    val certSha256: String,
    val deviceIdHashAlg: String,
    val deviceIdSaltId: String,
    val authorizedDeviceHashes: Set<String>,
    val deviceSha256: String,
    val issuedAt: String,
    val expiresAt: String,
    val maintenanceUntil: String,
    val installTier: String,
    val features: List<String>,
    val sdkMajor: Int,
) {
    val boundApplicationId: String
        get() = applicationId.ifBlank { bundleName }

    val boundSigningCertDigest: String
        get() = signingCertDigest.ifBlank { certSha256 }
}
