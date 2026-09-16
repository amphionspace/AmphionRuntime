# Sample memory and precision work (2026-09-16)

## FP32 runtime changes

- Dictionary text is retained as UTF-8 plus a compact row-offset hash index.
  Values are decoded only for lookups; small pronunciation overrides and English
  supplement entries overlay the base without copying it. The complete shipped
  Chinese/English dictionaries match the previous eager loader entry for entry.
- Streaming callback synthesis no longer collects a second full PCM copy inside
  the SDK. The sample still retains its result for Play / Save WAV.
- ORT sessions do not retain separate CPU arenas/memory-pattern buffers for
  variable sentence shapes, and temporary native SessionOptions are closed.
- Model weights, speaker 1, temperature 0, token table and 50-frame streaming
  geometry are unchanged in the FP32 build.

## EC521S measurement

Fresh process, same 50-segment Chinese/English prose, 166.704 seconds of output.
RSS samples are in KiB; the table converts to MiB. Peak is kernel VmHWM from
process start (including load), not a resettable per-request counter.

| Measurement | Previous FP32 | Optimized FP32 |
| --- | ---: | ---: |
| After model load + warmup | 543.1 MiB | 395.7 MiB |
| Process RSS peak | 614.1 MiB | 465.0 MiB |
| Three seconds after synthesis | 527.4 MiB | 438.0 MiB |
| First audio callback | 381 ms | 402 ms |
| Synthesis wall time | 48.202 s | 48.454 s |

This is one controlled run per build, not a statistical performance benchmark.
Peak RSS fell about 24%; total synthesis time differed by about 0.5%. No forced
GC, swap manipulation or unloading was used to manufacture a lower RSS number.
The goal of 200 MB is **not reached**. Original graph initializers total about
193 MiB before runtime buffers, dictionary, UI and shared-library pages.

Local evidence in the parent workspace: `work/logs/memory-baseline-ready/`,
`work/logs/memory-optimized/`, `lifecycle-device-result.log`,
`sample-screen-device-result.log`, `sdk-unit-memory-final/`, and
`full-lexicon-parity.log`. App/runtime source: `7e5a2ba9`.

## Mixed FP16 candidate

`tts/tools/android/convert_intmeanflow_fp16.py` creates a separate package.
Only Conv/MatMul/Gemm are eligible for FP16. Duration prediction is explicitly
kept FP32; other arithmetic, normalization, masks and public graph/cache IO stay
FP32. The converter repairs redundant casts between adjacent FP32 regions:
without that repair large mask sentinels can become infinity and produce NaNs.
A unit test checks that case and another protects Ceil-based duration rounding.

The current candidate reduces ONNX graph files from 197.9 to 127.1 MiB. Four
phonetic reference cases retain their FP32 mel lengths. Cached decoder checks
cover 16, 49, 50, 51, 99, 100, 101, 350, 431, 2050 and 2101 frames with independent
state for each of the two flow steps; all outputs are finite. These are numerical
checks, not proof of equal perceived audio quality. CPU execution providers can
promote operators/weights back to FP32, so disk savings do not establish RSS
savings.

### FP16 device result

Installed and verified the candidate APK and model graph/JSON hashes on EC521S.
Runtime callbacks confirm the `_fp16` model, speaker 1 and 50-frame streaming.
The same 50-segment prose completed with 188 PCM chunks and 166.704 seconds of
output, without an error callback. This is functional validation, not a listening
quality verdict.

| Measurement | Optimized FP32 | Mixed FP16 |
| --- | ---: | ---: |
| After model load + warmup | 395.7 MiB | 441.5 MiB |
| Process RSS peak | 465.0 MiB | 631.3 MiB |
| Three seconds after synthesis | 438.0 MiB | 444.0 MiB |
| First audio callback | 402 ms | 661 ms |
| Synthesis wall time | 48.454 s | 52.128 s |

One run per variant; FP16 did not improve memory or speed on this CPU/runtime.
It remains installed for evaluation, with FP32 retained as a rollback artifact.
The 200 MB target remains unmet. Evidence: `work/logs/memory-fp16-active/`.

Deployment caveat: external-resource discovery sorts valid model directories
by path rather than preferring the compiled model ID. With both variants in the
active resource root, it selected FP32. That preliminary run was stopped and is
not FP16 evidence. The FP32 directory was moved outside the discovery root to
`files/tts-model-backup/`; callbacks then confirmed the FP16 model. No discovery
policy code was changed in this experiment. Deploy one active model package.

Removed the obsolete `com.amphion.lits.tts.demo` application and the sample
instrumentation package `com.lits.tts.studentdemo.test`; retained the current
sample and ASR applications. The temporary model transfer archive was removed.
