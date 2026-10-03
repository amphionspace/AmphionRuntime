# Community-1 candidate (Harmony / Android)

Restore the original `community-wespeaker-masked.fp32.onnx`, `community-feature.f32`
and `community-plda.f64` from `storagePrefix` in
`delivery/harmony-dingqiao/delivery/community_diarization_1.json`. The two FP32 split
ONNX graphs are **derived locally**, not expected to exist at that storage prefix.
Use `onnx==1.19.1` in the model preparation environment:

```bash
python asr/tools/export_community_embedding_split.py \
  --source shared/models/asr/dingqiao/community-wespeaker-masked.fp32.onnx \
  --output /tmp/community-split
cp /tmp/community-split/community-wespeaker-*.onnx shared/models/asr/dingqiao/
```

Harmony packages the pinned per-channel INT8 encoder while Android retains the
FP32 encoder. Generate the Harmony model from the split FP32 encoder and the
private calibration feature directory with the runtime versions fixed in the
manifest:

```bash
.venv-harmony-ort-1.16.3/bin/python asr/tools/quantize_community_encoder.py \
  --calibration-dir /path/to/calibration-fbank \
  --output shared/models/asr/dingqiao/community-wespeaker-encoder.int8.onnx
```

The command rejects a source, calibration set, dependency version or generated
hash that differs from `community_diarization_1.json`. Calibration features and
customer audio remain private inputs and must not be committed.

The exporter verifies the original model and both output hashes against the
manifest. Use a new output directory for each export. Keep `export.json` with
build provenance. Check feature/PLDA bytes against the same manifest before
building. Android packages the two FP32 split ONNX files. Harmony packages the
INT8 encoder and the unchanged FP32 pooling graph; the original combined graph is
retained as a reproducible preparation input, not an additional runtime model.

The encoder produces a 1,280,000-byte intermediate tensor once per 10-second
window. Pooling consumes that tensor for the whole mask and disconnected clean
runs. Its lifetime ends with the synchronous native `Process` call; no feature
cache crosses a window, generation or session. Weights, masks and output vector
semantics remain unchanged. The internal native byte-array loader now takes five
assets: segmentation, encoder, pooling, feature constants, PLDA. The public SDK
API and resource-manager loader are unchanged.

These files contain global model weights/statistics; customer PCM and enrollment
embeddings must not be added to the model directory. The segmentation model is
shared. Model preparation dependencies are never shipped in the SDK, and runtime
uses packaged assets without network access. All identity and release gates have
not yet passed; this remains a candidate.
