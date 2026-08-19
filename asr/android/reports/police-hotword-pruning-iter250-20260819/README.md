# Police hotword pruning experiment (iter250)

This directory tracks the reversible pruning experiment for the iter250 zh-en model.

## Immutable baseline

- Git base: `2b7985673d9950bb70c864417992f22ef33af649`
- Branch: `exp/police-hotword-pruning-iter250-20260819`
- Decoder: modified beam search, `maxActivePaths=8`
- Default hotword score: `3.0`
- Effective built-in hotwords: 370 unique (`terms=355`, `plate=6`, `station=10`, with
  cross-domain duplicate `接警`)
- Packed model manifest SHA-256:
  `397f8476281b83b2c0d28fc611549402e69fd96dfbded98592d674d9fef8a829`

The production default remains `full`. The undocumented Android-only experiment parameter
`__experimentalPoliceHotwordProfile` accepts:

- `full`: all existing built-in hotwords (default, delivery-compatible baseline)
- `prune_ui30`: remove only the first 30 UI/menu candidates; 340 effective built-ins remain
- `none`: customer words only; when empty, a placeholder keeps modified-beam search armed

The placeholder means both runs use modified-beam search, avoiding an accidental comparison of
modified-beam against greedy decoding. The profile helper is public only because the experiment
crosses Android modules; it must be removed or made an explicit supported API before delivery.

## Accuracy matrix

Run the same immutable WAV corpus with:

1. `full`, police enhancement disabled: decoder/ITN/punctuation output before police final repair.
2. `full`, police enhancement enabled: current delivered result.
3. `prune_ui30`, police enhancement disabled/enabled: first reversible candidate.
4. `none`, police enhancement disabled: new acoustic model without built-in term bias.
5. `none`, police enhancement enabled: how much the unchanged final repair layer can recover.

The corpus test instrumentation arguments are
`policeHotwordProfile=full|prune_ui30|none` and a unique
`runId`. Pull and rename the TSV immediately after each run because the next run overwrites it.
Every row and the companion `dingqiao_audio_eval_profile.txt` record the run id, profile and police
enhancement state.

The public-demo batch runner writes `police_terms_eval_config.txt` beside its TSV. A valid pruning
run must record `user_hotword_count=0`; otherwise persisted customer words contaminate the
FULL/NONE comparison. Explicit-profile runs are always fresh and cannot use `--resume`.

## Promotion gates

- No critical police term may regress after final enhancement.
- Overall and per-category police term hit rate must not be lower than `full`.
- Plate and station corpora must have zero new regressions.
- General-domain collision/negative corpus must have zero new false corrections.
- Customer-hotword stress runs at 50, 100 and 200 words must improve or stay equal.
- CPU, real-time factor, engine readiness and native RSS are measured after a candidate is made
  the build default. FULL and placeholder-NONE both keep the modified-beam recognizer armed, but
  accuracy-profile runs alone do not establish production startup or memory cost.

No production hotword has been removed in this first checkpoint.
