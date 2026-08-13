# Automatic AGC evaluation

This report records the accuracy evidence used to make the conservative WebRTC AGC2 preset
automatic for every Android and Harmony ASR session. The evaluated DSP settings are identified by
the implementation source hashes in `report.json`: 4 dB fixed gain, 4 dB adaptive initial gain,
20 dB maximum adaptive gain, 6 dB headroom, 6 dB/s maximum gain change, and -50 dBFS maximum output
noise.

## Decision

- On normal-volume AISHELL-3, no statistically significant difference was observed: CER changes
  from 2.2035% to 2.2214% (+0.0179 percentage points); the paired bootstrap 95% interval is
  [-0.1300, +0.1620] points.
- Controlled low-volume speech improves from -40 dBFS onward. At -70 dBFS, CER changes from
  5.9361% to 2.7397%, exact match changes from 70% to 76%, and empty output changes from 2% to 0%.
- The customer pink-noise set remains correct at SNR 30/25/20 dB. Below 20 dB it remains
  incorrect; AGC does not improve SNR and is not presented as a denoiser.
- In the 213.28-second meeting recording, post-180-second non-empty text changes from 105 to 112
  characters. The previously missing opening `你就不能当成你的测试来测` is retained, but another
  short clause changes, so this is evidence of local benefit rather than complete transcript proof.
- Native preprocessing median RTF is 0.00138 on the 213.28-second input (~0.14% of one host CPU
  core). Mobile power was not measured.

## Method

- Model: the repository zh-en Zipformer2 bundle, modified beam search, 8 active paths.
- Corpus: 500 AISHELL-3 utterances at original level; a deterministic RMS-stratified subset of 100
  utterances scaled to -30/-40/-50/-60/-70 dBFS without changing each source's SNR.
- Customer SNR: eight pink-noise files from 30 dB through -5 dB, reference `你好一二三四`.
- Repository regression fixture: `asr/test-fixtures/voiceprint-fallback/001_recognize.wav` scaled to
  -80 dBFS changes from `当我核查…` without AGC to the original `帮我核查…` with AGC.
- Long audio: the supplied 213.28-second meeting WAV, using the SDK-style raw Silero VAD lane and
  processed ASR lane.
- Every comparison uses the same input, model, decoder parameters, endpoint parameters, and feed
  timing. Only the ASR PCM is switched between raw and AGC output.

Machine-readable aggregate results and SHA-256 provenance are in [report.json](report.json). The
raw customer audio and per-utterance hypotheses are intentionally not committed; their preserved
local artifacts are identified by hashes so later delivery evidence can detect replacement.

With the zh-en model and host AGC library available, reproduce the repository-fixture assertion:

```bash
python3 asr/tools/evaluate_automatic_agc_regression.py \
  --model-dir asr/tools/demo-model/zhen \
  --agc-lib asr/native/audio-processing/build-host/libamphion_audio_processing.so
```

On macOS, use the `.dylib` output path. The command exits non-zero unless the raw low-volume input
reproduces the recorded substitution and automatic AGC restores the complete reference.

## Limitations

- AISHELL-3 is read speech and does not represent all devices, rooms, speakers, or far-field noise.
- The long recording has no complete human transcript, so the character count is diagnostic, not
  CER.
- Packet loss, microphone nonlinearity, hardware clipping, and mobile power consumption are not
  covered.
