package com.lits.tts.sdk.internal

/** The trained KV-cache path must never silently fall back to window decoding. */
internal object IntMeanFlowStreamingContract {
    const val CACHE_MODE = "intmeanflow_absolute_kv_v1"

    fun requiresCache(manifest: LitsTtsAssetInstaller.ManifestInfo): Boolean =
        manifest.streamDecoderCacheInfo?.mode == CACHE_MODE

    fun validate(
        manifest: LitsTtsAssetInstaller.ManifestInfo,
        chunkSize: Int?, flowStep: Int?, previousContext: Int?,
        firstChunkSize: Int?, secondChunkSize: Int?, steadyChunkSize: Int?,
        growthFactor: Int?, maxChunkSize: Int?,
    ) {
        require(manifest.supportsStreaming && manifest.streamDecoderExternalLoop &&
            manifest.streamingChunkSize in setOf(50, 100) && manifest.streamDecoderTimesteps == 2 &&
            manifest.streamingPreLookaheadLen == 0 && manifest.streamDecoderTemperature.isFinite() &&
            manifest.streamDecoderTemperature >= 0f &&
            manifest.streamDecoderCacheInfo?.requiresFixedChunkSize == manifest.streamingChunkSize) {
            "Invalid IntMeanFlow streaming manifest"
        }
        require(listOf(chunkSize, firstChunkSize, secondChunkSize, steadyChunkSize, maxChunkSize)
            .all { it == null || it == manifest.streamingChunkSize }) { "This student requires ${manifest.streamingChunkSize}-frame chunks" }
        require(flowStep == null || flowStep == 2) { "This student requires two trained flow steps" }
        require(previousContext == null || previousContext == 0) { "This student carries history through KV cache" }
        require(growthFactor == null || growthFactor == 1) { "This student does not support chunk growth" }
    }
}
