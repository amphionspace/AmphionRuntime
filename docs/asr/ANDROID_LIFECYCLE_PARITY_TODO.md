# Android ASR lifecycle parity status

Reviewed against the Harmony lifecycle fixes on 2026-07-18. The code-level parity work below is now
implemented on Android; Android device stress remains a release gate and is not implied by unit-test
completion.

## Implemented

- [x] Bind queued Dingqiao callbacks to a per-session generation and recheck ownership after customer
  listeners return. In particular, a last `onResult` callback must permit
  `cancel(old) -> startListening(new)` without an old completion or `ENGINE_BUSY` contaminating the
  replacement session.
- [x] Bind engine-level asynchronous errors to an engine epoch so callbacks queued before shutdown or a
  session replacement cannot arrive in the new state.
- [x] Treat omitted and non-finite `maxAudioDuration` as disabled; only an explicit positive finite value may
  auto-finish a session.
- [x] Compute `speakerSimilarity` eligibility from fixed-window effective speech rather than raw VAD
  segments, which contain leading context. Native VAD may retain low-volume candidate PCM, but a
  non-empty ASR text/token result remains the final scoring gate; steady high-energy non-speech and
  empty ASR finals must not receive a score.
- [x] When ASR creates an endpoint inside a PCM chunk, do not replay that old chunk into the reset VAD or
  count it toward the next utterance.
- [x] Reserve the bounded `vadBegin` confirmation window when `voiceprintIds` provision runtime Speaker
  VAD capability, including enablement from inside `onStart`.

## Acceptance gate

Unit coverage must include same-session-id reuse, last-result reentry, queued errors after shutdown,
omitted/NaN duration, short/exact/long effective speech, VAD segment padding, token-only native
segments, and endpoint chunk ownership.

Before changing the Android delivery version, run the SDK device modes for `max-duration`, `cancel`,
`reentrant`, `start-write`, `voiceprint-fallback`, and `voiceprint-vad-begin`. Each normal session must
produce exactly one last result followed by one complete; cancel must produce neither.

## Device verification

The focused Android parity gate passed on 2026-07-19 using a Vivo V2505A running Android 16:
`max-duration`, `cancel`, `reentrant`, both `start-write` paths, `voiceprint-fallback`, and
`voiceprint-vad-begin`. A 25-cycle terminal-callback reentry run also passed over approximately
99 seconds. The later expanded run and filtered evidence are retained in the local validation
archive; device identifiers and unfiltered system logs are intentionally excluded from version
control.

The Vivo process freezer suspends instrumentation processes that have no visible activity. Device
tests on this model must bring the demo `MainActivity` to the foreground after instrumentation starts;
the observed `cgroup.freeze` value changed from `1` to `0` when the activity became visible.
