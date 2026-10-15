package com.amphion.asr.internal

import com.amphion.asr.AsrErrorCode
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

class EnterpriseLicensePolicyTest {
    private val issued = 1792022400L
    private fun claims() = JSONObject()
        .put("authorizationVersion", 1).put("authorizationId", "contract")
        .put("generation", 1).put("issuedAtUnix", issued).put("notBeforeUnix", issued)
        .put("expiresAtUnix", issued + 600).put("graceSeconds", 3600)
        .put("activationMode", "online_lease").put("platformScope", "selected")
        .put("runtime", "android_arm64")

    private fun reject(value: JSONObject, now: Long, expected: Int) {
        try {
            EnterpriseLicensePolicy.validate(value.toString(), now * 1000)
            fail("invalid policy accepted")
        } catch (error: EnterpriseLicensePolicy.Rejected) {
            assertEquals(expected, error.code)
        }
    }

    @Test fun leaseAndGraceUseExactSeconds() {
        EnterpriseLicensePolicy.validate(claims().toString(), (issued + 4199) * 1000)
        reject(claims(), issued + 4200, AsrErrorCode.LICENSE_EXPIRED)
        reject(claims(), issued + 4201, AsrErrorCode.LICENSE_EXPIRED)
    }

    @Test fun invalidPlatformGenerationAndFutureIssueAreRejected() {
        reject(claims().put("runtime", "ios_arm64"), issued, AsrErrorCode.LICENSE_MALFORMED)
        reject(claims().put("generation", 0), issued, AsrErrorCode.LICENSE_MALFORMED)
        reject(claims().put("issuedAtUnix", issued + 1), issued, AsrErrorCode.LICENSE_MALFORMED)
        reject(claims().put("graceSeconds", 604801), issued, AsrErrorCode.LICENSE_MALFORMED)
        EnterpriseLicensePolicy.validate(claims().put("platformScope", "all_supported").toString(), issued * 1000)
    }

    @Test fun contractExpiryCapsGraceAndOfflineExpiryHasNoExtraDay() {
        reject(claims().put("entitlementExpiresAtUnix", issued + 601), issued + 601, AsrErrorCode.LICENSE_EXPIRED)
        reject(claims().put("activationMode", "offline_file").put("graceSeconds", 0), issued + 600, AsrErrorCode.LICENSE_EXPIRED)
        EnterpriseLicensePolicy.validate(JSONObject().put("expiresAt", "2099-01-01").toString(), issued * 1000)
    }
}

