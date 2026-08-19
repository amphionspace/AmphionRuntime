# FULL vs PRUNE_UI28 create-only ABBA probe

This is the focused follow-up for a noisy `createEngineAsync` result. It measures only:

1. one explicit `setLicense` followed by one `prepareRuntime`;
2. one `createEngineAsync(language="zh-CN")` against that prepared runtime.

It never starts recognition, feeds audio or starts a PSS/RSS sampler. The instrumentation test has
no create-time performance assertion; latency interpretation belongs to the host analyzer.

## Bootstrap isolation

The interactive Demo normally calls `setLicense` and `prepareRuntime` from
`DingqiaoApp.onCreate()`. That would preload the model before this test and produce two cold-load
events. The create-only build passes `-PdingqiaoCreateOnlyPerfRunner=true`, which registers the
dedicated `DqCreateOnlyPerfRunner`. That runner creates a plain `android.app.Application`, so only
the test performs bootstrap.

The report records the actual Application class and one prepare/create call. Structured phase logs
must prove, on one process PID, `prepare_start -> COLD_MODEL_LOAD -> prepare_end -> create_start ->
create_end`; the analyzer therefore rejects both a second bootstrap and a cold load deferred into
create. It also rejects a pooled-config mismatch. Omitting the Gradle property leaves every normal
Demo/test build on `AndroidJUnitRunner` and `DingqiaoApp`.

## Run five ABBA cycles

Commit the source first and choose a new output directory outside the Git worktree:

```bash
export ANDROID_SERIAL=R28M40JBCLV   # optional when adb has exactly one device
bash asr/android/reports/police-hotword-pruning-iter250-20260819/\
run_police_hotword_create_only_abba.sh \
  /absolute/path/to/new-create-only-evidence \
  5
```

The runner enforces at least five cycles. Every cycle is
`FULL -> PRUNE_UI28 -> PRUNE_UI28 -> FULL`, yielding two adjacent paired comparisons and one
cycle-level mean delta. Five cycles produce ten samples per profile.

Formal runs require a clean worktree. `PERF_ALLOW_DIRTY=1` permits diagnosis only and is recorded
as non-formal evidence.

## Evidence and summaries

Each run records run/cycle/position, compiled profile, effective hotword count and hash, target/test
APK hashes, verified model-manifest and model-payload hashes, wall/process-CPU time, battery
temperature, AP temperature and thermal status. Source profile/harness hashes bind both APK builds
to the same Git tree and model payload.

The analyzer writes `create-only-summary.json` and `create-only-summary.md` with:

- per-profile `n`, mean, median, min and max for prepare/create wall and CPU time;
- pair A, pair B and per-cycle mean PRUNE-minus-FULL deltas;
- summaries of those paired deltas;
- per-run battery/AP temperatures and thermal status.

With fewer than 20 samples per profile, p95 is explicitly omitted. Run ten or more cycles when a
real p95 is required; five-cycle results must be discussed using paired deltas, median, mean and
max. The analyzer does not impose an absolute create threshold: `PASS` means the evidence is bound,
complete and thermally comparable, not that a release performance policy passed.

## Device-data safety

The host runner forces source-module builds with `-PdingqiaoUseFatAar=false`, installs with
`adb install -r -t`, and uses `force-stop` between runs. It never clears package data or removes an
installed package. Only the dedicated private directory `files/police_hotword_create_only_perf` is
removed before and after a measurement; Demo preferences, databases, external files and the normal
`dingqiao_work` directory are left untouched.
