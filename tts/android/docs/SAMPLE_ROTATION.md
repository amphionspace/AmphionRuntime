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

Repeat using the Speak button (`--start 119 292`) to cover streaming playback.
The check requires callbacks from the same request after landscape and portrait
transitions, rejects unexpected stop/error/completion or Activity restart, and
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
