package com.amphion.asr.internal

import android.content.Context
import com.amphion.asr.AsrErrorCode
import org.json.JSONObject

/** Second-precision policy for Enterprise licenses; legacy offline licenses stay compatible. */
internal object EnterpriseLicensePolicy {
    class Rejected(val code: Int) : IllegalArgumentException("Enterprise license policy rejected")

    fun deadlineMillis(licenseText: String?): Long {
        if (licenseText.isNullOrBlank()) return Long.MAX_VALUE
        val envelope = JSONObject(licenseText)
        val payload = JSONObject(String(android.util.Base64.decode(envelope.getString("payload_b64"), android.util.Base64.NO_WRAP), Charsets.UTF_8))
        if (!payload.has("authorizationVersion")) return Long.MAX_VALUE
        val expiry = payload.getLong("expiresAtUnix")
        val leaseEnd = if (expiry == 0L) Long.MAX_VALUE else Math.multiplyExact(Math.addExact(expiry, payload.getLong("graceSeconds")), 1000L)
        val hardExpiry = payload.optLong("entitlementExpiresAtUnix", 0)
        return minOf(leaseEnd, if (hardExpiry == 0L) Long.MAX_VALUE else Math.multiplyExact(hardExpiry, 1000L))
    }

    fun validate(payload: String, nowMillis: Long): JSONObject {
        val value = JSONObject(payload)
        if (!value.has("authorizationVersion")) return value
        fun requirePolicy(condition: Boolean, code: Int = AsrErrorCode.LICENSE_MALFORMED) {
            if (!condition) throw Rejected(code)
        }
        requirePolicy(value.getInt("authorizationVersion") == 1)
        val issued = value.getLong("issuedAtUnix")
        val start = value.getLong("notBeforeUnix")
        val expiry = value.getLong("expiresAtUnix")
        val grace = value.getLong("graceSeconds")
        val mode = value.getString("activationMode")
        requirePolicy(issued > 0 && start >= issued && expiry >= 0 && (expiry == 0L || expiry > start))
        requirePolicy(value.getLong("generation") > 0 && value.getString("authorizationId").isNotBlank())
        requirePolicy(mode in setOf("offline_file", "online_once", "online_lease"))
        requirePolicy(grace in 0L..604800L && (mode == "online_lease" || grace == 0L))
        requirePolicy(mode != "online_lease" || expiry > 0)
        val scope = value.optString("platformScope", "")
        requirePolicy(scope in setOf("", "selected", "all_supported"))
        val runtime = value.getString("runtime")
        requirePolicy(runtime in setOf("android_arm64", "harmony_arm64", "ios_arm64"))
        requirePolicy(scope == "all_supported" || runtime == "android_arm64")
        val now = nowMillis / 1000
        requirePolicy(now >= issued && now >= start)
        requirePolicy(expiry == 0L || now < expiry || now - expiry < grace, AsrErrorCode.LICENSE_EXPIRED)
        val hardExpiry = value.optLong("entitlementExpiresAtUnix", 0)
        requirePolicy(hardExpiry == 0L || now < hardExpiry, AsrErrorCode.LICENSE_EXPIRED)
        return value
    }

    // Rollback protection is committed only by activation/runtime gates, never by validateLicense.
    fun checkGeneration(ctx: Context, value: JSONObject) {
        if (!value.has("authorizationVersion")) return
        val preferences = ctx.getSharedPreferences("amphion.enterprise.license.generations", Context.MODE_PRIVATE)
        if (value.getLong("generation") < preferences.getLong(value.getString("authorizationId"), 0)) {
            throw Rejected(com.amphion.asr.AsrErrorCode.LICENSE_MALFORMED)
        }
    }

    @Synchronized
    fun acceptGeneration(ctx: Context, payload: String) {
        val value = JSONObject(payload)
        if (!value.has("authorizationVersion")) return
        checkGeneration(ctx, value)
        val preferences = ctx.getSharedPreferences("amphion.enterprise.license.generations", Context.MODE_PRIVATE)
        val id = value.getString("authorizationId")
        val generation = value.getLong("generation")
        if (generation < preferences.getLong(id, 0)) throw Rejected(AsrErrorCode.LICENSE_MALFORMED)
        if (generation > preferences.getLong(id, 0) && !preferences.edit().putLong(id, generation).commit()) {
            throw Rejected(AsrErrorCode.LICENSE_MALFORMED)
        }
    }
}

