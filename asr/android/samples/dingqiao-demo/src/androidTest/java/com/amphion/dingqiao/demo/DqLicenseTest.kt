package com.amphion.dingqiao.demo

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.amphion.dingqiao.CreateEngineParams
import com.amphion.dingqiao.DingqiaoErrorCode
import com.amphion.dingqiao.DingqiaoOnlineMode
import com.amphion.dingqiao.LicenseActivationCallback
import com.amphion.dingqiao.LicenseActivationResult
import com.amphion.dingqiao.SpeechRecognizeSdk
import java.io.File
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters

/**
 * 离线 License 运行时激活（setLicense）corner-case：正向激活、到期、损坏和缺文件。
 * 同时验证资产 license 生效后 getLicenseInfo 能回落返回 runtime 授权信息。
 *
 * 正向授权复用 Demo APK 内置的 amphion-license.lic；androidTest 只保留时间无关的负向样本。
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class DqLicenseTest {

    private val ctx: Context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val testCtx: Context get() = InstrumentationRegistry.getInstrumentation().context

    private data class Activation(val code: Int, val remainingDays: Int?, val features: List<String>?, val errMsg: String?)

    private fun setLicense(assetName: String): Activation {
        val path = stageAsset(testCtx, ctx, "licenses/$assetName", "lic/$assetName")
        return setLicensePath(path)
    }

    private fun setBundledLicense(): Activation = setLicensePath(stageRuntimeLicense(ctx))

    private fun setLicensePath(path: String): Activation {
        val latch = CountDownLatch(1)
        var code = -999
        var remaining: Int? = null
        var features: List<String>? = null
        var msg: String? = null
        SpeechRecognizeSdk.setLicense(path, object : LicenseActivationCallback {
            override fun onResult(result: LicenseActivationResult) {
                code = result.errorCode; remaining = result.remainingDays; features = result.authorizedFeatures; latch.countDown()
            }
            override fun onError(errorCode: Int, errorMessage: String) {
                code = errorCode; msg = errorMessage; latch.countDown()
            }
        })
        latch.await(20, TimeUnit.SECONDS)
        return Activation(code, remaining, features, msg)
    }

    // ---------- L01: 资产 license 已授权且 getLicenseInfo 可读 ----------
    @Test
    fun L01_assetLicensed_engineWorks_andInfoReadable() {
        prepareSdkRuntime(
            ctx,
            File(ctx.getExternalFilesDir(null), "dq_lic_work"),
        )
        val engine = SpeechRecognizeSdk.createEngine(
            CreateEngineParams(language = "zh-CN", online = DingqiaoOnlineMode.OFFLINE),
        )
        try {
            val info = SpeechRecognizeSdk.getLicenseInfo()
            DqReport.append(ctx, mapOf(
                "case" to "L01_infoReadableWhileAssetLicensed",
                "infoStatus" to info.status,
                "infoFeatures" to info.authorizedFeatures.toString(),
            ))
            assertEquals("asset license should be active", 0, info.status)
            assertTrue("asset license should include ASR", info.authorizedFeatures.contains("ASR"))
        } finally {
            engine.shutdown()
        }
    }

    // ---------- L10: 合法 demo license ----------
    @Test
    fun L10_setValid_ok() {
        val a = setBundledLicense()
        val info = runCatching { SpeechRecognizeSdk.getLicenseInfo() }.getOrNull()
        DqReport.append(ctx, mapOf("case" to "L10_valid", "code" to a.code, "remainingDays" to a.remainingDays,
            "features" to a.features?.toString(), "infoStatus" to info?.status, "infoFeatures" to info?.authorizedFeatures?.toString()))
        assertEquals("valid license should activate", 0, a.code)
        assertTrue("features should contain ASR", a.features?.contains("ASR") == true)
    }

    // ---------- L20: 过期 ----------
    @Test
    fun L20_setExpired() {
        val a = setLicense("expired.lic")
        DqReport.append(ctx, mapOf("case" to "L20_expired", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_EXPIRED, a.code)
    }

    // ---------- L80: 损坏信封 ----------
    @Test
    fun L80_setMalformed() {
        val a = setLicense("malformed.lic")
        DqReport.append(ctx, mapOf("case" to "L80_malformed", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_INVALID, a.code)
    }

    // ---------- L85: 路径不存在 ----------
    @Test
    fun L85_setMissingPath() {
        val a = setLicensePath(File(ctx.filesDir, "no_such.lic").absolutePath)
        DqReport.append(ctx, mapOf("case" to "L85_missingPath", "code" to a.code, "msg" to a.errMsg))
        assertEquals(DingqiaoErrorCode.LICENSE_FILE_UNREADABLE, a.code)
    }

    // ---------- L90: 恢复合法 license，便于后续类复用 ----------
    @Test
    fun L90_restoreValid() {
        val a = setBundledLicense()
        DqReport.append(ctx, mapOf("case" to "L90_restoreValid", "code" to a.code))
        assertEquals(0, a.code)
    }
}
