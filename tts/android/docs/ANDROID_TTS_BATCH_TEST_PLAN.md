# Android TTS Batch Test Plan

## Goal

Build an instrumentation-based APK test harness for the TTS SDK service. The expanded batch contains at least 200 categorized cases and focuses on:

- Service stability: engine lifecycle, repeated requests, preemption, stop/shutdown, and no uncaught crash.
- Streaming performance: first packet latency, synthesis latency, audio duration, RTF, chunk count, and model path.
- Functional completeness: language/voice query, speak parameter validation, play type behavior, queue/preempt behavior, and SDK documented edge cases.
- Edge coverage: empty/overlong text, mixed Chinese-English, numbers, punctuation, long text, speed clamp, invalid pitch/volume/audioType/languageContext, duplicate requestId, and stop/preempt.

## Execution Model

The harness is an Android instrumentation test under `sdk/src/androidTest`.

- Runs inside the Android test runner, directly calling the SDK public API.
- Writes machine-readable output to the app external files directory:
  - `tts-batch-results.jsonl`
  - `tts-batch-summary.json`
- Uses `SYNTHESIZE_ONLY` for most performance cases to measure SDK streaming callback latency without AudioTrack playback variability.
- Uses a small number of `SYNTHESIZE_AND_PLAY` cases to validate SDK internal playback completion.
- Keeps request IDs globally unique to validate duplicate behavior separately.

## Metrics

Per case:

- `status`: `PASS`, `EXPECTED_ERROR`, `FAIL`, or `TIMEOUT`
- `language`, `voiceId`, `playType`, `queueMode`
- `textLength`, `speed`, `pitch`, `volume`, `languageContext`
- `startLatencyMs`: submit to `onStart`
- `firstPacketMs`: `onStart` to first `onData` or SDK-reported value
- `synthesisMs`, `audioDurationMs`, `rtf`
- `chunkCount`, `bytes`, `sampleRate`, `dataPath`, `modelInfo`, `profilingInfo`
- `errorCode`, `errorMessage`
- `category`: generated case family, used to see which edge dimension failed or slowed down.

Summary:

- Total/pass/fail/timeout/expected-error counts.
- Counts grouped by `category`.
- First-packet p50/p90/max.
- RTF p50/p90/max.
- Slowest cases and failed cases.

## Expanded Batch Matrix

Functional and performance:

- At least 200 total cases per run.
- Chinese text families: greeting, question, command, temperature, time, date, money, percent, address, phone, code, URL, email, punctuation, parentheses, quotes, lists, units, mixed English, AI/product terms, repeated words, polyphonic Chinese, short utterances, spaces, full-width text, symbols, fractions, ordinals, IDs, license plates, stocks, weather, navigation, reminders, dialogue, medium text, and longer repeated text.
- English text families: greeting, question, command, time, date, money, percent, address, phone, code, URL, email, punctuation, parentheses, product terms, repeated words, short utterances, USB, speed, chunking, and medium/longer text.
- Generated compact cases: more than 100 short cases mixing sequence numbers, negative/decimal temperatures, times, IDs, percentages, money, path-like text, and Chinese-English fragments.
- Speed values: normal and boundary/clamp values `0.1`, `0.25`, `0.49`, `0.5`, `0.75`, `1.0`, `1.25`, `1.5`, `2.0`, `2.01`, `3.0`, `4.0`, `NaN`, and `Infinity`.
- Pitch/volume success values: representative in-range values around `0.6`, `0.8`, `1.0`, `1.2`, and `1.5`.
- Chunk sizes in the pass/fail batch: `16`, `32`, `50`, `64`, `100`, `128`, `256`, `512`, and `1024`.
- Dangerous streaming chunk sizes below `16` are tracked as a discovered crash risk instead of regular expected-success cases, because `chunkSize=1/2/8` can feed an invalid condition-encoder input shape into ONNX Runtime.
- PCM queue capacities: `1`, `2`, `4`, `8`, `16`, and `32`.
- Queue modes: mostly `PREEMPT`, plus selected sequential `QUEUE` cases.
- `SYNTHESIZE_ONLY` and selected `SYNTHESIZE_AND_PLAY`.

Error and lifecycle:

- Empty/blank/control-whitespace text.
- Overlong text > 10000 chars at several lengths.
- Invalid pitch and volume below/above allowed range, including `NaN` and infinity.
- Invalid audioType values such as `wav`, `mp3`, `aac`, `pcm16`, uppercase/blank/space-padded variants.
- Invalid languageContext values such as `ja-JP`, `fr-FR`, `zh`, `en`, `zh-TW`, blank, uppercase, and space-padded variants.
- Duplicate requestId.
- Stop active long request.
- Preempt active long request.

## Pass Criteria

The batch test fails if:

- Any expected-success case times out, errors, or misses synthesis complete.
- Any expected-error case does not produce the expected error.
- Any case causes an uncaught crash or instrumentation failure.
- Engine creation/listVoices basic checks fail.

Performance thresholds are reported, not hard-failed in the first batch, because device thermal state strongly affects RTF. Suggested warning thresholds:

- First packet p90 > 1000 ms.
- RTF p90 > 1.0.
- Any single request timeout > 60 s.
