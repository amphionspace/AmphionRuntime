# Frontend Parity Verification

Shared cases live in `tools/frontend_golden_cases.jsonl`. Keep Android, HarmonyOS, and Python verification based on this same catalog.

## Android Host Parity

Run host TN plus Python frontend golden generation, then compare Android JVM frontend tokens:

```sh
python tools/run_android_frontend_parity.py \
  --zh-tn /path/to/host/zh_tts \
  --en-tn /path/to/host/en_tts
```

The runner writes a generated JSONL with `raw_text`, host `tn_text`, Python `cleaned_text`, then runs:

```sh
./gradlew :sdk:testDebugUnitTest \
  --tests com.lits.tts.sdk.internal.AndroidFrontendGoldenParityTest \
  -Dandroid.frontend.golden=/path/to/generated/golden.jsonl
```

## Android APK Path

Run the instrumented smoke on a phone or emulator:

```sh
./gradlew :sdk:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.lits.tts.sdk.internal.ApkPathFrontendSmokeTest
```

This validates bundled asset extraction, `.asset_signature`, real `liblits_tn.so`, and field badcases such as `Type-C`, `USB-C`, `chatgpt`, serial codes, leading-zero minutes, and negative temperatures.

## HarmonyOS

HarmonyOS cannot execute ETS frontend code in the JVM host harness. Use the same raw cases from `tools/frontend_golden_cases.jsonl` for HAR/HAP smoke verification through `TextToSpeechEngineImpl.buildTextMetric()` logs (`[LitsTextMetric]`) and sample-app synthesis calls.

After frontend resource changes, rebuild the HAR/HAP so `supplement_lexicon.json` and the new frontend asset signature are bundled and extracted.
