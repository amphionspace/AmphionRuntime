package com.amphion.asr.sample.eval.data

import android.content.Context
import android.content.SharedPreferences
import java.security.MessageDigest
import java.util.UUID

/**
 * 测试员身份的轻量持久化（无登录系统）。
 *
 * 设计要点：
 * - tester_id 从 nickname 派生：`sha1(nickname)[:12]`，相同 nickname 在不同设备能聚合，避免要求测试员手动协调
 * - 不存敏感字段；nickname 只是 UI 展示，tester_id 才是数据归属 key
 * - 第一次进入评估模式时 EvalActivity 会强制弹 dialog 让用户填 nickname
 */
class TesterPrefs(ctx: Context) {

    private val sp: SharedPreferences =
        ctx.applicationContext.getSharedPreferences(PREF_NAME, Context.MODE_PRIVATE)

    fun isConfigured(): Boolean =
        !sp.getString(KEY_NICKNAME, null).isNullOrBlank() &&
            !sp.getString(KEY_TESTER_ID, null).isNullOrBlank()

    fun nickname(): String = sp.getString(KEY_NICKNAME, "") ?: ""

    fun testerId(): String = sp.getString(KEY_TESTER_ID, "") ?: ""

    /**
     * 设置 nickname。tester_id 由 nickname 派生；同一 nickname 派生出来的 id 在不同设备上一致，
     * 便于后台聚合"同一测试员跨多机型"的数据。
     *
     * @return 派生后的 tester_id
     */
    fun setNickname(nickname: String): String {
        val trimmed = nickname.trim()
        require(trimmed.isNotEmpty()) { "nickname cannot be empty" }
        val tid = deriveTesterId(trimmed)
        sp.edit()
            .putString(KEY_NICKNAME, trimmed)
            .putString(KEY_TESTER_ID, tid)
            .apply()
        return tid
    }

    /** 清空当前测试员信息（仅 EvalActivity 的 Toolbar「切换测试员」入口调用）。 */
    fun clear() {
        sp.edit().clear().apply()
    }

    companion object {
        private const val PREF_NAME = "amphion_eval_tester"
        private const val KEY_NICKNAME = "nickname"
        private const val KEY_TESTER_ID = "tester_id"

        /**
         * 把 nickname 做 sha1 取前 12 字符作为 tester_id。
         *
         * 取 sha1 而非 UUID 的理由：相同 nickname 在不同设备上必须派生出相同 id，否则
         * 后台无法把"alice 在 Pixel 7"和"alice 在 Mi 13"两批数据聚合在一个 tester 维度。
         *
         * 12 字符 = 48 位 hex，碰撞概率对几十个测试员场景可忽略。
         */
        fun deriveTesterId(nickname: String): String {
            val md = MessageDigest.getInstance("SHA-1")
            val hex = md.digest(nickname.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }
            return hex.substring(0, 12)
        }

        /**
         * 调试 / 后备用：生成一个完全随机的 tester_id（不绑定 nickname）。
         * 当前流程没用到，预留给将来"无 nickname 匿名提交"场景。
         */
        @Suppress("unused")
        fun randomTesterId(): String = UUID.randomUUID().toString().substring(0, 12)
    }
}
