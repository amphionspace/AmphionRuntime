# HarmonyOS HAP build with local model resources

This is a historical branch handoff. For current DevEco CLI and standalone Command Line Tools commands, follow [BUILD_FROM_SOURCE.md](BUILD_FROM_SOURCE.md).

This note is for colleagues who pull the remote branch and use the separately provided local model/frontend resource package to build the sample HAP.

The remote branch contains the HarmonyOS native TN source and ICU static build dependencies needed by `liblitsttsnative.so`. You do not need a sibling training checkout or any files from the original local training/export workspace.

## 1. Pull the branch

```bash
git fetch origin
git switch --detach origin/tts-android-harmony-v3.0
```

## 2. Unpack the resource package

Use the provided package:

```text
harmony-v3.0-model-frontend-20260702.zip
SHA-256: 669f71f0187d430da18bf2720b50d17876d383cd5d5ebf1c856e2dad2a967e98
```

Unzip it at the repository root. After unzipping, these paths must exist:

```text
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/manifest.json
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/lits_hidden_encoder.onnx
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/vocos_vocoder.onnx
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/frontend_rules.json
tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/rules_v2/zh.full.json
tts/harmony/build-ohos-tn/zh_tts
tts/harmony/build-ohos-tn/en_tts
```

The HarmonyOS build script reads the model package from `tts/tools/trial-export/...`. Current source assets already contain verified frontend `.bin` files; ordinary builds copy them without rewriting the source dictionaries. If `tts/harmony/build-ohos-tn/zh_tts` and `en_tts` are present, those HarmonyOS TN binaries are copied into the bundled rawfile model resources during the build.

## 3. Current build and signing

The archive and hash above identify the historical 2026-07-02 input only. For a current checkout, obtain the matching model resources and follow [BUILD_FROM_SOURCE.md](BUILD_FROM_SOURCE.md) for HAR/HAP commands. Use DevEco CLI, standalone CLT and JDK; do not use DevEco Studio installation paths.

Configure a signing profile trusted by the target device using local protected signing material. Build the sample with the CLI, verify the signed HAP and install using CLT `hdc`. An unsigned HAP or the historical resource archive alone does not establish current device acceptance.
