package com.lits.tts.sdk.internal

import org.junit.Assert.assertTrue
import org.junit.Test

class BundledResourceCompletenessTest {
    @Test fun restoredModelContainsEveryRuntimeRequiredResource() {
        val root = TtsTestAssets.root()
        val missing = LitsTtsAssetRegistry.files.filter { !root.resolve(it).isFile }
        assertTrue("Missing runtime resources: $missing", missing.isEmpty())
    }
}
