package com.amphion.asr.internal

/**
 * 解析自 `.lic` 文件 payload 的授权声明（不含签名）。仅内部使用。
 *
 * 与签发端（`tools/license/issue_license.py`）的 payload JSON 字段一一对应。
 *
 * @property licenseId 授权编号
 * @property customer 客户名
 * @property applicationId 必填；绑定的宿主 applicationId
 * @property certSha256 绑定的签名证书 SHA-256（大写、可含冒号）；空表示不绑证书
 * @property issuedAt 签发日期 `yyyy-MM-dd`
 * @property expiresAt 到期日期 `yyyy-MM-dd`；空表示永久
 * @property installTier 装机量档位（声明性）
 * @property features 授权功能模块
 * @property sdkMajor 兼容的 SDK 大版本；-1 表示未声明
 */
internal data class LicenseClaims(
    val licenseId: String,
    val customer: String,
    val applicationId: String,
    val certSha256: String,
    val issuedAt: String,
    val expiresAt: String,
    val installTier: String,
    val features: List<String>,
    val sdkMajor: Int,
)
