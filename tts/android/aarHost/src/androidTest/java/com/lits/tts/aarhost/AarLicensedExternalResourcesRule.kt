package com.lits.tts.aarhost

import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import com.lits.tts.sdk.TextToSpeechSdk
import com.lits.tts.sdk.TtsLicenseOptions
import com.lits.tts.sdk.TtsLicenseStatus
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.rules.TestRule
import org.junit.runner.Description
import org.junit.runners.model.Statement

/** Shared setup for the legacy batch/RTF entries; caller-owned resources are never removed. */
class AarLicensedExternalResourcesRule : TestRule {
    override fun apply(base: Statement, description: Description): Statement = object : Statement() {
        override fun evaluate() {
            val instrumentation = InstrumentationRegistry.getInstrumentation()
            val arguments = InstrumentationRegistry.getArguments()
            val workPath = requireNotNull(arguments.getString("workPath")?.takeIf { it.isNotBlank() }) {
                "Pass -e workPath <external model root>; batch tests do not create or clear model directories"
            }
            val licensePath = requireNotNull(arguments.getString("licensePath")?.takeIf { it.isNotBlank() }) {
                "Pass -e licensePath <private license file>"
            }
            val modelDirectory = File(workPath)
            require(modelDirectory.isDirectory && modelDirectory.canRead()) {
                "workPath must be an existing readable directory: $workPath"
            }
            val licenseFile = File(licensePath)
            require(licenseFile.isFile && licenseFile.canRead()) {
                "licensePath must be an existing readable file: $licensePath"
            }
            val licenseText = licenseFile.readText(Charsets.UTF_8)
            val context = instrumentation.targetContext
            val activity = instrumentation.startActivitySync(Intent(context, AarHostActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            try {
                TextToSpeechSdk.init(context, TtsLicenseOptions(
                    license = licenseText, licenseAssetName = null,
                ))
                val state = TextToSpeechSdk.licenseStatus().state
                assertEquals("Batch gate requires a licensed Release AAR", TtsLicenseStatus.State.LICENSED, state)
                TextToSpeechSdk.setWorkPath(workPath)
                println("AAR_BATCH_SETUP licenseState=${state.name}; workPath=$workPath; resources=preserved")
                base.evaluate()
            } finally {
                instrumentation.runOnMainSync { activity.finish() }
            }
        }
    }
}
