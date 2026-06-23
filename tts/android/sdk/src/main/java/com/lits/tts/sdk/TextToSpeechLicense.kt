package com.lits.tts.sdk

import android.annotation.SuppressLint
import android.content.Context
import android.os.Build

/**
 * License 强制策略：决定 license 校验失败时 SDK 的行为。
 *
 * 注意：仅当 SDK 被「武装」（构建期注入了 license 公钥 `BuildConfig.LICENSE_PUBLIC_KEY_B64`）时
 * 本策略才生效。开发 / 内部构建（未注入公钥）下 SDK 处于
 * [TtsLicenseStatus.State.DEV_UNLICENSED]，不做任何校验、功能可用。
 */
enum class LicenseEnforcement {
    /**
     * 默认。license 缺失 / 验签失败 / 绑定不符 / 过期时，[TextToSpeechSdk.init] 与
     * [TextToSpeechSdk.createEngine] 抛 [TextToSpeechException]（errorCode 取自 [TtsErrorCode]
     * 的 `LICENSE_*` 段）。
     */
    ENFORCE,

    /**
     * 宽松。校验失败时不抛异常；[TextToSpeechSdk.licenseStatus] 返回
     * [TtsLicenseStatus.State.INVALID]，由业务方自行决定是否提示 / 降级。
     * 用于灰度上线或现场排障，不建议长期使用。
     */
    PERMISSIVE,
}

/**
 * License 运行状态快照。通过 [TextToSpeechSdk.licenseStatus] 查询，可用于在「关于」页展示
 * 授权客户 / 到期日 / 档位，或在排障时确认 SDK 当前是否被授权武装。
 *
 * 字段在 [State.LICENSED] 时全部有效；其他状态下文本字段可能为空。
 *
 * @property state 当前授权状态机，见 [State]
 * @property valid 是否处于已授权可用状态（等价于 `state == State.LICENSED`）
 * @property errorCode 校验错误码（取自 [TtsErrorCode]）；无错误时为 [TtsErrorCode.OK]
 * @property licenseId 授权编号（我方签发时分配）
 * @property customer 授权客户名
 * @property applicationId license 绑定的 applicationId
 * @property bundleName license 绑定的 HarmonyOS bundleName；Android 端通常等同或为空
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
data class TtsLicenseStatus(
    val state: State,
    val valid: Boolean,
    val errorCode: Int,
    val licenseId: String,
    val customer: String,
    val applicationId: String,
    val bundleName: String,
    val signingCertDigest: String,
    val deviceIdHashAlg: String,
    val deviceIdSaltId: String,
    val authorizedDeviceCount: Int,
    val maintenanceUntil: String,
    val issuedAt: String,
    val expiresAt: String,
    val installTier: String,
    val features: List<String>,
) {

    /** 授权状态机。 */
    enum class State {
        /** 尚未触发任何 license 校验（既未调用 [TextToSpeechSdk.init]，也未 createEngine）。 */
        NOT_INITIALIZED,

        /** SDK 未武装 license（构建期未注入公钥）。开发 / 内部构建，不做校验、功能可用。 */
        DEV_UNLICENSED,

        /** license 校验全部通过。 */
        LICENSED,

        /** license 校验失败。 */
        INVALID,
    }

    /** 该 license 是否授权了某个功能模块（[features] 包含 [feature]）。 */
    fun hasFeature(feature: String): Boolean = features.contains(feature)

    internal companion object {
        val NOT_INITIALIZED: TtsLicenseStatus = TtsLicenseStatus(
            state = State.NOT_INITIALIZED,
            valid = false,
            errorCode = TtsErrorCode.OK,
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
 * 初始化 license 校验的选项。
 *
 * @property license 直接传入的 `.lic` 文件全文（优先于 [licenseAssetName]）；null 表示走 asset
 * @property licenseAssetName app assets 内 `.lic` 文件名，默认 `amphion-license.lic`；
 *   置 null / 空表示不从 asset 读取。仅当 SDK 被武装（构建期注入 license 公钥）时才会真正读取
 * @property expiryGraceDays 到期宽限天数（规避客户端时钟误差），默认 0；必须 >= 0
 * @property licenseEnforcement license 校验失败时的策略，默认 [LicenseEnforcement.ENFORCE]
 * @property deviceIdProvider 设备 SN 码提供方；默认通过系统序列号读取。license 包含设备白名单时必须能返回稳定 SN
 */
data class TtsLicenseOptions @JvmOverloads constructor(
    val license: String? = null,
    val licenseAssetName: String? = "amphion-license.lic",
    val expiryGraceDays: Int = 0,
    val licenseEnforcement: LicenseEnforcement = LicenseEnforcement.ENFORCE,
    val deviceIdProvider: TtsDeviceIdProvider? = TtsSystemDeviceIdProvider,
) {
    init {
        require(expiryGraceDays >= 0) { "expiryGraceDays must be >= 0, got $expiryGraceDays" }
    }
}

/**
 * License 设备绑定用 SN 码提供方。
 */
fun interface TtsDeviceIdProvider {
    fun getDeviceSerial(context: Context): String?
}

/**
 * 鼎桥 Android 交付默认 SN 来源。系统应用具备 `READ_PRIVILEGED_PHONE_STATE` 时，
 * [Build.getSerial] 返回的序列号应与 `adb devices` 展示的设备序列号一致。
 */
object TtsSystemDeviceIdProvider : TtsDeviceIdProvider {
    override fun getDeviceSerial(context: Context): String? = readDeviceSerial()

    @SuppressLint("HardwareIds", "MissingPermission")
    private fun readDeviceSerial(): String? =
        runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                Build.getSerial()
            } else {
                @Suppress("DEPRECATION")
                Build.SERIAL
            }
        }.getOrNull()
            ?.trim()
            ?.takeUnless { it.isBlank() || it.equals(Build.UNKNOWN, ignoreCase = true) }
}
