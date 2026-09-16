# Student 10000, teacher-matched 50-frame model (2026-09-16)

Checkpoint SHA-256:
`9310bf4338c73cfbcc5e32ed6ba1ee1e8e6dbddcf23f32996112d535c327154d`.
Matching training source: `LITs-distill-teacher-matched`, revision
`5fc895350ea22370dd3c1bfce93e45fceecd7e56`.

This replaces the previous 100-frame KV-distilled checkpoint. It keeps the
173-token inventory, two-step grid `[0, 0.5, 1]`, Vocos 24 kHz and inference
temperature 0. The model ID is
`dingqiao_intmeanflow_student_0010000_streaming_matched50_vocos24k`.

## Training and inference

`teacher_matched_streaming=true` selects one shared streaming/non-streaming
mode per training loss call, with probability 0.5. Condition and decoder masks
match the teacher. Training uses 50-frame blocks, 20-frame decoder history,
`mu_streaming=true`, and `kv_cache_distill=false`. The latter describes the
training loss; it does not prohibit cached inference. The supplied inference
script and `meanflow_distill/streaming_eval.py` support cached decoding.

Android uses that causal KV inference route, with 50-frame chunks matching this
checkpoint instead of the generic inference shell script's 100-frame default.
The hidden graph applies the stateless condition encoder over the text segment
with its streaming attention mask. It must not use either the old unmasked
condition encoder or repeated stateful `encode_mu` calls during ONNX tracing.
The decoder retains separate KV/convolution states for each of the two steps.
Remainders merge into the final chunk, as in the source helper. The manifest's
training/default chunk size is 50. Android also accepts a uniform inference
chunk override of at least 40 frames, including 75, 100, 150 and 200. Both
solver steps retain their independent caches at the requested size; there is
no fallback to window decoding. The exported condition attention mask remains
the original training mask; changing the decoder partition does not retrain or
re-export that encoder. The previous 100-frame bundle remains supported.

The legacy manifest field `requires_fixed_chunk_size` still records the original
export/default geometry for this cache mode. It no longer forces the requested
decoder chunk size to equal the training size. It remains a fixed-size restriction
for legacy cache modes. Different first/steady chunk sizes and chunk growth are
not enabled by this change.

The lower bound is an export limitation, not a training prohibition: the cached
step was traced with saturated 20-frame attention histories, including the 2x
downsampled level. Tests with 24/25-frame regular chunks diverged from PyTorch
after the first chunk; 40 frames and above passed the tested cases. Short
utterances/final tails remain supported. Do not remove the lower bound without
fixing and validating the exported cache-offset branches.

## Export and validation

Use `tts/tools/android/export_intmeanflow_streaming.py` with the matching source,
checkpoint and original frontend resources. The exporter selects the supported
training profile from checkpoint metadata and rejects inconsistent settings.
It verifies strict weight loading, token IDs, hidden output parity, and cached
ONNX decoding against the matching PyTorch source at lengths around the chunk
boundaries, plus longer multi-chunk sequences. This validates the exported
inference route; it is not a claim that cached inference equals the stateless
training forward or that perceptual quality improves.

Keep the original checkpoint and published bundle identities distinct: their
filenames and global step are the same, but their SHA-256 values differ.

## Variable chunk verification (2026-09-16)

`tts/tools/android/validate_intmeanflow_chunk_sizes.py` compares the existing
ONNX decoder with the same checkpoint's PyTorch cached inference, preserving
training context and changing only the inference partition. Sizes 40, 50, 75,
100, 150 and 200 passed first/tail/boundary and multi-chunk cases. This checks
ONNX/source parity at each size, not equality between different chunk sizes or
perceived quality. Local evidence: `work/logs/variable-chunks-validated.json`.

`VariableChunkDeviceTest` uses the public SDK on TECNO KI8, speaker 1,
temperature 0, with the same Chinese/English passage at 50/100/75/150 frames.
It checks the reported requested size, streaming callbacks and sequence order,
completion without error, multi-chunk output and equal total PCM length.
All four passed. Audio and timing results are retained in
`outputs/tts-variable-chunks-20260916/` in the parent workspace.
