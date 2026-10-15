package com.amphion.dingqiao

import android.os.Looper
import android.util.AtomicFile
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID

/**
 * Optional HTTPS authorization client. Call on a background thread, then activate
 * the downloaded file with setLicense before preparing an ASR/TTS engine.
 * Inference itself remains offline. The host must declare INTERNET permission.
 */
class EnterpriseLicenseClient(baseUrl: String) {
    /** Persist with the host's secure credential storage; never log the device token. */
    class Activation(val deviceId: String, val token: String)

    private val base = URL(baseUrl).also {
        require(it.protocol == "https" && it.host.isNotBlank() && it.userInfo == null &&
            it.query == null && it.ref == null && it.path in listOf("", "/")) { "HTTPS origin required" }
    }

    fun activate(code: String, machineFingerprint: String, destination: File, timeoutMillis: Long = 120000): Activation {
        backgroundOnly()
        require(timeoutMillis in 1000L..300000L)
        val response = json("/activation/v1/activate", null, JSONObject()
            .put("activation_code", code).put("machine_fingerprint", machineFingerprint))
        val activation = Activation(response.getJSONObject("device").getString("id"), response.getString("device_token"))
        download(activation, destination, timeoutMillis)
        return activation
    }

    fun renew(activation: Activation, machineFingerprint: String, destination: File, timeoutMillis: Long = 120000): Long {
        backgroundOnly()
        require(timeoutMillis in 1000L..300000L)
        val current = json(devicePath(activation) + "/license", activation.token)
        val generation = current.getJSONObject("device").getLong("generation")
        json(devicePath(activation) + "/renew", activation.token, JSONObject()
            .put("machine_fingerprint", machineFingerprint).put("expected_generation", generation))
        return download(activation, destination, timeoutMillis)
    }

    fun download(activation: Activation, destination: File, timeoutMillis: Long = 120000): Long {
        backgroundOnly()
        require(timeoutMillis in 1000L..300000L)
        val deadline = android.os.SystemClock.elapsedRealtime() + timeoutMillis
        while (android.os.SystemClock.elapsedRealtime() < deadline) {
            val response = json(devicePath(activation) + "/license", activation.token)
            val device = response.getJSONObject("device")
            check(device.getString("status") == "active") { "device authorization is inactive" }
            val license = response.getJSONObject("license")
            when (license.getString("status")) {
                "verified", "delivered" -> {
                    val generation = device.getLong("generation")
                    check(generation == license.getLong("generation")) { "license generation mismatch" }
                    val ticket = json(devicePath(activation) + "/license-downloads", activation.token,
                        JSONObject().put("expected_generation", generation))
                    val path = ticket.getString("download_url")
                    check(path.matches(Regex("/activation/v1/license-downloads/[a-f0-9-]{36}"))) { "invalid download path" }
                    val content = request(path, ticket.getString("download_token"), null)
                    val digest = MessageDigest.getInstance("SHA-256").digest(content).joinToString("") { "%02x".format(it.toInt() and 255) }
                    check(digest == license.getString("artifact_sha256")) { "license integrity check failed" }
                    val atomic = AtomicFile(destination)
                    val stream = atomic.startWrite()
                    try {
                        stream.write(content)
                        atomic.finishWrite(stream)
                    } catch (error: Throwable) {
                        atomic.failWrite(stream)
                        throw error
                    }
                    return generation
                }
                "failed", "revoked" -> error("license issuance failed")
            }
            Thread.sleep(500)
        }
        error("license issuance timed out")
    }

    private fun devicePath(activation: Activation): String {
        require(activation.deviceId.matches(Regex("[a-f0-9-]{36}")))
        return "/activation/v1/devices/" + activation.deviceId
    }

    private fun json(path: String, token: String?, body: JSONObject? = null) =
        JSONObject(String(request(path, token, body), Charsets.UTF_8))

    private fun request(path: String, token: String?, body: JSONObject?): ByteArray {
        val connection = URL(base, path).openConnection() as HttpURLConnection
        try {
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15000
            connection.readTimeout = 30000
            connection.useCaches = false
            connection.setRequestProperty("Accept", "application/json")
            connection.setRequestProperty("X-Request-ID", UUID.randomUUID().toString())
            if (token != null) connection.setRequestProperty("Authorization", "Bearer " + token)
            if (body != null) {
                connection.requestMethod = "POST"
                connection.setRequestProperty("Idempotency-Key", UUID.randomUUID().toString())
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            }
            check(connection.responseCode in 200..299) { "authorization HTTP " + connection.responseCode }
            return connection.inputStream.use { input ->
                val output = ByteArrayOutputStream()
                val buffer = ByteArray(8192)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    check(output.size() + count <= 1048576) { "authorization response too large" }
                    output.write(buffer, 0, count)
                }
                output.toByteArray()
            }
        } finally {
            connection.disconnect()
        }
    }

    private fun backgroundOnly() {
        check(Looper.myLooper() != Looper.getMainLooper()) { "authorization requires a background thread" }
    }
}

