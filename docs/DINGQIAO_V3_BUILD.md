# Dingqiao v3 Build Handoff

This checkout contains the Android and HarmonyOS SDK source. Large model files,
Android TN executables, and ICU source/build outputs are delivered separately.

## Inputs

1. Clone with submodules:

   ```bash
   git clone --recurse-submodules <AmphionRuntime-url>
   cd AmphionRuntime
   git submodule update --init --recursive
   ```

2. Install an Android SDK with NDK 27.2.12479018 or a compatible arm64 NDK,
   Java 17, Gradle wrapper dependencies, and DevEco Studio with HarmonyOS SDK
   API 12 / API 22 support.

3. Deliver the pre-exported model package at:

   ```text
   tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
   ```

   It must contain the five ONNX files plus the frontend text dictionaries,
   rules, and manifest. The `.bin` frontend dictionaries and TN executables are
   generated during the Android/HarmonyOS builds, and the colleague does not
   run ONNX export.

4. To rebuild Android ICU and the Android TN frontend executables, deliver the
   ICU source archive separately and run:

   ```bash
   ANDROID_NDK=/path/to/android-sdk/ndk/27.2.12479018 \
   ICU_SOURCE_ARCHIVE=/path/to/icu4c-78.1-sources.tgz \
   scripts/build_dingqiao_android_native.sh
   ```

   This writes all native build outputs under `tts/training/dingqiao_lits/build/` and the
   two executable TN frontends under `tts/training/dingqiao_lits/e2e_infer/bin-android-arm64/`.
   No sibling checkout or absolute path is used.

5. To rebuild the HarmonyOS TN frontend executables with the DevEco native SDK:

   ```bash
   OHOS_NATIVE_SDK=/path/to/openharmony/native \
   scripts/build_dingqiao_harmony_tn.sh
   ```

   This writes `zh_tts` and `en_tts` to `tts/harmony/build-ohos-tn/`.

## Android SDK

From `tts/android`:

```bash
JAVA_HOME=/path/to/jdk-17 \
ANDROID_HOME=/path/to/android-sdk \
ANDROID_SDK_ROOT=/path/to/android-sdk \
./gradlew --no-daemon :sdk:assembleRelease
```

Gradle compiles `liblits_tn.so` from the submodule and the Android ICU output,
then stages the delivered ONNX files, frontend text/bin dictionaries, rules, and
TN executables under:

```text
tts/android/external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/
```

The AAR is SDK-only: it keeps `liblits_tn.so`, ONNX Runtime JNI libraries, and
the SDK playback implementation, but it does not package `assets/lits-models`,
ONNX files, frontend resources, or TN executables. When integrating, copy the
`external-resources/tts/...` tree into the SDK work path so it is visible under
`<workPath>/tts/...`; otherwise the SDK will fail engine creation with a missing
external resources error.

## HarmonyOS SDK

From `tts/harmony`, after `ohpm install --all`:

```bash
/path/to/DevEco-Studio/tools/hvigor/bin/hvigorw \
  --mode module -p product=default -p module=sdk@default assembleHar --no-daemon
```

The Harmony CMake target compiles `liblitsttsnative.so` from the repository's
TN source and OHOS ICU static libraries. The build generates the frontend `.bin`
dictionaries before packaging, and it does not export ONNX. A HAP sample
can be built separately with `-p module=sample@default assembleHap`.

## Files intentionally outside GitHub

- five pre-exported ONNX model files;
- Android ICU source archive, if ICU must be rebuilt from source;
- generated Android ICU headers/static libraries, if rebuilding is skipped;
- Android and Harmony TN frontend executables if the colleague does not rebuild them;
- training filelists, test datasets, and checkpoints.
