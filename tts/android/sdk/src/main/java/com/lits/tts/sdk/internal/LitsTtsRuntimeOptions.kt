package com.lits.tts.sdk.internal

internal object LitsTtsRuntimeOptions {
    @Volatile
    var parallelOrtCreate: Boolean = true

    @Volatile
    var streamingFirstChunkSize: Int = 25

    @Volatile
    var streamingSecondChunkSize: Int = 50

    @Volatile
    var streamingSteadyChunkSize: Int = 100

    @Volatile
    var streamingChunkGrowthFactor: Int = 2

    @Volatile
    var streamingMaxChunkSize: Int = 200

    @Volatile
    var streamingMelCacheLen: Int = 16

    /** Decoder input left context in mel frames for the no-state-cache path. */
    @Volatile
    var decoderLeftContextFrames: Int = 16

    /** Explicit decoder-step state cache stays opt-in; the default path is cache-free. */
    @Volatile
    var decoderCacheEnabled: Boolean = false

    /**
     * When true, engine preload runs one tiny streaming synthesis right after the
     * ORT sessions are created, paying each session's first-run fixed cost
     * (MLAS thread-pool spin-up, arena allocation) inside createEngine instead of
     * on the user's first speak.
     */
    @Volatile
    var ortWarmupOnCreate: Boolean = false

    /** Per-session intra-op thread counts. Default 1 keeps the legacy behavior. */
    @Volatile
    var hiddenEncoderThreads: Int = 1

    @Volatile
    var conditionEncoderThreads: Int = 1

    @Volatile
    var decoderStepThreads: Int = 1

    @Volatile
    var vocoderThreads: Int = 1
}
