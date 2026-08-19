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
- `prune_ui28`: remove 28 device-safe UI/menu candidates; 342 effective built-ins remain
- `none`: customer words only; when empty, a placeholder keeps modified-beam search armed

The placeholder means both runs use modified-beam search, avoiding an accidental comparison of
modified-beam against greedy decoding. The profile helper is public only because the experiment
crosses Android modules; it must be removed or made an explicit supported API before delivery.

## Accuracy matrix

Run the same immutable WAV corpus with:

1. `full`, police enhancement disabled: decoder/ITN/punctuation output before police final repair.
2. `full`, police enhancement enabled: current delivered result.
3. `prune_ui28`, police enhancement disabled/enabled: first device-refined candidate.
4. `none`, police enhancement disabled: new acoustic model without built-in term bias.
5. `none`, police enhancement enabled: how much the unchanged final repair layer can recover.

The corpus test instrumentation arguments are
`policeHotwordProfile=full|prune_ui28|none` and a unique
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

## First device finding

The initial `prune_ui30` profile regressed 3 of 60 UI target cases: `自主填报` regressed once and
`短租房补录` regressed twice. Both words were restored before continuing, producing the narrower
`prune_ui28` candidate. This rejected profile is retained in Git history only as evidence.

## Samsung device checkpoint

Device: Samsung SM-G9758 (Android 12). Model: iter250. Police final enhancement was enabled in
every accuracy comparison below. FULL and PRUNE used the same APK, model, audio, decoder settings
and post-processing rules; only the hidden hotword profile changed.

- Direct UI corpus: 60 recordings (30 candidate terms x 2). FULL and `prune_ui28` produced the
  same text for all 60 recordings. Both achieved 59/60 term hits and 44/60 strict sentence hits;
  there were zero regressions. The one shared term miss, `表单填报`, was already wrong in FULL.
- Recent customer police-term corpus: 173 unique recordings, of which 166 were scorable and 7
  had conflicting labels. FULL scored 107/166 (64.46%); `prune_ui28` scored 108/166 (65.06%).
  There were zero correct-to-wrong transitions. Three outputs changed: one was corrected
  (`帮我打开警信语` to `帮我打开警信`) and two remained wrong with different hypotheses.
- Critical-term smoke: 6 recordings for `签警情`/`签警单` plus 4 Sichuan-accent recordings for
  `签收警单`. FULL and `prune_ui28` produced identical text for all 10. Both scored 9/10; the one
  shared miss was `签警情` decoded as `山警情`, so it is not a pruning regression.
- Runtime: the 173-recording run took 834.663 seconds for FULL and 833.439 seconds for
  `prune_ui28`. This near-equality is informative but is not a formal CPU, latency or RSS result.

This checkpoint is sufficient to keep `prune_ui28` as the next experimental candidate. It is not
yet sufficient to make it the delivery default: customer-hotword capacity and production-profile
performance gates remain pending.

## Additional Android device safety checkpoint

Police final enhancement was enabled for both profiles in these device A/B runs.

- Plate/station smoke: FULL and `prune_ui28` produced identical text, status, final-count and
  error state on all 47 recordings (270.080 seconds per run), with zero changed outputs and zero
  pruning regressions. Both scored 33/47 under the predefined metric: plate 7/20 and station
  26/27. All cases completed `OK` without SDK errors. The single station metric miss was the same
  two-final segmentation in both profiles; `中关村派出所` remained present in the combined text.
- General-domain audio collision smoke: all 53 synthetic Tingting-voice recordings produced
  identical output and callback state under FULL and `prune_ui28`. Both scored 44/53 normalized
  sentence matches, with zero changed outputs and zero pruning regressions. All cases completed
  `OK`, with one final and no SDK errors. The nine misses were shared baseline/model/TTS errors;
  this establishes zero *new* pruning collateral, not zero absolute errors.
- Deterministic post-processing red-team replay: all 100 simulated-ASR text cases passed the
  unchanged police pipeline (75 identity guards and 25 expected police/station/plate repairs).

These are sampled parity gates, not broad accuracy claims. The plate audio covers `冀R` and `辽B`
but has no reliable positive recording for the preset words `车牌号码` or `牌照`; its 7/20
absolute whole-plate hit rate also remains an independent model/decoder issue. The station set
covers the eight preset station names, not the wider station gazetteer. The 53 negative recordings
are single-voice synthetic speech rather than human/accent/noise coverage, and the 100-case replay
is text-only rather than an acoustic test. Matching enhancement-disabled plate/station A/B,
Harmony-device coverage and broader human negative audio remain outside this checkpoint.
