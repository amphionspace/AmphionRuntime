# Sample rotation lifecycle

The sample handles `orientation|screenSize` changes in its existing Activity.
Both phone and small-screen layouts use flexible dimensions and the same view
tree in portrait and landscape; Android remeasures that tree on rotation.
There are no orientation-specific layouts to reinflate.

This preserves the engine, active request, PCM player, input and result while
rotating. Explicit Stop still cancels work. Actual Activity destruction still
releases resources. This change does not promise background playback across
process death or other configuration changes.

## Device regression

Provision the sample with its model and license, open it in portrait, wait for
warmup and use a long input. Run the following with the visible portrait button
centres (the example coordinates are for EC521S at 240 × 320):

```sh
python3 tts/tools/android/check_sample_rotation.py \
  --serial DSJ-TDTH6A10000336 --start 42 292 --stop 197 292 \
  --log /tmp/rotation-synthesis.log
```

Repeat using the Speak button (`--start 119 292 --playback`) to cover streaming
playback. Playback does not emit PCM callbacks: on Android 10 this check reads
the app's AudioFlinger track and requires its server frame position to advance
on the same track after each rotation.
The synthesis check requires callbacks from the same request after landscape and portrait
transitions. Both reject unexpected stop/error/completion or Activity restart, and
then verifies explicit Stop. It restores rotation settings and refuses to
overwrite existing logs. Run on a provisioned normal phone as well to validate
its actual screen geometry; EC521S alone is not evidence of phone visual QA.

Before the fix, EC521S emitted `onStop ... STOP_ALL` immediately on rotation
after the first audio chunk. The cause is Activity recreation invoking
`MainActivity.onDestroy`, which shuts down its engine.

## Related open issue: shutdown during native inference

During the original rotation reproduction on 2026-09-16, the engine thread also
crashed with SIGSEGV in `libonnxruntime.so` / `OrtSession.run` after shutdown.
Evidence is saved locally as `work/logs/rotation-before-native-crash.log` in the
parent workspace. Concurrent session release is suspected, not yet proven.
The rotation fix avoids that shutdown but does not fix or validate the general
SDK shutdown/inference race. Track that separately with a controlled active
inference → shutdown reproduction before changing SDK resource ownership.

## Related open issue: error following playback cancellation

EC521S playback validation also observed `onStop ... STOP_ALL` followed by
`onError ... 1002300011: streaming playback produced no synthesized audio`.
AudioFlinger confirmed zero active tracks after Stop. This extra error is a
separate cancellation-callback defect: the streaming playback path requires a
synthesized result even when cancellation ends the producer early. This patch
does not change SDK callbacks; fix and test that cancellation path separately.

## Validation on EC521S, Android 10 (2026-09-16)

- Old APK: same-request continuity assertion fails with STOP_ALL on rotation.
- Fixed APK: synthesis continues across landscape and portrait; explicit Stop
  produces its stop callback.
- Fixed APK: the same playback track advances across both rotations; explicit
  Stop produces its callback and leaves no active app audio track.
- Normal phone hardware was not connected; it uses the same Activity manifest,
  but its on-device rotation check remains unperformed.
- The playback checker was corrected to observe AudioFlinger rather than PCM
  callbacks, which are intentionally absent in streaming playback mode.
