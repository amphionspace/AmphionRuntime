# Android student regression fixes and current-model validation

完整中文说明（含修改清单、版本对应的测试证据及全部 155 条核对全文）：[Android TTS 本轮修改与验证](ANDROID_TTS_CHANGES_AND_VALIDATION_20260916.md)。以下阶段记录应结合该文档中的最新状态阅读。

## Changes

The Android runtime now preserves numeric path separators and leading zero minutes, reads build/order IDs as digits, protects PCM from the native `cm` unit rule, and uses one cardinal converter for native-TN preparation and normalized frontend input. Cardinal conversion keeps internal 一十 and handles thousands/grouped large values. 一 sandhi uses the following neutral syllable's citation tone and keeps the citation reading for decimal 1.x. Context phrases disambiguate 音量调到, 串行 and 只终止; common technical words callback, emoji and requestId have explicit pronunciations.

The model weights, 173-token mapping, temperature 0, speaker 1, 24 kHz Vocos and streaming cache contract are unchanged.

## Test adaptation

- Engineering profile `intmeanflow-student` retains all original cases, checks that each unsupported 16/32-frame input is rejected, and adds a legal 40-frame version with the same text/remaining parameters: 252 cases total.
- `AarStudentStabilityDeviceTest` is a versioned 1000-scenario Release-AAR stress suite. It actually performs queueing, callback-reentrant preemption, stopping active/queued work, shutdown/recreation, playback and recovery. It is not presented as a pass of the original 1000-case fixture with missing operation implementations.
- Playback tests enforce one start, one synthesis completion, one playback start and one playback completion, with start first and playback completion last. Synthesis completion and playback start may occur in either order because production and playback run concurrently. The original fixed-order assertion was reproduced as a false failure with short audio/large chunks.
- Public scalar/text validation errors occur before start; model-specific chunk compatibility errors currently occur after start. Negative tests assert the corresponding phase and exact error code.
- Pronunciation comparison only canonicalizes aliases with identical complete model tokens (including tone). Raw expectations, actual TN text and actual tokens remain in reports. Neither legacy oracle was rewritten to force a pass.

## Validation status

Device: TECNO KI8 / Android 13 / arm64-v8a. The installed sample APK includes the initial frontend changes and terminal-state repair; the later ordinal-context fix is not installed. Artifacts and per-request/per-case evidence are under workspace `outputs/tts-student-gate-20260916/`; SHA-256 and unit counts are in `provenance.json`.

- JVM after terminal-state repair: 141 tests, 137 PASS, 4 existing conditional skips, 0 failures. The deterministic reproducer failed twice before repair (completion/shutdown and error/shutdown) and all seven cancellation tests pass afterward.
- Student stress pilot: 30 scenarios / 51 requests PASS; all ten scenario types and three invalid-input variants exercised.
- Existing public API/lifecycle/variable-chunk device suite: 6 tests PASS.
- Engineering student profile: 252 cases, 201 PASS, 51 EXPECTED_ERROR, 0 FAIL, 0 TIMEOUT (before terminal-state repair).
- The first full stress attempt stopped at case 1: a completed request received a later STOP during shutdown. The engine now commits terminal state under the cancellation lock before entering the user callback; terminal notification and native-worker release remain separate. This also protects error callbacks and preserves cancellation after intermediate synthesis completion during playback.
- Post-repair 30-case pilot and six API tests passed. The full stress run was stopped at user request: 208 recorded cases PASS, 0 FAIL; no full-1000 pass. In-flight work and normal final cleanup were not assessed. See `stability-stopped-summary.json`; local evidence is under `stopped-long-run/`.

## Pronunciation: completed, strict gate still FAIL

The existing reviewed 675-case corpus produced **520 matches, 155 mismatches, 0 execution errors**, compared with 439 matches before the changes (the older comparison did not canonicalize equivalent aliases). All 10 known-regression cases and all 60 English-core cases match. These are frontend checks, not an audio listening evaluation.

The 155 remaining cases were grouped for review, not automatically accepted:

| Cases | Review category |
| --- | --- |
| 66 | Tone/context or numeric annotation requiring case-by-case review |
| 14 | Coordinate cardinal readings and tone conventions |
| 15 | Negative temperatures: 零下 vs 负 |
| 15 | Clock reading includes 分 |
| 7 | Calendar day cardinal vs digits in the reviewed oracle |
| 14 | sdcard falls back to letter spelling vs SD + card in oracle |
| 9 | Command am as letter names vs English am in oracle |
| 8 | ABC123 as an alphanumeric identifier vs cardinal digits in oracle |
| 7 | Integer currency amount omits .00; tone conventions |

The complete text, normalized text, expected phonemes and actual phonemes are retained in local `remaining-pronunciation-review.json`. Mismatch counts must not be described as 155 confirmed SDK bugs or as pronunciation PASS. In particular, numeric/sandhi annotation conflicts need an independently reviewed acceptance convention; the unknown compound sdcard can benefit from a lexical entry.

## Limits

Pitch quality remains the pre-existing known issue from the API audit; accepting a pitch parameter is not proof of pitch shifting. Stress coverage does not validate all external fault injections or subjective audio quality. Memory sampling reports the test-host process, including the test recorder; no automatic 200 MB acceptance claim is made.

Harmony code was inspected to satisfy repository cross-platform guidance but was not modified. No Harmony build/device pass is claimed. The Android fixes and test results above apply to Android only.

## Follow-up: individual adjudication of all 155 mismatches

See [the complete per-case review](PRONUNCIATION_ADJUDICATION_155.md) and `pronunciation-adjudication-155.json`. Primary classifications: 17 frontend defects, 34 annotation errors, 18 invalid/inconsistent date inputs, 86 reading/annotation-policy variants. Secondary findings are retained per row; categories must not be interpreted as mutually exclusive underlying causes. The original oracle remains unchanged.

The 17 frontend cases lose ordinal context at whitespace or inside the same numeral. The fix carries the surrounding text into 一 sandhi, preserves citation tone throughout a 第-prefixed numeral, and stops at punctuation/other words. Its new spacing/ordinal/cardinal/boundary regression failed before the fix and passes afterward. The legacy optional host pronunciation test was also repaired to read the real model manifest and accept text lexicons without requiring optional binary accelerators.

Verification: all 155 device-recorded normalized inputs were run through the current JVM G2P; exactly the 17 adjudicated frontend cases changed. Of those, 16 now match the old oracle; the remaining case also has an oracle omission (116 written as 一百十六). Full JVM tests: 142 total, 138 PASS, 4 pre-existing skips, 0 failures. This is not a new JNI/device run or listening evaluation. Evidence is in `outputs/tts-student-gate-20260916/pronunciation-audit/`.

The terminal-state-repair APK passed its 30-case pilot and six API/lifecycle/chunk tests; its 1000-case run was stopped at user request after 208 recorded PASS cases (0 FAIL). That installed build predates this ordinal fix and must not be cited as device evidence for it.
