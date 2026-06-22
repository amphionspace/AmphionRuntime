package com.lits.tts.sdk.internal

internal data class LicenseClaims(
    val licenseId: String,
    val customer: String,
    val applicationId: String,
    val certSha256: String,
    val deviceSha256: String,
    val issuedAt: String,
    val expiresAt: String,
    val installTier: String,
    val features: List<String>,
    val sdkMajor: Int,
)
