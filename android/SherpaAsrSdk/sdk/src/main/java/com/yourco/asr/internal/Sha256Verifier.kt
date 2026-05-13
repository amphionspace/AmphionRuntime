package com.yourco.asr.internal

import java.io.File
import java.io.FileInputStream
import java.security.MessageDigest

internal object Sha256Verifier {

    private const val BUF_SIZE = 1 shl 20  // 1 MB

    fun compute(file: File): String {
        val md = MessageDigest.getInstance("SHA-256")
        FileInputStream(file).use { fis ->
            val buf = ByteArray(BUF_SIZE)
            while (true) {
                val n = fis.read(buf)
                if (n <= 0) break
                md.update(buf, 0, n)
            }
        }
        return md.digest().joinToString("") { "%02x".format(it) }
    }

    fun matches(file: File, expected: String): Boolean {
        if (!file.isFile) return false
        return compute(file).equals(expected, ignoreCase = true)
    }
}
