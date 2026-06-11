package com.amphion.dingqiao.demo

import android.content.Context
import com.amphion.dingqiao.SpeechRecognizeSdk

/** Demo 层声纹 ID 与 SDK [SpeechRecognizeSdk.deleteVoiceprint] 同步。 */
object VoiceprintHelper {

    fun registeredId(context: Context): String? = DemoPrefs.getVoiceprintId(context)

    /**
     * 删除 SDK 持久化声纹并清空本地记录的 voiceprintId。
     * @return 被删除的 ID；无已注册 ID 时返回 null
     */
    fun deleteRegistered(context: Context): String? {
        val id = DemoPrefs.getVoiceprintId(context) ?: return null
        SpeechRecognizeSdk.deleteVoiceprint(id)
        DemoPrefs.setVoiceprintId(context, null)
        return id
    }

    /** 注册新声纹前，若已有 ID 则先删除，避免 workPath 下残留旧 embedding。 */
    fun deleteRegisteredIfAny(context: Context) {
        val id = DemoPrefs.getVoiceprintId(context) ?: return
        try {
            SpeechRecognizeSdk.deleteVoiceprint(id)
        } catch (_: Throwable) {
            // 旧 ID 可能已被手动删过，继续注册
        }
        DemoPrefs.setVoiceprintId(context, null)
    }
}
