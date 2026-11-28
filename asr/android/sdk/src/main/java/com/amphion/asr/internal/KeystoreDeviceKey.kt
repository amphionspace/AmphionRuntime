package com.amphion.asr.internal

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

/**
 * AndroidKeyStore 内的设备密钥（EC P-256，私钥不可导出）。用于激活请求、运行时持有证明与注销回执。
 * 恢复出厂/清除应用数据会删除密钥，设备需重新激活（签发点按同 SN 沿用原序号，不多占名额）。
 */
internal class KeystoreDeviceKey(private val alias: String = DEFAULT_ALIAS) : QuotaChainVerifier.DeviceKey {

    private val ks: KeyStore = KeyStore.getInstance(PROVIDER).apply { load(null) }

    fun exists(): Boolean = ks.containsAlias(alias)

    /** 首次激活时调用；已存在则复用。 */
    fun ensure() {
        if (exists()) return
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, PROVIDER)
        gen.initialize(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
                .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
                .setDigests(KeyProperties.DIGEST_SHA256)
                .build(),
        )
        gen.generateKeyPair()
    }

    override fun publicKeySpki(): ByteArray =
        ks.getCertificate(alias)?.publicKey?.encoded ?: throw IllegalStateException("device key missing")

    override fun sign(challenge: ByteArray): ByteArray {
        val key = ks.getKey(alias, null) as? PrivateKey ?: throw IllegalStateException("device key missing")
        return Signature.getInstance("SHA256withECDSA").run { initSign(key); update(challenge); sign() }
    }

    /** 注销：调用方先用 [sign] 签好回执，再调用本方法销毁密钥。 */
    fun destroy() {
        if (exists()) ks.deleteEntry(alias)
    }

    companion object {
        private const val PROVIDER = "AndroidKeyStore"
        const val DEFAULT_ALIAS = "amphion.quota.device.v1"
    }
}
