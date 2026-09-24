# Community-1 model export

Export the bundled segmentation checkpoint:

```bash
python export_segmentation_onnx.py \
  /path/to/speaker-diarization-community-1/segmentation/pytorch_model.bin \
  ../../../shared/models/asr/dingqiao/community1-segmentation.onnx
```

Export the bundled WeSpeaker ResNet34 checkpoint as a standard sherpa-onnx
speaker embedding graph:

```bash
python export_wespeaker_onnx.py \
  /path/to/speaker-diarization-community-1/embedding/pytorch_model.bin \
  ../../../shared/models/asr/dingqiao/community1-wespeaker.onnx
```

The graph accepts globally mean-normalized 80-bin Kaldi fbank features in
`feats[B,T,80]` and returns `embs[B,256]`. The mobile SDK performs feature
extraction through sherpa-onnx and never loads Python or PyTorch at runtime.
