# Responsive sample and lifecycle

## Page / engine boundary

`MainActivity` binds widgets and forwards user actions to `TtsSampleViewModel`.
It does not create, stop or release SDK engines. The ViewModel owns the engine,
request callbacks, result audio, inputs and `SampleUiState`; it holds only the
application context, never an Activity or View.

Android selects `res/layout-small/activity_main.xml` on small screens and
`res/layout/activity_main.xml` on normal/larger screens. The IDs and actions are
shared; both show RSS and the process RSS high-water mark in MiB, updated once
per second while visible. These numbers include the entire process, not just
model tensors. The peak is since process start and includes cold loading.

Normal configuration recreation is enabled. Rotation reconnects the new page to
the same ViewModel, preserving the request, input and result. Closing the page
clears the ViewModel and shuts down the engine. Process death recovery and a
background playback service are outside this sample's contract.

## SDK release / cancellation

The previous Activity closed its engine on rotation. In addition to stopping
speech, native ORT inference sometimes crashed because engine shutdown closed
sessions before running workers returned. The playback producer could also
outlive `playStreaming` after cancellation.

Shutdown now marks requests cancelled immediately and returns without blocking
the UI. Resource release waits for all submitted workers, including preempted
workers, to exit. Streaming playback joins both producer and playback threads
before returning to that engine worker. A Java interrupt is not treated as proof
that JNI inference has ended.

Explicit cancellation is tracked separately from a player failure. A cancelled
playback does not require a complete synthesized result, and its late exception
cannot emit an error after Stop. Genuine uncancelled failures still emit errors.

## Regression evidence (EC521S, Android 10, 2026-09-16)

- JVM controlled native-work analogue: shutdown must not close a synthesizer
  while its noninterruptible operation is still running.
- JVM cancellation/error test: cancelled worker failure produces Stop only;
  a subsequent genuine failure still produces Error. Both failed before the fix.
- `TtsLifecycleDeviceTest`: real-model playback stop, synthesis shutdown and
  playback shutdown; each is followed by successful engine recreation and PCM
  synthesis, with exactly one Stop for each cancelled request and no late error.
- `SampleScreenDeviceTest`: both layout variants contain the RSS display and
  actions; Activity recreation preserves the same controller, edited input,
  active synthesis and completed result.
- Actual normal-phone hardware was not connected. Its layout is inflated in the
  device test, but normal-phone visual QA is not claimed.

For an additional manual rotation check on a provisioned, foreground sample with
long text, use `tts/tools/android/check_sample_rotation.py`. Supply visible
portrait button centres. Playback uses `--playback` (Android 10 AudioFlinger
format) rather than PCM callbacks, which streaming playback does not emit.
