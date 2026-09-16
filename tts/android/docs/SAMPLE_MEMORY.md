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
savings. Target-device installation was cancelled; native FP16 speed/memory
validation remains pending. The verified FP32 build remains the current app.
