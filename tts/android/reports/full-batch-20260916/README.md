# Current student model: legacy batch follow-up (2026-09-16)

## Scope and identity

- SDK source: `b84710f7` plus test-only external license/workPath/device-ID initialization. No runtime, model, corpus, or expected-result changes.
- Device: TECNO KI8, Android 13, arm64-v8a.
- Model: `dingqiao_intmeanflow_student_0010000_streaming_matched50_vocos24k`, temperature 0, speaker 1; copied from the currently installed sample application.
- SDK engineering/frontend suites run in the SDK instrumentation APK. The stability preflight uses the actual Release AAR through `aarHost`.
- Local evidence: workspace `outputs/tts-full-batch-20260916/` (per-case JSONL, summaries, instrumentation logs, artifact SHA-256 in `provenance.json`). License/SN/private-key material is not part of this report.

## Engineering batch: complete, gate FAIL

235 cases: **184 PASS, 34 EXPECTED_ERROR, 17 FAIL, 0 TIMEOUT**.
All 17 failures are original success cases requesting 16/32-frame chunks, rejected with `This exported student requires chunks of at least 40 frames`. The current export supports uniform configured chunks >= 40; short utterances/final blocks remain allowed.

The unchanged legacy assertions passed for the other 218 cases. This is not a perceptual quality or pitch-shift validation. The known pitch defect from the API audit remains unresolved.

For the 182 successful cases with performance metrics: first packet p50 410 ms, p90 670 ms, max 1264 ms; RTF p50 0.284, p90 0.301, max 0.357. These are suite observations on this phone, not a performance guarantee.

## Pronunciation corpus: complete, gate FAIL

The original Round15 corpus ran with native TN enabled against the current 173-token frontend: **675 total, 406 matched, 269 mismatched, 0 execution errors**. `check_pronunciation_report.py --expected-total 675` returned FAIL. Instrumentation completion alone is not a pronunciation PASS.

Separately, the captured device output was compared offline to the repository's existing `pronunciation-golden-round3-results-with-pinyin-fixed-round15-reviewed-merged.jsonl`: **439 matched, 236 mismatched**. IDs and input text were verified identical for all 675 cases. This is a second oracle comparison, not another device run; neither oracle was edited.

Differences include both frontend defects and annotation/normalization conventions. Examples:

- “把音量调到” produces `diao4` where the original oracle expects `tiao2`: a concrete polyphone issue to investigate.
- Year “2026 年” is normalized to “二零二六年”; the original oracle expects “二千零二十六年”. A mismatch is not automatically a wrong reading.
- Negative temperature is normalized to “零下” where the original oracle expects “负”.

No listening judgement was made for all 675 utterances: this suite verifies frontend pronunciation sequences, not generated audio quality. The 269 differences must not be presented as 269 confirmed model defects.

## Legacy 1000-case stability suite

The licensed Release-AAR cold-create/synthesize/shutdown smoke (case 0) passed. Cases 1–4 then produced 3 PASS and 1 FAIL: `warm-create-speak` with chunk 32 was rejected by the current model. Across both preflights, 5 original entries were executed (4 PASS, 1 FAIL). **A complete 1000-case long-run gate has not passed or been completed.**

Static inspection of the unchanged 1000-case fixture found 232 cases requesting chunks below 40 and 142 additional cases requesting a first chunk different from the steady chunk (374 distinct incompatible configurations). This inventory counts fixture settings, not device failures; query/create-only and expected-error cases may not synthesize at all.

The runner also has coverage gaps: operations such as `preempt-burst`, `queue-burst`, and `stop-running` fall through to the generic one-request speak path rather than implementing the named action. Its aggregate result therefore cannot establish these named lifecycle/concurrency contracts. The dedicated API/lifecycle audit remains the evidence for those tested sequences.

Do not spend a full long-run cycle repeating known configuration failures or call these 1000 entries 1000 successful stress iterations. Before a meaningful long-run acceptance gate, retain legacy incompatibility checks, add explicitly versioned student-compatible profiles, and implement the missing operation-specific call sequences. Keep corpus expectations and actual supported model boundaries visible; do not silently replace invalid values or count rejections as successful synthesis.
