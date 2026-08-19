# FULL vs PRUNE_UI28 Android performance gate

This gate compares two APKs built from the same Git tree and iter250 model assets. The only build
input that changes is `policeDefaultHotwordProfile`:

- `full`: 370 effective built-in hotwords; this remains the default when the property is omitted.
- `prune_ui28`: 342 effective built-in hotwords.

The property controls the profile used when the private experimental engine parameter is absent.
Consequently, both `prepareRuntime()` and the ordinary `createEngine(language="zh-CN")` call use the
same profile. Explicit `full`, `prune_ui28` and `none` experiment values still override the build
default.

## Device probe

`DqPoliceHotwordPerformanceInstrumentedTest` measures one real-time 16 kHz mono PCM utterance and
writes exactly one JSONL row under the target app's dedicated
`files/police_hotword_perf/report.jsonl`. Its SDK work path and staged test license are also below
`files/police_hotword_perf`, so the runner can remove only performance-owned state. It records:

- compiled profile, effective hotword count and effective-list SHA-256;
- `prepareRuntime`, `createEngineAsync` and `startListening -> onStart` wall time;
- first non-empty partial, final and complete wall time;
- process CPU time and CPU RTF;
- PSS and `/proc/self/status` VmRSS baseline, checkpoints, peak and unload values;
- final/last/error counts.

The SDK's existing `AmphionMetrics` logcat stream remains the source of `engineReadyMs`, SDK first
partial/E2E latency, post-process time, SDK RTF and RSS-at-ready. Note that its `nativeRssMb` field is
the process VmRSS, not a native-heap-only measurement.

The probe deliberately does not modify or call the general corpus evaluator. It uses the public
Dingqiao lifecycle and does not pass a runtime hotword profile.

## Repeatable ABBA run

Commit the source first. Then run from any directory:

```bash
export AUDIO_ASSET=known-partial-producing.wav
bash asr/android/reports/police-hotword-pruning-iter250-20260819/\
run_police_hotword_perf_abba.sh \
  /absolute/path/to/16k-wavs \
  /absolute/path/outside-the-repo/new-evidence-dir \
  2
```

`AUDIO_ASSET` is required and must name one WAV directly under the supplied directory. This keeps
every FULL/PRUNE run on exactly the same utterance and avoids accidentally selecting a bundled test
fixture. Optional environment variables:

```bash
export ANDROID_SERIAL=R28M40JBCLV
export DINGQIAO_DEMO_ASSET_DIR=/absolute/path/to/private/demo/assets
```

The runner:

1. refuses a dirty worktree unless `PERF_ALLOW_DIRTY=1` is explicitly set;
2. forces `-PdingqiaoUseFatAar=false`, then builds and hashes FULL and PRUNE_UI28 target/test APK
   pairs from project sources;
3. copies and hashes the exact audio, model manifest and profile-source hash inventory into the
   evidence directory, and binds those hashes into every artifact and run manifest; the analyzer
   re-hashes the named audio entry inside each test APK and requires it to match the evidence copy;
   it also streams every model payload from each target APK and verifies it against the manifest's
   `output_sha256` before computing a combined model-payload hash;
4. uses replacement install plus `force-stop`, and removes only `files/police_hotword_perf` before
   and after each measurement; all other target-App files, preferences, databases and external
   files remain untouched;
5. runs `FULL -> PRUNE -> PRUNE -> FULL` for each cycle and archives instrumentation output, SDK
   metrics, app JSONL, APKs, device identity, battery and thermal dumps;
6. hard-checks run-directory/meta/measurement/profile identity, complete per-profile samples for
   every gated metric, artifact hashes and effective hotword hashes;
7. generates overall median/p95 comparisons plus both within-cycle paired deltas.

The analyzer exits `0` only for PASS, `1` for FAIL and `2` for INCONCLUSIVE. A dirty override is
explicitly marked non-formal. Missing/negative gated samples, missing RSS, partial runs or broken
hash bindings cannot be silently summarized as zero or mistaken for a pass.

At present the analyzer always keeps an otherwise clean result at **INCONCLUSIVE** because thermal
dumps are archived but not automatically interpreted. A human thermal review is useful evidence,
but it does not change the machine status to PASS. Automated thermal validation must be added before
this becomes a release gate.

Use at least two ABBA cycles (four samples per profile). For a final decision, prefer three cycles,
keep the screen/power mode fixed, and wait for comparable battery temperature before each run.
Temperature skew above 3 °C or a thermal throttling state change makes the result inconclusive.

## Numeric checks

For each relative metric, PRUNE p95 must not exceed the larger of `FULL p95 * 1.05` and
`FULL p95 + noise floor`. Noise floors are 20 ms for latency, 0.02 for RTF, 10 MiB for SDK RSS and
10 MiB (10,240 KiB) for PSS/RSS deltas. Absolute PRUNE p95 limits are 500 ms for create and SDK
engine-ready, 500 ms for first-partial overhead, and 0.8 for process CPU RTF. Every gated metric
must have one finite, non-negative sample from every run in both profiles; otherwise the result is
INCONCLUSIVE rather than being computed from a smaller favorable subset.

## Build-only checks

The production-compatible default:

```bash
cd asr/android
./gradlew --no-daemon :sdk-police:testDebugUnitTest \
  -PpoliceDefaultHotwordProfile=full
```

Candidate build default:

```bash
cd asr/android
./gradlew --no-daemon :sdk-police:testDebugUnitTest \
  -PpoliceDefaultHotwordProfile=prune_ui28
```

Invalid values fail during Gradle configuration. Omitting the property is equivalent to `full`, so
rollback does not require deleting the FULL profile or restoring the 370-word list.

## Interpretation limits

- The instrumentation APK is a debug build. It is suitable for paired deltas, not an absolute
  release-build performance claim.
- The paced SDK RTF includes input sleeps and other wall-time effects.
- `cpuRtf` currently shares a run with the 50 ms PSS/RSS sampler. Sampling consumes process CPU, so
  CPU RTF is diagnostic only until CPU and memory probes are split; the analyzer records this as an
  explicit INCONCLUSIVE blocker.
- PSS/RSS are whole-process values and include the test carrier. Compare paired deltas, not the
  absolute number as pure SDK memory.
- RSS read failure is recorded as `-1` plus `rssAvailable=false`; it is never converted into a
  plausible-looking zero delta.
- The output directory should be outside the Git worktree. A clean worktree that changes during the
  run fails evidence-integrity validation.
