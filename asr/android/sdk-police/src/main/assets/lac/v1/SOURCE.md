# LAC ONNX model provenance

- Project: https://github.com/kniost/lac-onnx
- Package version: `lac-onnx 0.1.0`
- License: Apache-2.0 (see `LICENSE` in this directory)
- Runtime: ONNX encoder plus local Viterbi decoding of the bundled CRF transitions

`pinyin.tsv` is generated from Amphion's bundled Chinese lexicon and is used only
for tone-aware, exact-pinyin matching against caller-supplied hotwords.
