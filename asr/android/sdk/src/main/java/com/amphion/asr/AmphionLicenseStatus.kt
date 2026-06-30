package com.amphion.asr

import android.content.Context

/**
 * License 强制策略：决定 [AmphionRuntime.init] 在 license 校验失败时的行为。
 *
 * 注意：仅当 SDK 被「武装」（构建期注入了 license 公钥）时本策略才生效。开发 / 内部
 * 构建（未注入公钥）下 SDK 处于 [AmphionLicenseStatus.State.DEV_UNLICENSED]，不做任何校验。
 */
public enum class LicenseEnforcement {
    /**
     * 默认。license 缺失 / 验签失败 / 绑定不符 / 过期时，[AmphionRuntime.init] 抛
     * [IllegalStateException]（message 形如 `code=6003: ...`，错误码取自 [AsrErrorCode]）。
     */
    ENFORCE,

    /**
     * 宽松。校验失败时 [AmphionRuntime.init] 不抛异常，仅打 ERROR 日志；
     * [AmphionRuntime.licenseStatus] 返回 [AmphionLicenseStatus.State.INVALID]，由业务方
     * 自行决定是否提示 / 降级。用于灰度上线或现场排障，不建议长期使用。
     */
    PERMISSIVE,
}

/**
 * License 运行状态快照。通过 [AmphionRuntime.licenseStatus] 查询，可用于在「关于」页展示
 * 授权客户 / 到期日 / 档位，或在排障时确认 SDK 当前是否被授权武装。
 *
 * 字段在 [State.LICENSED] 时全部有效；其他状态下文本字段可能为空。
 *
 * @property state 当前授权状态机，见 [State]
 * @property valid 是否处于已授权可用状态（等价于 `state == State.LICENSED`）
 * @property errorCode 校验错误码（取自 [AsrErrorCode]）；无错误时为 [AsrErrorCode.OK]
 * @property licenseId 授权编号（我方签发时分配）
 * @property customer 授权客户名
 * @property applicationId license 记录的 applicationId；Android 端不按该字段限制宿主应用
 * @property bundleName license 记录的 HarmonyOS bundleName；Android 端不按该字段限制宿主应用
 * @property signingCertDigest license 绑定的签名证书 SHA-256
 * @property deviceIdHashAlg 设备 SN 哈希算法
 * @property deviceIdSaltId 设备 SN 哈希盐编号；当前实现也作为哈希盐材料
 * @property authorizedDeviceCount 授权设备数量
 * @property maintenanceUntil 可升级维护期截止日（`yyyy-MM-dd`）
 * @property issuedAt 签发日期（`yyyy-MM-dd`）
 * @property expiresAt 到期日期（`yyyy-MM-dd`）；空字符串表示永久授权（买断）
 * @property installTier 装机量档位标识（声明性，仅用于展示 / 审计）
 * @property features 授权能力列表；当前仅允许 `ASR` / `TTS`
 */
public data class AmphionLicenseStatus(
    public val state: State,
    public val valid: Boolean,
    public val errorCode: Int,
    public val licenseId: String,
    public val customer: String,
    public val applicationId: String,
    public val bundleName: String,
    public val signingCertDigest: String,
    public val deviceIdHashAlg: String,
    public val deviceIdSaltId: String,
    public val authorizedDeviceCount: Int,
    public val maintenanceUntil: String,
    public val issuedAt: String,
    public val expiresAt: String,
    public val installTier: String,
    public val features: List<String>,
) {

    /** 授权状态机。 */
    public enum class State {
        /** 尚未调用 [AmphionRuntime.init]。 */
        NOT_INITIALIZED,

        /** SDK 未武装 license（构建期未注入公钥）。开发 / 内部构建，不做校验、功能可用。 */
        DEV_UNLICENSED,

        /** license 校验全部通过。 */
        LICENSED,

        /** license 校验失败；仅 [LicenseEnforcement.PERMISSIVE] 模式会到达此状态。 */
        INVALID,
    }

    /** 该 license 是否授权了某个功能模块（[features] 包含 [feature]）。 */
    public fun hasFeature(feature: String): Boolean = features.contains(feature)

    internal companion object {
        val NOT_INITIALIZED: AmphionLicenseStatus = AmphionLicenseStatus(
            state = State.NOT_INITIALIZED,
            valid = false,
            errorCode = AsrErrorCode.SDK_NOT_INITIALIZED,
            licenseId = "",
            customer = "",
            applicationId = "",
            bundleName = "",
            signingCertDigest = "",
            deviceIdHashAlg = "",
            deviceIdSaltId = "",
            authorizedDeviceCount = 0,
            maintenanceUntil = "",
            issuedAt = "",
            expiresAt = "",
            installTier = "",
            features = emptyList(),
        )
    }
}

/**
 * License 设备绑定用 SN 码提供方。
 *
 * Android 公开 API 无法在所有系统版本稳定读取硬件 SN，因此交付时由宿主或客户适配层注入。
 * 返回值会被 SDK 做 trim + uppercase 规范化，再按 license 中的 `deviceIdSaltId` 计算白名单哈希。
 */
public fun interface AmphionDeviceIdProvider {
    public fun getDeviceSerial(context: Context): String?
}
