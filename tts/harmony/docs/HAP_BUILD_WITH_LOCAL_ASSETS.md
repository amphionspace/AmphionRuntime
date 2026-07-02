# HarmonyOS HAP build with local model resources

This note is for colleagues who pull the remote branch and use the separately provided local model/frontend resource package to build the sample HAP.

## 1. Pull the branch

```bash
git fetch origin
git checkout -B tts-android-harmony-v3.0 origin/tts-android-harmony-v3.0
```

## 2. Unpack the resource package

Use the provided package:

```text
harmony-v3.0-model-frontend-20260702.zip
SHA-256: 3cbbb1396d1cab0fec032db174d4b5848eb9c83872ad320cc14cb08858c5a5aa
```

Unzip it at the repository root. After unzipping, these paths must exist:

```text
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/manifest.json
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/lits_hidden_encoder.onnx
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/vocos_vocoder.onnx
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/frontend_rules.json
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/rules/zh.json
tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/rules_v2/zh.full.json
tts/harmony/build-ohos-tn/zh_tts
tts/harmony/build-ohos-tn/en_tts
```

The HarmonyOS build script reads the model package from `tools/trial-export/...`. If `tts/harmony/build-ohos-tn/zh_tts` and `en_tts` are present, those HarmonyOS TN binaries are copied into the bundled rawfile model resources during the build.

## 3. Build the sample HAP

On macOS with DevEco Studio installed:

```bash
cd tts/harmony
export NODE_HOME=/path/to/node/home
export DEVECO_SDK_HOME=/Applications/DevEco-Studio.app/Contents/sdk
/Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all
/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw \
  --mode module \
  -p product=default \
  -p module=sample@default \
  assembleHap \
  --no-daemon
```

On Windows, run the equivalent command from `tts\harmony`:

```powershell
$env:DEVECO_SDK_HOME="C:\Program Files\Huawei\DevEco Studio\sdk"
$env:NODE_HOME="C:\Program Files\Huawei\DevEco Studio\tools\node"
& "C:\Program Files\Huawei\DevEco Studio\tools\ohpm\bin\ohpm.bat" install --all
& "C:\Program Files\Huawei\DevEco Studio\tools\hvigor\bin\hvigorw.bat" --mode module -p product=default -p module=sample@default assembleHap --no-daemon
```

The output is under:

```text
tts/harmony/sample/build/default/outputs/default/
```

## 4. Signing for device install

The branch does not contain any personal signing material. If the generated HAP is unsigned or cannot be installed on a device, open `tts/harmony` in DevEco Studio, configure a debug signing profile trusted by the target device, and rebuild the `sample` module.

For SDK-only delivery, build the HAR instead:

```bash
/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw \
  --mode module \
  -p product=default \
  -p module=sdk@default \
  assembleHar \
  --no-daemon
```

The HAR output is:

```text
tts/harmony/sdk/build/default/outputs/default/sdk.har
```
