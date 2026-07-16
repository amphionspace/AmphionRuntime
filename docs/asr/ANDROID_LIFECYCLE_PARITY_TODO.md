# Android ASR lifecycle parity TODO

Scope note: the 0.2.5 customer delivery is Harmony-only. The following Android work was found while
reviewing the shared ASR contract and is deliberately deferred instead of being mixed into the
Harmony release.

## Required follow-up

- Bind queued Dingqiao callbacks to a per-session generation and recheck ownership after customer
  listeners return. In particular, a last `onResult` callback must permit
  `cancel(old) -> startListening(new)` without an old completion or `ENGINE_BUSY` contaminating the
  replacement session.
- Bind engine-level asynchronous errors to an engine epoch so callbacks queued before shutdown or a
  session replacement cannot arrive in the new state.
- Treat omitted and non-finite `maxAudioDuration` as disabled; only an explicit finite value may
  auto-finish a session.
- Compute `speakerSimilarity` eligibility from fixed-window effective speech rather than raw VAD
  segments, which contain leading context. Native VAD or non-empty ASR output may confirm low-volume
  candidates; steady high-energy non-speech must still be rejected without that evidence.
- When ASR creates an endpoint inside a PCM chunk, do not replay that old chunk into the reset VAD or
  count it toward the next utterance.
- Reserve the bounded `vadBegin` confirmation window when `voiceprintIds` provision runtime Speaker
  VAD capability, including enablement from inside `onStart`.

## Acceptance gate

Add unit and Android-device coverage for same-session-id reuse, last-result reentry, queued errors
after shutdown, omitted/NaN duration, short/exact/long effective speech, VAD segment padding, and
endpoint chunk ownership before changing the Android delivery version.
