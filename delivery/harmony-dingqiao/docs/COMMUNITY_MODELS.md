# Community-1 candidate (Harmony / Android)

Restore the original `community-wespeaker-masked.fp32.onnx`, `community-feature.f32`
and `community-plda.f64` from `storagePrefix` in
`delivery/harmony-dingqiao/delivery/community_diarization_1.json`. The two split
ONNX graphs are **derived locally**, not expected to exist at that storage prefix.
Use `onnx==1.19.1` in the model preparation environment:

```bash
python asr/tools/export_community_embedding_split.py \
  --source shared/models/asr/dingqiao/community-wespeaker-masked.fp32.onnx \
  --output /tmp/community-split
cp /tmp/community-split/community-wespeaker-*.onnx shared/models/asr/dingqiao/
```

The exporter verifies the original model and both output hashes against the
manifest. Use a new output directory for each export. Keep `export.json` with
build provenance. Check feature/PLDA bytes against the same manifest before
building. Harmony and Android package only the two split ONNX files; the original
is retained as a reproducible preparation input, not an additional runtime model.

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
