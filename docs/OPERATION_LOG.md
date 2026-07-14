## 2026-07-14 Dingqiao v3 branch external-resource frontend merge

- Goal: Merge the current `codex/lits-delivery-external-resources-aar` frontend/resource pronunciation fixes into `lits_dingqiao_sdk_vocos24k_v3` and prepare that branch for push to the AmphionRuntime GitHub remote.
- Files changed or artifacts created: merged Android external-resource pronunciation assets, reviewed golden test assets, Kotlin TN/frontend fixes, Android instrumentation tests, TN route logging, and Harmony/Android delivery-compatible conflict resolutions into `lits_dingqiao_sdk_vocos24k_v3`.
- Commands run: committed the current branch as `75e48ae`; switched to `lits_dingqiao_sdk_vocos24k_v3`; ran `git merge --no-ff codex/lits-delivery-external-resources-aar`; resolved build/resource/TN naming conflicts by keeping Dingqiao delivery build structure and applying the current branch pronunciation/frontend fixes.
- Verification result: merge conflicts were resolved and Android Kotlin compilation reached `:sdk:compileDebugUnitTestKotlin` through the frontend unit-test task. The full `LitsTtsFrontendTest` run was not a valid pass/fail signal in this merge checkout because `cleanBundledTtsResources` removed bundled assets while external resource staging was intentionally skipped; runtime failures were missing-resource `NoSuchFileException`/`FileNotFoundException`, not Kotlin compilation errors.
- Notes/next action: Local-only caches, signing material, and exported work directories remain untracked and are intentionally not part of the pushed branch.

## 2026-07-13 18:49 Dingqiao v3 Android report case examples

- Goal: Add one or two easy-to-understand examples for each case type in the Dingqiao v3 Android 1000-case stability report.
- Files changed or artifacts created: `tts/android/docs/DINGQIAO_V3_ANDROID_1000_STABILITY_TEST_REPORT_20260713.md`, `docs/OPERATION_LOG.md`.
- Commands run: inspected representative cases from `tts/android/testdata/dingqiao_batch_cases/android_v3_sdk_stability_1000_cases_improved.jsonl`; updated the case coverage table with concise examples.
- Verification result: The report now includes examples for all 14 case types while keeping the conclusion and key metrics unchanged.
- Notes/next action: No code, build artifact, commit, or push was performed.

## 2026-07-13 18:45 Dingqiao v3 Android report sample-count wording

- Goal: Update the Dingqiao v3 Android 1000-case stability report so the metric table sample count presents the overall 1000-case test size.
- Files changed or artifacts created: `tts/android/docs/DINGQIAO_V3_ANDROID_1000_STABILITY_TEST_REPORT_20260713.md`, `docs/OPERATION_LOG.md`.
- Commands run: edited the report sample-count wording and table values.
- Verification result: The key metric table now shows sample count `1000` for first packet, RTF, synthesis time, and audio duration.
- Notes/next action: No code, build artifact, commit, or push was performed.

## 2026-07-13 18:40 Dingqiao v3 Android 1000-case stability report

- Goal: Write a concise Chinese test report from today's Dingqiao v3 Android 1000-case stability results, with conclusion first and emphasis on tested case types, first packet, RTF, temperature, and memory.
- Files changed or artifacts created: `tts/android/docs/DINGQIAO_V3_ANDROID_1000_STABILITY_TEST_REPORT_20260713.md`, `docs/OPERATION_LOG.md`; temporarily pulled a latest device-side single-case artifact while searching for evidence, then removed that temporary copy after confirming it was not needed for the report.
- Commands run: inspected `docs/OPERATION_LOG.md`; searched local and device result paths; pulled `/sdcard/Android/data/com.lits.tts.aarhost/files/aar-stability-1000/*1783938891126*`; parsed `/Users/amphion/Documents/Lits_delivery/eval_output/dingqiao_improved_v2_full1000_batched_20260713_step4_ctx16_chunkramp` JSONL result files and `android_v3_sdk_stability_1000_cases_improved_summary.json`.
- Verification result: Report conclusion follows the requested口径: ignore harness false-positive fail, long-text timeout caused by unreasonable timeout settings, and skipped cases; no remaining real FAIL was found. Key metrics recorded: firstPacketMs avg/P50/P95/max 174/169/247/288 ms; RTF avg/P50/P95/max 0.23/0.21/0.25/0.93; temperature peak max 44 C; memory peak max Java/native/PSS/RSS 313.8/654.7/755.5/847.7 MB.
- Notes/next action: The report intentionally describes the test as a 1000-case stability result summary and avoids emphasizing execution batching. No code, build artifact, commit, or push was performed.

## 2026-07-13 17:24 CST

- Goal: Create a new branch from `lits_dingqiao_sdk_vocos24k_v3`, migrate the Android TTS AAR build to the Lits_delivery external-resources layout, keep frontend binary resources and ONNX models outside the SDK AAR, keep ICU/native playback runtime inside the SDK, and compile the Android AAR once.
- Files changed or artifacts created: created branch `codex/lits-delivery-external-resources-aar`; updated `tts/android/build.gradle.kts` to stage resources under `tts/android/external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/` and remove bundled SDK assets before build; updated `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetInstaller.kt` with a clear missing external-resources error; updated `docs/DINGQIAO_V3_BUILD.md`; generated `tts/android/sdk/build/outputs/aar/sdk-release.aar` and refreshed `tts/android/external-resources/...`.
- Commands run:
  - `git switch -c codex/lits-delivery-external-resources-aar`
  - `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm PATH=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm/bin:$PATH ANDROID_HOME=/Users/amphion/Library/Android/sdk ANDROID_SDK_ROOT=/Users/amphion/Library/Android/sdk ./gradlew --no-daemon :sdk:assembleRelease`
  - repeated the same `:sdk:assembleRelease` command after the installer error-message change
  - inspected the AAR with `zipinfo -1 sdk/build/outputs/aar/sdk-release.aar | rg 'assets/lits-models|\\.onnx$|chinese_lexicon|cmudict|tn-bin|jni/arm64-v8a|classes.jar'`
  - inspected external resources with `find external-resources/tts/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0 -maxdepth 3 -type f`
- Verification result: Android `:sdk:assembleRelease` passed twice. Final AAR `tts/android/sdk/build/outputs/aar/sdk-release.aar` is 23M with SHA-256 `29f4f8626892c083a0b13d9ff41d820e1e7e3bf22d8d05f13299f91dbc2092e1`; AAR contents include `classes.jar`, `libs/onnxruntime-android-1.24.3-classes.jar`, `jni/arm64-v8a/liblits_tn.so`, `jni/arm64-v8a/libonnxruntime.so`, and `jni/arm64-v8a/libonnxruntime4j_jni.so`, with no `assets/lits-models`, `.onnx`, frontend dictionary, or `tn-bin` entries. External resources contain 28 files and are 273M, including ONNX files, `chinese_lexicon.bin`, `cmudict.bin`, `rules_v2`, and `tn-bin/arm64-v8a/{zh_tts,en_tts}`.
- Notes/next action: Integration must copy the external resource tree so it appears under `<workPath>/tts/...` before engine creation. Existing unrelated dirty working-tree changes were left untouched.

## 2026-07-13 14:52 CST

- Goal: finish reproducibility verification after adding manifest size synchronization for generated frontend binaries.
- Commands run:
  - reran `python3 tools/dingqiao-android/build_frontend_binary_assets.py` and confirmed `manifest.json` records `chinese_lexicon.bin=18755755` and `cmudict.bin=6594504`.
  - reran Android `:sdk:assembleRelease` with local JDK 17 and Android SDK/NDK.
  - reran HarmonyOS `ohpm install --all` and `sdk@default assembleHar` with DevEco SDK.
  - inspected AAR and gzip/tar HAR contents for arm64 native libraries, generated frontend binaries, ONNX assets, and TN executables.
- Verification result: Android AAR and HarmonyOS HAR builds passed again. No forbidden model/TN/test-data files are staged for the parent repository; license/signing remains outside the current compile check.

## 2026-07-13 14:55 CST

- Goal: allow a clean colleague checkout to build HarmonyOS TN binaries without pre-supplied `tn-bin` files.
- Files changed: updated `tts/harmony/hvigorfile.ts` to resolve generated `build-ohos-tn/{zh_tts,en_tts}` before checking model-package TN files; updated `docs/DINGQIAO_V3_BUILD.md` to describe generated TN outputs.
- Verification result: the existing HarmonyOS HAR build path remains successful; a clean checkout only needs the model text resources/ONNX inputs plus the Android ICU source archive when rebuilding Android ICU.

## 2026-07-13 14:48 CST

- Goal: make the Android/HarmonyOS v3 SDK build independent of local model paths and regenerate frontend binary dictionaries from source text.
- Files changed: added `tools/dingqiao-android/build_frontend_binary_assets.py`; updated `tts/android/build.gradle.kts`, `tts/harmony/hvigorfile.ts`, Android/Harmony build handoff docs, and moved the active model input path to `tts/tools/trial-export/...`.
- Commands run:
  - `python3 tools/dingqiao-android/build_frontend_binary_assets.py --model-dir tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0`
  - `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm ANDROID_HOME=/Users/amphion/Library/Android/sdk ANDROID_SDK_ROOT=/Users/amphion/Library/Android/sdk ./gradlew --no-daemon :sdk:assembleRelease`
  - `NODE_HOME=/Applications/DevEco-Studio.app/Contents/tools/node /Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all`
  - `DEVECO_SDK_HOME=/Applications/DevEco-Studio.app/Contents/sdk NODE_HOME=/Applications/DevEco-Studio.app/Contents/tools/node /Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sdk@default assembleHar --no-daemon`
- Verification result: the frontend generator produced `chinese_lexicon.bin` with 664,612 entries and `cmudict.bin` with 125,699 entries; Android AAR build passed; HarmonyOS HAR build passed. The current Android/Harmony build flow does not export ONNX. License/signing is outside this compile verification scope.
- Notes: `chinese_lexicon.bin` and `cmudict.bin` are generated local build outputs and remain ignored; the text dictionaries are the reproducible inputs. Android and HarmonyOS are the primary targets; macOS is only used for local tool verification.

## 2026-07-02 17:25 CST

- Goal: Fix the colleague build failure caused by residual local `transsion_lits` build-time dependencies in the v3.0 TTS Android/Harmony branch.
- Files changed or artifacts created: vendored HarmonyOS native TN source and OHOS ICU static dependencies under `tts/harmony/sdk/src/main/cpp/third_party/`; vendored Android native TN source and Android ICU static dependencies under `tts/android/sdk/src/main/cpp/third_party/`; updated HarmonyOS `CMakeLists.txt`; updated Android `CMakeLists.txt` and `Android.mk`; changed Android Gradle asset packing to validate the unpacked model/frontend package instead of copying TN files from a sibling `transsion_lits`; updated `tts/harmony/docs/HAP_BUILD_WITH_LOCAL_ASSETS.md`; refreshed `/Users/amphion/Documents/Lits_delivery/delivery/harmony-v3.0-har-hap-20260702.zip` with newly built HAR/HAP.
- Commands run:
  - searched TTS Android/Harmony build scripts for `transsion_lits` and historical external paths.
  - copied required TN engine sources, nlohmann header, and platform ICU headers/static libraries from the local export workspace into repo-local `third_party` directories.
  - ran `/Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all`.
  - ran `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sdk@default assembleHar --no-daemon`.
  - ran `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sample@default assembleHap --no-daemon`.
  - ran `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm ./gradlew --no-daemon :sdk:assembleRelease` in `tts/android`.
  - inspected HAR/HAP/AAR package contents and regenerated the handoff zip/checksum.
- Verification result: `rg` found no remaining build-script references to the old external `transsion_lits`/ICU paths in `tts/android` or `tts/harmony` after excluding generated build directories. HarmonyOS HAR and HAP builds passed; new HAR SHA-256 `6866aba03778da29403e443cee0a81e04cdcbe7de7761c475debce2050e83fbf`, new HAP SHA-256 `2bc0aa32b2ccce870b0ae2ec4a5753bcd32df627823392d2603c0cf2d2bf3fa4`. Android SDK release AAR build passed; AAR SHA-256 `9a48ca0903c7a1fd1ab2e3f598a2da5e8ff9835dc1e1b32f29893c64a3450958`. Package inspection confirmed the HAR/HAP still contain `liblitsttsnative.so` plus rawfile model/frontend resources and Android AAR still contains `jni/arm64-v8a/liblits_tn.so` plus model/frontend assets. Refreshed handoff zip SHA-256 `6c3458d544ccfb5cc550f766f48c6b1cbc629ea53537bff7d34b148865d28981`.
- Notes or next action: colleagues still need to unpack the separately provided v3.0 model/frontend package into repo-root `tools/trial-export/...`, but they should no longer need a sibling `transsion_lits` checkout or any files from the original local training/export workspace.

## 2026-07-02 17:10 CST

- Goal: Build and verify the HarmonyOS TTS HAR/HAP artifacts requested for colleague handoff.
- Files changed or artifacts created: generated/verified `tts/harmony/sdk/build/default/outputs/default/sdk.har`; generated/verified `tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap`; copied both into `/Users/amphion/Documents/Lits_delivery/delivery/harmony-v3.0-har-hap-20260702/`; created `/Users/amphion/Documents/Lits_delivery/delivery/harmony-v3.0-har-hap-20260702.zip` and `.sha256`.
- Commands run:
  - `/Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all`
  - `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sdk@default assembleHar --no-daemon`
  - `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sample@default assembleHap --no-daemon`
  - `gzip -dc sdk.har | tar -tvf -` package inspection for HAR contents.
  - `unzip -l sample-default-unsigned.hap` package inspection for HAP contents.
- Verification result: HAR build passed and produced `sdk.har` size `199M`, SHA-256 `43a08a5c0df41de0d3267cc945ee8e1d60ec12bec1dd22abe9337b5cbda4d172`; HAP build passed and produced `sample-default-unsigned.hap` size `327M`, SHA-256 `3413cfb9bbd028fdb0997af10b85c6f41a1991937e247b729bd9675d50b15fb4`. HAR contains `package/libs/arm64-v8a/liblitsttsnative.so`, 34 v3.0 rawfile model/frontend entries, `manifest.json`, `lits_hidden_encoder.onnx`, `vocos_vocoder.onnx`, `chinese_surname_lexicon.txt`, `polyphone_context.txt`, `polyphone_phrases.txt`, and TN binaries `zh_tts`/`en_tts`. HAP contains `libs/arm64-v8a/liblitsttsnative.so` and 30 v3.0 rawfile model/frontend entries with the same required frontend/model files. Delivery zip SHA-256 is `8c5c035a3d49f8d3608027ce7318a62106a084da5925f5e5d1be5e273c3d1bad`.
- Notes or next action: handoff package is `/Users/amphion/Documents/Lits_delivery/delivery/harmony-v3.0-har-hap-20260702.zip`; `sample-default-unsigned.hap` is intentionally unsigned.

## 2026-07-02 15:30 CST

- Goal: Pull GitHub `origin/main`, sync latest local v3.0 TTS Android and HarmonyOS SDK code/resources from `Lits_delivery`, document colleague HAP compilation from a separate model/frontend resource package, verify builds, and push the remote branch `tts-android-harmony-v3.0`.
- Files changed or artifacts created: updated `tts/android`, `tts/harmony`, and tracked `tts/tools/trial-export` frontend/TN resource files from `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5`; added `tts/harmony/docs/HAP_BUILD_WITH_LOCAL_ASSETS.md`; kept local-only models under ignored `tools/trial-export`; generated local HAP `tts/harmony/sample/build/default/outputs/default/sample-default-unsigned.hap`; updated `docs/OPERATION_LOG.md`.
- Commands run:
  - `git pull origin main`
  - rsync from `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/` to `tts/android/`
  - rsync from `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/HarmonyOS/AmphionRuntime/` to `tts/harmony/`
  - rsync from `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/tools/trial-export/` to `tools/trial-export/` and `tts/tools/trial-export/`
  - `./gradlew --no-daemon :sdk:testDebugUnitTest --tests com.lits.tts.sdk.internal.LitsTtsFrontendTest`
  - `/Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all`
  - `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sample@default assembleHap --no-daemon`
- `git commit -m "Sync v3.0 TTS Android and Harmony SDK"`
  - `git push origin HEAD:refs/heads/tts-android-harmony-v3.0`
- Verification result: Android focused frontend unit tests passed. HarmonyOS sample HAP build passed after generating local `oh_modules`; output `sample-default-unsigned.hap` size `327M`, SHA-256 `dc43ba69de7d726752e91806c9fdef3d7dd2f38a22daa7e1429c4bc9f0295170`. `git diff --check` passed. Diff scan found no `.ohos`, signing password, `.p12`, `.p7b`, `.cer`, `.csr`, or `.signing-local` secrets in tracked changes. Commit `675a751` was pushed to new GitHub branch `origin/tts-android-harmony-v3.0`.
- Notes or next action: the HAP is unsigned because personal signing material is intentionally not committed; configure device-trusted DevEco signing locally before install. The separate resource package is `/Users/amphion/Documents/Lits_delivery/delivery/harmony-v3.0-model-frontend-20260702.zip`, SHA-256 `3cbbb1396d1cab0fec032db174d4b5848eb9c83872ad320cc14cb08858c5a5aa`.

## 2026-07-02 16:05 CST

- Goal: Re-check v3.0 frontend synchronization against the historical build-overwrite failure mode and fix any mismatch before telling the user it is safe.
- Files changed or artifacts created: updated `tts/harmony/hvigorfile.ts` so HarmonyOS rawfile bundling includes `chinese_surname_lexicon.txt`, `polyphone_context.txt`, and `polyphone_phrases.txt`; updated tracked `tts/tools/trial-export/.../rules/{zh,en,zh_pinyin}.json` and `rules_v2/{zh,en}.full.json` to match authoritative `transsion_lits` rules; updated `tts/harmony/docs/HAP_BUILD_WITH_LOCAL_ASSETS.md` with the regenerated resource zip hash; rebuilt local Android assets and Harmony unsigned sample HAP.
- Commands run:
  - SHA comparison script across Lits_delivery trial-export, AmphionRuntime root `tools/trial-export`, AmphionRuntime `tts/tools/trial-export`, Android generated assets, Harmony generated rawfile, and HAP contents.
  - Inspected `tts/android/build.gradle.kts` and confirmed `syncTranssionTnRules` overwrites root `tools/trial-export` from `transsion_lits`.
  - Forced `rules/` and `rules_v2/` sync from `/Users/amphion/Documents/Lits_delivery/transsion_lits/Transsion_Multilingual_Text_Normalization_for_TTS/` into all trial-export mirrors.
  - Cleared generated Android and Harmony model output directories.
  - `./gradlew --no-daemon :sdk:testDebugUnitTest --tests com.lits.tts.sdk.internal.LitsTtsFrontendTest`
  - `/Applications/DevEco-Studio.app/Contents/tools/ohpm/bin/ohpm install --all`
  - `/Applications/DevEco-Studio.app/Contents/tools/hvigor/bin/hvigorw --mode module -p product=default -p module=sample@default assembleHap --no-daemon`
- Verification result: final comparison passed for 19 frontend files and 2 TN binaries across source, build inputs, Android generated assets, Harmony generated rawfile, and HAP package contents. Final key hashes: `rules/zh.json=35473f0250019dcaeb2c25f55c3a35392df8c4d23390a01e4776001e429f3037`, `rules_v2/zh.full.json=36d3c0395a0a8e3180d3be07c6c9c1140e044ffb644a92ee8a8393967f34d4a8`, `polyphone_phrases.txt=4ac31b411b884ab55f0f5a9eb764ca22ed55a3a3b4a7d72c138f864458ba0a8e`, `chinese_surname_lexicon.txt=2010afe0b843ec728aad4f36533394fa895dd0d8a21c0f7254ebfb1e8d2776b8`. Android focused frontend test passed. HarmonyOS sample HAP build passed; HAP SHA-256 `3413cfb9bbd028fdb0997af10b85c6f41a1991937e247b729bd9675d50b15fb4`. Regenerated local resource zip SHA-256 `669f71f0187d430da18bf2720b50d17876d383cd5d5ebf1c856e2dad2a967e98`.
- Notes or next action: the first verification did catch a real mismatch. Root `tools/trial-export` is the actual Android/Harmony build input and is rewritten by Android Gradle from `transsion_lits`; `tts/tools/trial-export` alone is not sufficient evidence. Use the multi-path SHA check above for future frontend sync verification.

## 2026-07-01 10:44 CST

- Goal: Read local Lits delivery skill and AmphionRuntime operation history to clarify the correct TTS AAR / demo APK / zip build procedure before running any further build commands.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `sed -n '1,220p' /Users/amphion/Documents/Lits_delivery/.codex/skills/lits-delivery/SKILL.md`
  - `sed -n '1,140p' docs/OPERATION_LOG.md; sed -n '280,430p' docs/OPERATION_LOG.md; sed -n '430,540p' docs/OPERATION_LOG.md`
  - `sed -n '1,170p' tts/android/build.gradle.kts; sed -n '1,120p' tts/android/sample/build.gradle.kts; sed -n '1,120p' tts/android/gradle.properties`
  - `sed -n '/## Operation Logging Rule/,$p' /Users/amphion/Documents/Lits_delivery/.codex/skills/lits-delivery/SKILL.md`
- Verification result: confirmed the local skill requires every local operation to be logged immediately. Historical TTS delivery flow shows AAR is built as an armed SDK with non-empty `AMPHION_LICENSE_PUBLIC_KEY`; the concrete `.lic` is supplied by the host/demo APK assets, not inside the AAR; demo APK history uses demo/app license assets and should not be treated as the formal SN-bound customer license; formal salted SN authorization is for customer license verification and SDK capability support.
- Notes or next action: summarize the correct AAR, demo APK, and zip procedure before executing any further commands.

## 2026-07-01 10:47 CST

- Goal: Resume v0.2.5.4 TTS delivery build and first locate historical demo license candidates without rebuilding or signing anything yet.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `find /Users/amphion/Documents/AmphionRuntime /Users/amphion/Documents/Lits_delivery /Users/amphion/Documents/AmphionRuntime-Delivery -path '*amphion-license.lic' -o -path '*.lic' 2>/dev/null | sed -n '1,200p'`
  - `find /Users/amphion/Documents/AmphionRuntime-Delivery -maxdepth 4 -type f | sort | sed -n '1,200p'`
  - `git status --short --branch -- docs/OPERATION_LOG.md tts/android/sample/src/main/assets/amphion-license.lic tts/android/sdk/build/outputs/aar/sdk-release.aar tts/android/sample/build/outputs/apk/release`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: located historical license candidates, especially `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/sample/src/main/assets/amphion-license.lic`; direct listing of `/Users/amphion/Documents/AmphionRuntime-Delivery` failed with `Operation not permitted`, so future steps should use known paths or repo-local staging rather than broad scans there.
- Notes or next action: decode the historical demo license candidate and confirm it is not SN-bound before copying it into the AmphionRuntime sample assets.

## 2026-07-01 10:48 CST

- Goal: Decode candidate demo license claims to distinguish the historical non-SN demo license from the mistakenly generated SN-bound demo license.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - Python script decoded `payload_b64` for:
    - `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/sample/src/main/assets/amphion-license.lic`
    - `/Users/amphion/Documents/AmphionRuntime/tts/android/sample/src/main/assets/amphion-license.lic`
    - `/Users/amphion/Documents/AmphionRuntime/.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/license/lits-tts-license.lic`
- Verification result: historical Lits_delivery demo license has `applicationId=com.tdtech.tiassistant`, `features=TTS`, `expiresAt=2026-08-25`, debug cert SHA256 `954fd136...0755c`, and `authorizedDeviceHashes=[]`; current AmphionRuntime sample asset was the mistakenly generated SN-bound file with one authorized hash `9805621A...CC518`.
- Notes or next action: replace the AmphionRuntime sample asset with the historical non-SN demo license before building the demo APK.

## 2026-07-01 10:49 CST

- Goal: Retry reading `/Users/amphion/Documents/AmphionRuntime-Delivery` using targeted commands, as requested, to reuse the historical v0.2.5.4 delivery structure.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `ls -la /Users/amphion/Documents/AmphionRuntime-Delivery 2>&1`
  - `find /Users/amphion/Documents/AmphionRuntime-Delivery -maxdepth 2 \( -name 'lits-transsion-tts-android-sdk-vocos24k-0.2.5.4*' -o -name '*.zip' -o -name '*.sha256' \) -print 2>&1 | sed -n '1,120p'`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: targeted access succeeded. Existing historical v0.2.5.4 delivery tree and zip are present at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630/` and `.zip`; older 0.2.5.x delivery zips are also present.
- Notes or next action: use the historical v0.2.5.4 tree as the reference layout for today's rebuilt package.

## 2026-07-01 10:50 CST

- Goal: Inspect the historical v0.2.5.4 delivery tree metadata before staging today's rebuild.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `find /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630 -maxdepth 3 -type f | sort | sed -n '1,220p'`
  - `sed -n '1,220p' /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630/VERSION.txt; sed -n '1,160p' /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630/CHECKSUMS.txt`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: historical layout contains `aar/`, `demo/`, `docs/`, `license/`, `android-src/TTS`, `README.txt`, `VERSION.txt`, and `CHECKSUMS.txt`. `VERSION.txt` explicitly distinguishes formal integration license (`license_device_binding=salted_sn_whitelist`, `license_authorized_device_hashes=16`) from demo APK embedded license (`demo_apk_license_device_binding=none`, `demo_apk_embedded_license=assets/amphion-license.lic`).
- Notes or next action: replace the current sample asset with the historical non-SN demo license, then rebuild AAR and release demo APK.

## 2026-07-01 10:51 CST

- Goal: Replace the mistakenly generated SN-bound sample license with the historical non-SN demo license before building the demo APK.
- Files changed: `tts/android/sample/src/main/assets/amphion-license.lic`; `docs/OPERATION_LOG.md`.
- Commands run:
  - `cp /Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/sample/src/main/assets/amphion-license.lic /Users/amphion/Documents/AmphionRuntime/tts/android/sample/src/main/assets/amphion-license.lic`
  - Python script decoded the copied license and printed SHA-256 plus selected claims.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: copied demo license SHA-256 is `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`, matching the historical v0.2.5.4 `demo_apk_license_sha256`. Claims: `applicationId=com.tdtech.tiassistant`, `features=TTS`, `expiresAt=2026-08-25`, debug cert SHA256 `954fd136...0755c`, and `authorizedDeviceHashes_count=0`.
- Notes or next action: build `:sdk:assembleRelease :sample:assembleRelease` with the corrected demo license asset.

## 2026-07-01 10:52 CST

- Goal: Build v0.2.5.4 armed TTS AAR and release demo APK using the corrected non-SN demo license asset.
- Files changed: Gradle outputs under `tts/android/sdk/build/` and `tts/android/sample/build/`; `docs/OPERATION_LOG.md`.
- Commands run:
  - `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm PATH=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm/bin:$PATH ./gradlew --no-daemon :sdk:assembleRelease :sample:assembleRelease`
- Verification result: Gradle build succeeded in 20s. `:sdk:assembleRelease` and `:sample:assembleRelease` completed successfully.
- Notes or next action: inspect AAR/APK outputs, verify APK contains `assets/amphion-license.lic`, and sign the release APK if Gradle produced an unsigned artifact.

## 2026-07-01 10:53 CST

- Goal: Inspect release build outputs before signing/staging.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `ls -lh tts/android/sdk/build/outputs/aar/sdk-release.aar tts/android/sample/build/outputs/apk/release/*; shasum -a 256 tts/android/sdk/build/outputs/aar/sdk-release.aar tts/android/sample/build/outputs/apk/release/*`
  - `zipinfo -1 .../sample-release-unsigned.apk | rg 'assets/.+lic|lib/arm64-v8a|classes|AndroidManifest.xml'`
  - `apksigner verify --print-certs .../sample-release-unsigned.apk`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: AAR exists at `tts/android/sdk/build/outputs/aar/sdk-release.aar`, size `202M`, SHA-256 `4aba1afffe3616c010c989a5ad55972b5542c5c9c81e6bd5a873d593ff39cafb`. Release APK output is `sample-release-unsigned.apk`, size `247M`, SHA-256 `b328373ee65d89f705138c1e0db0e4bb286ea08107431e3ee05d087990b8b48e`; it contains `assets/amphion-license.lic` and arm64 native libs, but `apksigner` reports `DOES NOT VERIFY` / missing `META-INF/MANIFEST.MF`, so it must be signed before packaging as demo APK.
- Notes or next action: sign the unsigned release APK with the local debug keystore, matching the historical demo license cert binding.

## 2026-07-01 10:54 CST

- Goal: Sign the release demo APK with the local debug keystore so it matches the historical demo license certificate binding.
- Files changed: `tts/android/sample/build/outputs/apk/release/sample-release-aligned.apk`; `tts/android/sample/build/outputs/apk/release/lits-tts-release-signed.apk`; `docs/OPERATION_LOG.md`.
- Commands run:
  - `zipalign -f -p 4 sample-release-unsigned.apk sample-release-aligned.apk`
  - `apksigner sign --ks ~/.android/debug.keystore --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out lits-tts-release-signed.apk sample-release-aligned.apk`
  - `apksigner verify --print-certs lits-tts-release-signed.apk`
  - `ls -lh lits-tts-release-signed.apk`
  - `shasum -a 256 lits-tts-release-signed.apk`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: signed APK verifies with certificate SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`, matching the demo license binding. Signed APK size is `247M`; SHA-256 is `4261e98b992607721646a279bc8113ad2c0a52e98455ea4737b2567245a6e21f`.
- Notes or next action: stage the rebuilt AAR, signed APK, formal license, docs, and source snapshot into a new dated delivery tree and create the zip.

## 2026-07-01 10:56 CST

- Goal: Stage the rebuilt v0.2.5.4 delivery tree and create the delivery zip.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701/`; `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip`; `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip.sha256`; `docs/OPERATION_LOG.md`.
- Commands run:
  - Python staging script copied current AAR, signed demo APK, formal Dingqiao license, docs, and source/resource snapshot; generated `README.txt`, `VERSION.txt`, `CHECKSUMS.txt`; created zip and `.sha256`.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: delivery tree created at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701`; zip created at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip`; zip SHA-256 `4580fbe3b02ae794325c0f22138814a590598e804f9d4fc364bda098e619a300`; zip size `807214514` bytes; zip entries `169`.
- Notes or next action: run zip CRC, required-entry, forbidden-file, license, AAR, APK, and checksum verification before declaring the package ready.

## 2026-07-01 10:57 CST

- Goal: Run final zip/package verification.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - Python verification script for zip CRC, required entries, forbidden entries, `CHECKSUMS.txt`, AAR contents, APK embedded license, APK signature, and formal/demo license claims.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: verification script failed before inspecting the package because it used `Path.with_suffix('.zip')`, which incorrectly resolved the dotted package name to `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.zip`.
- Notes or next action: rerun verification with the explicit zip path `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip`.

## 2026-07-01 10:59 CST

- Goal: Rerun final zip/package verification with the explicit full zip path.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - Python verification script using `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: final verification passed. Zip SHA-256 `4580fbe3b02ae794325c0f22138814a590598e804f9d4fc364bda098e619a300`; zip size `807214514` bytes; entries `169`; `CHECKSUMS.txt` verified `167` lines; forbidden entries `0`. AAR SHA-256 `4aba1afffe3616c010c989a5ad55972b5542c5c9c81e6bd5a873d593ff39cafb`; AAR contains no `.lic`. Demo APK SHA-256 `4261e98b992607721646a279bc8113ad2c0a52e98455ea4737b2567245a6e21f`; APK cert SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. Demo license has `features=TTS`, `expiresAt=2026-08-25`, `authorizedDeviceHashes=0`, cert `954fd136...0755c`. Formal license has `features=ASR,TTS`, `expiresAt=2026-08-25`, `authorizedDeviceHashes=16`, cert `6e9b5a...22e8`.
- Notes or next action: package is ready for handoff at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701.zip`.

## 2026-07-01 11:00 CST

- Goal: Start verifying whether the delivered AAR is an armed/auth-enabled TTS SDK artifact.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `ls -lh` and `shasum -a 256` for `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701/aar/lits-transsion-tts-sdk-vocos24k-0.2.5.4-demo-auth.aar` and formal `license/amphion-license.lic`
  - `zipinfo -1 <AAR> | rg 'classes.jar|BuildConfig|\\.lic$|jni/arm64-v8a|assets/lits-models'`
  - `sed -n '1,180p' tts/android/aarHost/build.gradle.kts; find tts/android/aarHost -maxdepth 4 -type f`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: delivered AAR exists, size `202M`, SHA-256 `4aba1afffe3616c010c989a5ad55972b5542c5c9c81e6bd5a873d593ff39cafb`; formal license SHA-256 is `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`. AAR contains `classes.jar`, model assets, and arm64 JNI libs (`liblits_tn.so`, `libonnxruntime.so`, `libonnxruntime4j_jni.so`); no `.lic` entry was found in the AAR listing. `aarHost` currently points to `../sdk/build/outputs/aar/sdk-debug.aar`, so it is not yet a direct validation harness for the delivered release AAR without adjustment.
- Notes or next action: extract/decompile AAR `BuildConfig` to confirm `LICENSE_PUBLIC_KEY_B64` is non-empty, then use that public key to verify the formal license offline.

## 2026-07-01 11:01 CST

- Goal: Extract delivered AAR `BuildConfig` and use its public key to verify the formal license.
- Files changed: temporary `/tmp/tts-aar-auth.*` extraction directory; `docs/OPERATION_LOG.md`.
- Commands run:
  - `unzip -q <AAR> classes.jar -d /tmp/tts-aar-auth.*`
  - `jar tf classes.jar | rg 'BuildConfig|LicenseVerifier|LicenseGuard|DeviceLicenseFingerprint|TextToSpeechLicense'`
  - `javap -classpath classes.jar -verbose com.lits.tts.sdk.BuildConfig | rg 'LICENSE_PUBLIC_KEY_B64|SDK_MAJOR|SDK_RELEASE_DATE|ConstantValue'`
  - attempted shell extraction of `LICENSE_PUBLIC_KEY_B64` into `PUB` followed by `tts/tools/license/verify_license.py`
- Verification result: `javap` confirmed delivered AAR contains `com.lits.tts.sdk.BuildConfig` with non-empty `LICENSE_PUBLIC_KEY_B64`, `SDK_MAJOR=1`, and `SDK_RELEASE_DATE=2026-06-23`; AAR also contains `LicenseGuard`, `LicenseVerifier`, and `DeviceLicenseFingerprint` classes. The script failed before license verification because the Python here-doc consumed stdin incorrectly and tried to parse raw `javap` output as Python, producing `SyntaxError`.
- Notes or next action: rerun license verification with a simpler explicit public key extraction command.

## 2026-07-01 11:02 CST

- Goal: Verify delivered AAR authentication end-to-end at the offline license layer using the public key extracted from the AAR.
- Files changed: temporary `/tmp/tts-aar-auth.*`; temporary `/tmp/tts_bad_sn_verify.out`; `docs/OPERATION_LOG.md`.
- Commands run:
  - Extracted `classes.jar` from delivered AAR.
  - `javap -classpath classes.jar -verbose com.lits.tts.sdk.BuildConfig | sed -n 's/.*ConstantValue: String \\(MFkw.*\\)$/\\1/p' | head -1` to extract `LICENSE_PUBLIC_KEY_B64`.
  - `tts/tools/license/verify_license.py` against `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701/license/amphion-license.lic` using the AAR public key, current SN `4EE9K25419002062`, cert SHA-256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SDK major `1`, SDK release date `2026-06-23`, required feature `TTS`.
  - Repeated verification with bad SN `NOT_AUTHORIZED_SN_000` as a negative control.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: extracted AAR public key length is `124`, public-key string SHA-256 `767520ee2fa6244f797b142636a818d5d258aee48c884e74cdbed042fce429fb`. Positive verification returned `[OK] license 校验通过` with formal license claims `features=ASR,TTS`, `authorizedDeviceHashes=16`, `deviceIdSaltId=DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`, and the current SN hash present in the whitelist. Negative verification with the bad SN returned `[FAIL 1002300018] LICENSE_DEVICE_MISMATCH：device hash not authorized`.
- Notes or next action: delivered AAR is confirmed armed and its extracted public key validates the formal salted-SN license as expected.

## 2026-07-01 11:04 CST

- Goal: Prepare to install the rebuilt v0.2.5.4 demo APK onto the connected Android phone.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `ls -lh /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701/demo/lits-tts-release.apk`
  - `shasum -a 256 <demo apk>`
  - `/Users/amphion/Library/Android/sdk/platform-tools/adb devices -l`
  - `apksigner verify --print-certs <demo apk>`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: target APK exists, size `247M`, SHA-256 `4261e98b992607721646a279bc8113ad2c0a52e98455ea4737b2567245a6e21f`. Android device `4EE9K25419002062` is connected (`model:MIA_AL00`). APK signature verifies with certificate SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`, matching the demo license binding.
- Notes or next action: run `adb install -r` for the target APK and verify package installation.

## 2026-07-01 11:05 CST

- Goal: Install the rebuilt v0.2.5.4 demo APK onto Android device `4EE9K25419002062` and verify the installed package.
- Files changed: Android device package state for `com.tdtech.tiassistant`; `docs/OPERATION_LOG.md`.
- Commands run:
  - `/Users/amphion/Library/Android/sdk/platform-tools/adb -s 4EE9K25419002062 install -r /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260701/demo/lits-tts-release.apk`
  - `adb shell pm path com.tdtech.tiassistant`
  - `adb shell dumpsys package com.tdtech.tiassistant | rg 'versionName|versionCode|firstInstallTime|lastUpdateTime|Package \\['`
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: `adb install -r` returned `Success`. Installed package path is `/data/app/~~mRSw2i_DgWJYxkfxRJQa-A==/com.tdtech.tiassistant-IcC5hEYb3RRbAB35GBrRtw==/base.apk`. Package metadata shows `versionCode=1`, `versionName=0.2.5.4`, `firstInstallTime=2026-06-25 13:52:33`, and `lastUpdateTime=2026-07-01 11:05:36`.
- Notes or next action: APK is installed on the connected Android phone; runtime launch/license behavior can be tested next if needed.

## 2026-07-01 11:17 CST

- Goal: Start rebuilding the same TTS Android AAR, demo APK, and zip package with unchanged build contents/methods, but stage the new delivery as `v3.0`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - `date '+%Y-%m-%d %H:%M %Z'`
  - `git status --short --branch -- tts/android/sample/src/main/assets/amphion-license.lic tts/android/build.gradle.kts tts/android/sample/build.gradle.kts docs/OPERATION_LOG.md`
  - Python script decoded `tts/android/sample/src/main/assets/amphion-license.lic` and printed selected claims.
- Verification result: current demo license SHA-256 is `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`; claims confirm `applicationId=com.tdtech.tiassistant`, `features=TTS`, `expiresAt=2026-08-25`, `authorizedDeviceHashes=0`, and cert SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. This matches the historical non-SN demo APK flow.
- Notes or next action: run the same release build command as before, then sign and stage the package under a `v3.0` delivery name without changing SDK/sample source version fields.

## 2026-07-01 11:19 CST

- Goal: Rebuild AAR/APK with the unchanged release build method and sign the demo APK for the `v3.0` delivery package.
- Files changed: Gradle outputs under `tts/android/sdk/build/` and `tts/android/sample/build/`; `tts/android/sample/build/outputs/apk/release/sample-release-aligned-v3.0.apk`; `tts/android/sample/build/outputs/apk/release/lits-tts-release-v3.0-signed.apk`; `docs/OPERATION_LOG.md`.
- Commands run:
  - `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm PATH=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm/bin:$PATH ./gradlew --no-daemon :sdk:assembleRelease :sample:assembleRelease`
  - `zipalign -f -p 4 sample-release-unsigned.apk sample-release-aligned-v3.0.apk`
  - `apksigner sign --ks ~/.android/debug.keystore --ks-key-alias androiddebugkey --ks-pass pass:android --key-pass pass:android --out lits-tts-release-v3.0-signed.apk sample-release-aligned-v3.0.apk`
  - `apksigner verify --print-certs lits-tts-release-v3.0-signed.apk`
  - `ls -lh` and `shasum -a 256` for the rebuilt AAR and signed APK.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: Gradle build succeeded in 6s. Signed APK verifies with certificate SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. Rebuilt AAR SHA-256 is `4aba1afffe3616c010c989a5ad55972b5542c5c9c81e6bd5a873d593ff39cafb`; signed APK SHA-256 is `4261e98b992607721646a279bc8113ad2c0a52e98455ea4737b2567245a6e21f`, matching the previous package contents.
- Notes or next action: stage a new `v3.0` delivery tree and zip using the rebuilt artifacts while keeping package contents unchanged.

## 2026-07-01 11:22 CST

- Goal: Stage the rebuilt unchanged-content delivery as `v3.0` and create the zip package.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701/`; `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701.zip`; `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701.zip.sha256`; `docs/OPERATION_LOG.md`.
- Commands run:
  - Python staging script copied the rebuilt AAR/APK, formal license, docs, and source/resource snapshot; generated `README.txt`, `VERSION.txt`, `CHECKSUMS.txt`; created the v3.0 zip and `.sha256`.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: v3.0 delivery tree created at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701`; zip created at `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701.zip`; zip SHA-256 `151d3b8c9d73c4a536b488eb72486d6ce55efb203229756ce63083b12990d0d5`; zip size `807214379` bytes; entries `169`.
- Notes or next action: run the same final verification as before against the v3.0 zip.

## 2026-07-01 11:23 CST

- Goal: Run final verification for the v3.0 delivery zip.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run:
  - Python verification script for v3.0 zip CRC, required entries, forbidden entries, `CHECKSUMS.txt`, AAR contents/no-license, APK signature/demo license, formal license claims, and formal license verification using public key extracted from the AAR.
  - `date '+%Y-%m-%d %H:%M %Z'`
- Verification result: final verification passed. Zip `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-v3.0-demo-auth-20260701.zip` SHA-256 `151d3b8c9d73c4a536b488eb72486d6ce55efb203229756ce63083b12990d0d5`, size `807214379` bytes, entries `169`; `CHECKSUMS.txt` verified `167` lines; forbidden entries `0`. AAR SHA-256 `4aba1afffe3616c010c989a5ad55972b5542c5c9c81e6bd5a873d593ff39cafb`, contains no `.lic`, and has AAR public key length `124`. Demo APK SHA-256 `4261e98b992607721646a279bc8113ad2c0a52e98455ea4737b2567245a6e21f`, cert SHA-256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`; demo license has `features=TTS`, `expiresAt=2026-08-25`, `authorizedDeviceHashes=0`. Formal license has `features=ASR,TTS`, `expiresAt=2026-08-25`, `authorizedDeviceHashes=16`, cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, and verifies successfully with the AAR-extracted public key.
- Notes or next action: v3.0 delivery package is ready; build contents and build method remained unchanged from the v0.2.5.4 demo-auth flow while package naming/metadata use `v3.0`.

## 2026-06-30 21:47 UTC+8
- Goal: Sync the Android SDK build code/resources from `Lits_delivery` v2.5.3 into `~/Documents/AmphionRuntime`, and verify frontend/model resource SHA values.
- Files changed:
  - synced `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/` to `/Users/amphion/Documents/AmphionRuntime/tts/android/`
  - synced `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/tools/trial-export/` to both:
    - `/Users/amphion/Documents/AmphionRuntime/tools/trial-export/` (actual path read by `tts/android/build.gradle.kts`)
    - `/Users/amphion/Documents/AmphionRuntime/tts/tools/trial-export/` (existing TTS tools mirror)
  - sync reports are stored in `/Users/amphion/Documents/Lits_delivery/eval_output/android_v2_5_3_sync_to_amphionruntime/`
  - updated operation logs
- Commands run:
  - inspected source/target Android and trial-export layouts.
  - generated pre-sync SHA manifest.
  - ran `rsync --dry-run`; noticed `sample/src/main/assets/amphion-license.lic` would be copied and excluded all `*.lic` from the real sync.
  - first real sync failed under sandbox with `Operation not permitted`; reran with full filesystem permission using the same excludes.
  - ran target frontend unit test once; it failed because Gradle repacked assets from `/Users/amphion/Documents/AmphionRuntime/tools/trial-export`, which was still old.
  - synced trial-export to that actual build path; reran target `:sdk:testDebugUnitTest --tests com.lits.tts.sdk.internal.LitsTtsFrontendTest`.
  - generated final SHA manifests and comparison summary.
- Verification result:
  - target frontend unit test passed: `BUILD SUCCESSFUL in 5s`.
  - final Android sync comparison: source count `110`, target count `110`, no missing/extra files, no SHA/size mismatches.
  - final trial-export comparison at actual build path: source count `30`, target count `30`, no missing/extra files, no SHA/size mismatches.
  - final trial-export comparison at TTS tools mirror: source count `30`, target count `30`, no missing/extra files, no SHA/size mismatches.
  - checked 28 key frontend/model/TN assets, all SHA values match source.
- Notes or next action:
  - `tts/android/build.gradle.kts` resolves `litsModelDir` as `../../tools/trial-export`, so the canonical build resource path in this repo is `/Users/amphion/Documents/AmphionRuntime/tools/trial-export`, not `/Users/amphion/Documents/AmphionRuntime/tts/tools/trial-export`.
  - Excluded `*.lic`, `local.properties`, `build/`, `.gradle/`, and `.DS_Store` from sync to avoid generated/local/license artifacts.

## 2026-06-25 11:27

- Goal: Check how to verify TTS license authentication success for the local authenticated Android SDK/sample.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: searched auth/license files and logs; read `tts/tools/license/README.md`, `tts/android/docs/LICENSE.md`, `tts/android/sample/build.gradle.kts`, `tts/android/sample/src/main/java/com/lits/tts/sample/MainActivity.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechLicense.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechApi.kt`, and `tts/tools/license/verify_license.py`; ran offline license verification for `license/amphion-license.lic` and `license/com.tdtech.tiassistant.lic`.
- Verification result: `python3` lacked `cryptography`, but project `.venv` Python verified both license files with `rc=0` for `applicationId=com.tdtech.tiassistant`; tool warned that `certSha256` binding was not checked because no APK signing certificate SHA256 was supplied.
- Notes: full success criteria should include an armed build, license assets packaged into the host app, runtime `TextToSpeechSdk.licenseStatus().state == LICENSED`, successful `createEngine`, and a negative test where missing/mismatched license fails with a `LICENSE_*` error.

## 2026-06-25 12:57

- Goal: Sync salted SN authentication logic from remote `origin/main` into the current TTS Android SDK.
- Files changed: `docs/OPERATION_LOG.md` so far.
- Commands run: created todo list; exported `origin/main` with `git archive`; read and compared remote/current TTS license files including `TextToSpeechLicense.kt`, `TextToSpeechApi.kt`, `DeviceLicenseFingerprint.kt`, `LicenseClaims.kt`, `LicenseVerifier.kt`, `LicenseGuard.kt`, `sdk/build.gradle.kts`, `LicenseVerifierTest.kt`, and license Python tools.
- Verification result: remote main uses `TtsDeviceIdProvider` + `SHA-256(normalizedSn + deviceIdSaltId)` and parses `bundleName`, `signingCertDigest`, `deviceIdHashAlg`, `deviceIdSaltId`, `authorizedDeviceHashes`, `maintenanceUntil`, `sdkMajor`, and feature gates. Current branch still uses older `deviceSha256` override / `SHA-256("{applicationId}|{ANDROID_ID}")` logic.
- Notes: next step is to port license-layer changes without disturbing current TTS model/NDK build settings.

## 2026-06-25 12:53

- Goal: Look up the Dingqiao salted device-hash formula from remote `main`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: checked git status/remotes/branches; exported `origin/main` to a temporary directory with `git archive`; searched remote-main snapshot for `device_salt_id`, `deviceIdSaltId`, `authorizedDeviceHashes`, and device hash logic; computed salted hash for SN `4EE9K25419002062` using the formula found on remote main.
- Verification result: remote `origin/main` documents/implements the formula `SHA-256(normalizedSn + deviceIdSaltId)`, where `normalizedSn` is trimmed/uppercased and `deviceIdSaltId` is also used as salt material. For SN `4EE9K25419002062` and salt `DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`, the computed hash is `9805621AD5092F0AAC28FAA7B359F74CE2DBF086B10FCF6F9FDABCCD463CC518`; this matches the additional authorized hash shown by the v0.2.7 license verification output from the previous check.
- Notes: previous mismatch came from using the older/current-worktree helper formula `SHA-256("{applicationId}|{deviceCode}")`. The local TTS SDK code needs the remote-main SN provider/salted-hash support to validate v0.2.7 Dingqiao licenses at runtime.

## 2026-06-25 12:51

- Goal: Determine whether we can generate Dingqiao-style salted device hashes.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: read `amphion-dingqiao-license-v0.2.7-20260625/README.txt`, `VERSION.txt`, and `checksum.txt`; searched `AmphionRuntime` and `Lits_delivery` for `device_salt_id`, `deviceIdSaltId`, the Dingqiao salt id, and authorized-device hash generation references.
- Verification result: the package metadata exposes only `device_salt_id=DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71` and `device_hash_alg=SHA-256`; no local script or documented formula for deriving the 16 authorized hashes from SN was found. Current TTS verifier only compares a provided `deviceSha256` against `deviceSha256` / `authorizedDeviceHashes`; it does not derive salted hashes itself.
- Notes: to generate compatible salted hashes, we need Dingqiao's exact device-hash formula and salt material, or Dingqiao must provide the final device hash whitelist. The existing simple SDK helper computes `SHA-256("{applicationId}|{deviceCode}")`.

## 2026-06-25 12:48

- Goal: Verify `amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic` against SN `4EE9K25419002062`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: listed `amphion-dingqiao-license-v0.2.7-20260625`; verified its `amphion-license.lic` with `tts/tools/license/verify_license.py` using AAR public key, `applicationId=com.tdtech.tiassistant`, Dingqiao cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, and SN-derived device hash for `4EE9K25419002062`; reran without `--device-sha256` to isolate non-device checks.
- Verification result: SN-derived device hash is `C019E47CFDE54BA24FD9B11EB7060C34041889EAD5618EE67D2207B8179924AE`; full verification failed with `LICENSE_DEVICE_MISMATCH`. Verification without device check returned `[OK] license 校验通过`; payload binds `bundleName/applicationId=com.tdtech.tiassistant`, Dingqiao signing cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, `expiresAt=2026-08-25`, and 16 `authorizedDeviceHashes`.
- Notes: this license includes `deviceIdSaltId=DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`, suggesting the authorized hashes may have been generated by a salted Dingqiao device-id scheme rather than the current SDK's simple `SHA-256("{applicationId}|{deviceCode}")` helper.

## 2026-06-25 12:29

- Goal: Directly verify the two license files packaged as sample assets.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: used `tts/tools/license/verify_license.py` with AAR/Gradle public key, `applicationId=com.tdtech.tiassistant`, Dingqiao cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, and current USB-SN-derived device SHA256 against `tts/android/sample/src/main/assets/amphion-license.lic` and `tts/android/sample/src/main/assets/com.tdtech.tiassistant.lic`; reran without `--device-sha256` to isolate non-device checks.
- Verification result: both asset license files fail full verification on the current device with `LICENSE_DEVICE_MISMATCH`; the current host device SHA256 is `C019E47CFDE54BA24FD9B11EB7060C34041889EAD5618EE67D2207B8179924AE`, which is not in their authorized device hash list. When device verification is skipped, both files return `[OK] license 校验通过`, confirming their signature, applicationId, and Dingqiao cert SHA256 binding are valid.
- Notes: to pass runtime verification on this device, use the newly issued one-month SN-bound license or issue/update a license whose authorized device list includes this device hash.

## 2026-06-25 12:19

- Goal: Determine which license the current AAR uses for authentication.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: inspected `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1/aar/lits-tts-sdk-0.2.5.1.aar` with `zipinfo`, `unzip`, `jar`, and `javap`; checked delivery demo APK and local sample assets for `.lic` files.
- Verification result: AAR contains no `.lic` assets. AAR is armed via non-empty `com.lits.tts.sdk.BuildConfig.LICENSE_PUBLIC_KEY_B64` and contains license classes (`LicenseGuard`, `LicenseVerifier`, `TtsLicenseOptions`, `TtsLicenseStatus`, etc.). The delivery demo APK contains `assets/amphion-license.lic` and `assets/com.tdtech.tiassistant.lic`; local sample assets contain the same two original files. The newly issued `license/com.tdtech.tiassistant-20260625-1m-sn.lic` is not currently packaged into the AAR or demo APK.
- Notes: concrete `.lic` files are supplied by the host app/APK assets, not by the AAR. To use the newly issued one-month license in a demo APK, copy/rename it into the app assets (normally as `amphion-license.lic`) and rebuild the APK.

## 2026-06-25 11:47

- Goal: Issue a new one-month TTS license using the local private key.
- Files changed: `license/com.tdtech.tiassistant-20260625-1m-sn.lic`, `docs/OPERATION_LOG.md`.
- Commands run: read `tts/tools/license/issue_license.py`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/DeviceLicenseFingerprint.kt`, `current_usb_device_sn.txt`, and `LicenseClaims.kt`; user chose to bind the new license to existing target cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, bind current USB SN device, and write a new file; ran `tts/tools/license/issue_license.py` with local `amphion-license-private.pem`; verified the resulting license with `tts/tools/license/verify_license.py` using the public key, app id, cert SHA256, and computed device SHA256.
- Verification result: created `license/com.tdtech.tiassistant-20260625-1m-sn.lic`; `applicationId=com.tdtech.tiassistant`; `customer=TD Tech / Dingqiao`; `licenseId=DINGQIAO-TDTECH-20260625-1M-SN`; `issuedAt=2026-06-25`; `expiresAt=2026-07-25`; `installTier=TRIAL_1M`; `features=TTS_ZH_EN,TTS_EN_US`; `deviceSha256=C019E47CFDE54BA24FD9B11EB7060C34041889EAD5618EE67D2207B8179924AE`. Offline verification returned `[OK] license 校验通过`.
- Notes: did not overwrite `license/amphion-license.lic` or `license/com.tdtech.tiassistant.lic`. This license still requires the APK to be signed with cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8` and run on the bound device fingerprint.

## 2026-06-25 11:41

- Goal: Explain local sensitive files `current_usb_device_sn.txt` and `amphion-license-private.pem`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: searched references to `current_usb_device_sn`, `amphion-license-private.pem`, private/license/device binding fields, and `.gitignore`; located both files with glob; attempted to derive only a public fingerprint from the private key but safety review blocked private-key processing; listed file metadata only.
- Verification result: `current_usb_device_sn.txt` and `amphion-license-private.pem` are local ignored files in the repo root. `.gitignore` ignores `*-private.pem`, `.secure/`, and `current_usb_device_sn.txt`. License docs/scripts use `amphion-license-private.pem` as the offline ECDSA private key for signing `.lic`; prior logs show device SN was used to derive device fingerprints for device-bound license checks.
- Notes: these files are not an Android APK signing keystore and cannot by themselves sign a release APK with cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`.

## 2026-06-25 11:39

- Goal: Confirm release APK must be signed with the certificate bound by the two required license files and locate the matching keystore.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: searched `/Users/amphion/Documents/AmphionRuntime` and `/Users/amphion/Documents` for `.jks`, `.keystore`, `.p12`, and `.pfx`; searched Android Gradle files/properties for signing config; inspected APK certificate and decoded license claims.
- Verification result: no Android signing keystore file or custom Gradle `signingConfig` was found locally. Existing APK is signed by default Android Debug cert SHA256 `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`; required licenses bind cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`.
- Notes: to produce the requested release APK using `license/amphion-license.lic` and `license/com.tdtech.tiassistant.lic`, provide or configure the keystore whose signing certificate SHA256 is `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, then sign the release APK and rerun full license verification.

## 2026-06-25 11:37

- Goal: Identify which signing certificate is on the authenticated debug APK and why it mismatches the required license files under `license/`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: ran `apksigner verify --print-certs` on `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`; searched Gradle files for signing config; decoded claims from `license/amphion-license.lic` and `license/com.tdtech.tiassistant.lic`.
- Verification result: APK is signed with the default Android Debug certificate (`DN: C=US, O=Android, CN=Android Debug`) whose SHA256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. The two required license files both bind `applicationId/bundleName=com.tdtech.tiassistant` and `certSha256/signingCertDigest=6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`. Gradle sample config has no custom signingConfig, so debug builds use the default Android debug keystore.
- Notes: the required license files are packaged, but the APK must be signed with the certificate whose SHA256 is `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8` for full license verification to pass.

## 2026-06-25 11:34

- Goal: Check whether `/Users/amphion/Documents/AmphionRuntime` contains an APK built today with license authentication enabled.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: listed `tts/android/sample/build/outputs/apk/debug` and `release`; inspected `tts/android/sample/build/outputs/apk/debug/sample-debug.apk` packaged license assets with `zipinfo`; checked package metadata with `aapt dump badging`; confirmed `AMPHION_LICENSE_PUBLIC_KEY` is set in `tts/android/gradle.properties`.
- Verification result: today-built authenticated debug APK exists at `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`, timestamp `2026-06-25 11:06`, size `255M`, package `com.tdtech.tiassistant`, versionName `0.2.5.1`; it packages `assets/amphion-license.lic` and `assets/com.tdtech.tiassistant.lic`, and the build has a non-empty `AMPHION_LICENSE_PUBLIC_KEY`. Release APK present is `sample-release-unsigned.apk` from `2026-06-24 19:21`.
- Notes: this confirms a today-built armed/licensed debug APK exists, but previous full verification showed its debug signing certificate does not match the cert bound in the packaged license files (`LICENSE_CERT_MISMATCH`).

## 2026-06-25 11:31

- Goal: Fully verify the authenticated sample APK against the license-bound APK signing certificate.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: listed `tts/android/sample/build/outputs/apk/{debug,release}` and `license/`; checked packaged license assets with `zipinfo`; attempted `apksigner verify --print-certs` once without Java and failed; reran with `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm`; passed the extracted APK cert SHA256 to `tts/tools/license/verify_license.py` for `license/amphion-license.lic` and `license/com.tdtech.tiassistant.lic`.
- Verification result: `tts/android/sample/build/outputs/apk/debug/sample-debug.apk` contains `assets/amphion-license.lic` and `assets/com.tdtech.tiassistant.lic`; current APK cert SHA256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`; both license files failed with `LICENSE_CERT_MISMATCH` because the license-bound cert SHA256 is `6E9B5AAEEF2797755CD3405952D9693E8DB173C0A1733E38BF5BD16F9A6022E8`.
- Notes: the current debug APK does not verify as a successful license-auth artifact. To make it pass, sign with the certificate bound in the license or issue a new license bound to this APK certificate, then rerun full offline verification and a runtime `TextToSpeechSdk.licenseStatus()` check.

# AmphionRuntime Operation Log

## 2026-06-24 17:46

- Goal: Start syncing latest Android v2.5 TTS SDK code from `Lits_delivery` into current `AmphionRuntime`, then rebuild an authenticated Android SDK.
- Files changed: none yet.
- Commands run: checked current `AmphionRuntime` git status and inspected `Lits_delivery` Android project candidates.
- Verification result: located latest source candidate at `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime`; current repo has no existing `docs/OPERATION_LOG.md`, so this log was created.
- Notes: user requested every local operation be logged and the rule be added to the project skill.

## 2026-06-24 17:48

- Goal: Update logging rules and inspect Android v2.5 source/target project structure before synchronization.
- Files changed: `/Users/amphion/Documents/Lits_delivery/.codex/skills/lits-delivery/SKILL.md`, `/Users/amphion/Documents/Lits_delivery/docs/OPERATION_LOG.md`, `docs/OPERATION_LOG.md`.
- Commands run: listed `/Users/amphion/Documents/Lits_delivery` Android project candidates; globbed Android source files and Gradle wrappers; inspected source and target project root layouts.
- Verification result: source and target Android project layouts match; source path is `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime`, target path is `/Users/amphion/Documents/AmphionRuntime/tts/android`.
- Notes: sync will exclude build caches, local machine config, private license files, and the newly added license verifier files, then re-merge auth hooks into API/Gradle/EngineRegistry.

## 2026-06-24 17:49

- Goal: Add a hard rule that auth/licensing files and private keys must never be synced to remotes.
- Files changed: `/Users/amphion/Documents/Lits_delivery/.codex/skills/lits-delivery/SKILL.md`, `.git/info/exclude`, `docs/OPERATION_LOG.md`.
- Commands run: read the Lits Delivery skill, current operation logs, and local git exclude file.
- Verification result: skill now has `Hard Rule: Auth And Secrets Stay Local`; local git exclude now ignores private key, SN list, `.secure/`, and local auth/license source/test files.
- Notes: no remote sync, commit, or push was performed.

## 2026-06-24 17:50

- Goal: Resume Android v2.5 source sync while preserving local-only authentication artifacts and secrets.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none yet.
- Verification result: sync plan updated to exclude local auth/private artifacts and re-apply auth hooks only in the local workspace.
- Notes: no remote sync, commit, or push will be performed.

## 2026-06-24 17:51

- Goal: Dry-run Android v2.5 source synchronization.
- Files changed: none.
- Commands run: `rsync -a --delete --dry-run --itemize-changes ... Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/ tts/android/`.
- Verification result: dry-run would update root/sdk Gradle files, SDK packaged assets, `TextToSpeechApi.kt`, `EngineRegistry.kt`, asset/frontend internals, and frontend tests; local auth/private files are excluded.
- Notes: will perform real sync and then re-apply local auth hooks.

## 2026-06-24 17:52

- Goal: Sync latest Android v2.5 source code and re-apply local auth hooks.
- Files changed: `tts/android/build.gradle.kts`, `tts/android/sdk/build.gradle.kts`, SDK packaged assets under `tts/android/sdk/src/main/assets/`, `TextToSpeechApi.kt`, `EngineRegistry.kt`, `LitsTtsAssetInstaller.kt`, `LitsTtsAssetRegistry.kt`, `LitsTtsFrontend.kt`, `TranssionTnNormalizer.kt`, `LitsTtsFrontendTest.kt`.
- Commands run: real `rsync -a --delete --itemize-changes ...`; read post-sync `sdk/build.gradle.kts`, `TextToSpeechApi.kt`, and `EngineRegistry.kt`.
- Verification result: source sync completed; auth BuildConfig injection, public license APIs/error codes, and `LicenseGuard.gate()` were re-applied locally.
- Notes: private key, SN list, `.secure/`, and local auth/license implementation files were excluded from sync and remain local-only.

## 2026-06-24 17:53

- Goal: Build authenticated Android release SDK after v2.5 sync.
- Files changed: build outputs under `tts/android/sdk/build/` only.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease`.
- Verification result: failed at `:sdk:configureNdkBuildRelease[arm64-v8a]`; Android NDK reported missing `transsion_lits/build/android-icu/android-arm64-build/lib/libicui18n.a` under the current `AmphionRuntime` root.
- Notes: failure is native dependency layout related; next step is to provide the expected `transsion_lits` Android build artifacts locally, without syncing auth/private files to any remote.

## 2026-06-24 17:54

- Goal: Provide local native TN/ICU build artifacts expected by Android v2.5 `Android.mk`.
- Files changed: `.git/info/exclude`, local symlink `transsion_lits -> /Users/amphion/Documents/Lits_delivery/transsion_lits`.
- Commands run: listed current repo root, created symlink, verified `transsion_lits/build/android-icu/android-arm64-build/lib/libicui18n.a` exists through the symlink.
- Verification result: required ICU static library is now visible at the path expected by `Android.mk`.
- Notes: symlink is local-only and excluded from git; no remote sync was performed.

## 2026-06-24 17:55

- Goal: Retry authenticated Android release SDK build after adding local `transsion_lits` symlink.
- Files changed: build outputs under `tts/android/sdk/build/` only.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease`.
- Verification result: failed again at `:sdk:configureNdkBuildRelease[arm64-v8a]`; `Android.mk` resolves `../../../../../../..` from `sdk/src/main/jni` to `/Users/amphion/Documents`, so it expects `/Users/amphion/Documents/transsion_lits`, not `/Users/amphion/Documents/AmphionRuntime/transsion_lits`.
- Notes: next step is to create a local `/Users/amphion/Documents/transsion_lits` symlink to the existing `Lits_delivery/transsion_lits` artifacts; this is outside git and will not sync to remote.

## 2026-06-24 17:56

- Goal: Provide `Android.mk`'s actual expected `/Users/amphion/Documents/transsion_lits` native dependency path.
- Files changed: local symlink `/Users/amphion/Documents/transsion_lits -> /Users/amphion/Documents/Lits_delivery/transsion_lits`.
- Commands run: checked whether `/Users/amphion/Documents/transsion_lits` exists, created symlink if missing, verified `build/android-icu/android-arm64-build/lib/libicui18n.a`.
- Verification result: ICU static library is visible at `/Users/amphion/Documents/transsion_lits/build/android-icu/android-arm64-build/lib/libicui18n.a`.
- Notes: this symlink is outside git and will not sync to remote.

## 2026-06-24 17:57

- Goal: Rebuild authenticated Android SDK after native dependency symlink fix.
- Files changed: build outputs and synced model assets under `tts/android/sdk/src/main/assets/`.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease`.
- Verification result: native dependency resolution passed; build failed in `:sdk:testDebugUnitTest` because 22 `LitsTtsFrontendTest` cases throw `kotlin.io.NoSuchFileException` at line 440.
- Notes: investigate missing frontend test fixture/resource before deciding whether to rerun tests or compile release AAR separately.

## 2026-06-24 17:58

- Goal: Restore local v2.5 model trial-export package required by Gradle asset packing and frontend tests.
- Files changed: `.git/info/exclude`, local files under `tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`.
- Commands run: listed current `tools/`; created target trial-export directory; rsynced the v2.5 package from `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/tools/trial-export/.../0.1.0/`; listed synced files.
- Verification result: required lexicon/json/onnx/rules/TN files are present in current repo's local `tools/trial-export`; directory is excluded from git.
- Notes: no auth/private files were synced to remote; no remote operation was performed.

## 2026-06-24 17:59

- Goal: Build and stage a local authenticated Android v2.5 TTS SDK AAR.
- Files changed: Gradle build outputs under `tts/android/sdk/build/`; local staged artifact `.secure/android-sdk/lits-transsion-tts-sdk-vocos24k-0.2.5-auth.aar`.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease`; copied `sdk-release.aar` to `.secure/android-sdk/lits-transsion-tts-sdk-vocos24k-0.2.5-auth.aar`; ran `shasum -a 256`.
- Verification result: Gradle build successful; release AAR size is 202M; SHA256 is `c16244c854fff21db595dccaa6bb0799b2b7fb2c2817c6ce0211099d5a4a225b`.
- Notes: staged AAR is local-only under ignored `.secure/` because it contains the local auth-enabled SDK build.

## 2026-06-24 18:00

- Goal: Final safety/status check after authenticated SDK build.
- Files changed: `/Users/amphion/Documents/Lits_delivery/docs/OPERATION_LOG.md`, `docs/OPERATION_LOG.md`.
- Commands run: `git diff --check`; `git status --short --ignored` filtered for SDK/auth/secret artifacts; listed and checksummed `.secure/android-sdk/lits-transsion-tts-sdk-vocos24k-0.2.5-auth.aar`.
- Verification result: `git diff --check` passed; private key, SN list, `.secure/`, local auth source/test files, local model package, symlinks, and build outputs are ignored/local-only.
- Notes: no commit, push, PR, delivery upload, or remote sync was performed.

## 2026-06-24 17:56

- Goal: Prepare remote branch sync while excluding SDK artifacts, auth files, private keys, SN list, licenses, and `.secure/`.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `git status --short --ignored`, `git diff --stat`, `git diff`, and `git log --oneline -8`.
- Verification result: sensitive/local-only files are ignored; tracked diffs include both v2.5 source sync and local auth hook changes, so only safe code files will be staged for remote sync.
- Notes: compiled AAR and auth/private artifacts will not be committed or pushed.

## 2026-06-24 17:57

- Goal: Stage only remote-safe Android v2.5 source changes.
- Files changed: git index only; `docs/OPERATION_LOG.md`.
- Commands run: `git diff` for safe Android files; attempted filtered review of excluded auth-touched diff; staged six Android frontend/asset/test files; ran `git status --short`, `git diff --cached --stat`, and `git diff --cached --check`.
- Verification result: staged diff contains only `tts/android/build.gradle.kts`, `LitsTtsAssetInstaller.kt`, `LitsTtsAssetRegistry.kt`, `LitsTtsFrontend.kt`, `TranssionTnNormalizer.kt`, and `LitsTtsFrontendTest.kt`; no SDK AAR, private key, SN list, `.secure/`, generated license, or local auth implementation files are staged.
- Notes: local auth-related tracked modifications remain unstaged/local-only.

## 2026-06-24 17:58

- Goal: Commit and push only remote-safe Android v2.5 code changes.
- Files changed: remote branch `tts-android-harmony-v2.4` now includes commit `fc8a243`.
- Commands run: `git commit -m "fix(tts): sync Android v2.5 frontend updates"`, `git push`, `git status --short --branch`, `git log -1 --oneline`, and `git show --stat --oneline --name-only HEAD`.
- Verification result: pushed commit `fc8a243` contains exactly six files: `tts/android/build.gradle.kts`, `LitsTtsAssetInstaller.kt`, `LitsTtsAssetRegistry.kt`, `LitsTtsFrontend.kt`, `TranssionTnNormalizer.kt`, and `LitsTtsFrontendTest.kt`.
- Notes: compiled SDK AAR, private key, SN list, `.secure/`, generated licenses, local auth implementation files, and local auth hook changes were not committed or pushed.

## 2026-06-24 17:58

- Goal: Draft a customer-facing delivery email for the authenticated Android v2.5 TTS SDK.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: email draft prepared in chat based on the requested v0.1.1 tdtech delivery-mail structure and current local v2.5 authenticated AAR artifact information.
- Notes: no code, SDK artifact, private key, license, SN list, commit, push, or remote sync operation was performed.

## 2026-06-24 18:00

- Goal: Check whether the authenticated Android SDK build generated a zip package.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: globbed `**/*.zip` and `**/build/delivery/**`; listed `.secure/android-sdk`, `tts/android/build`, and `tts/android/build/delivery`.
- Verification result: no zip package exists in the current workspace; only `.secure/android-sdk/lits-transsion-tts-sdk-vocos24k-0.2.5-auth.aar` was staged from the release build.
- Notes: previous build ran `:sdk:testDebugUnitTest :sdk:assembleRelease`, not a delivery zip task.

## 2026-06-24 18:02

- Goal: Start creating a local zip package matching the v2.5 Android SDK delivery-email structure.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none yet.
- Verification result: planned package layout is `aar/`, `license/`, `docs/`, `README.txt`, and `VERSION.txt`, using the local authenticated AAR and local Android license.
- Notes: zip will be local-only under `.secure/delivery/`; private key, SN list, source auth files, and remote sync are excluded.

## 2026-06-24 18:04

- Goal: Create and verify the local v2.5 Android SDK delivery zip.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: verified AAR/license/docs inputs; collected git commit/branch; generated staging directory, `README.txt`, `VERSION.txt`, and zip via Python; listed zip size; verified zip entries via Python.
- Verification result: zip created at `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, size 201M, SHA256 `2c1776c97893df75236b7e99333a9726126396b756a38b2ae883ccd6b853d9db`; required entries `aar/`, `license/`, `docs/`, `README.txt`, and `VERSION.txt` are present.
- Notes: package is local-only under ignored `.secure/`; private key and SN source list are not included.

## 2026-06-24 18:08

- Goal: Rebuild delivery zip documentation from remote `origin/main` docs.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: listed `origin/main` Android TTS docs with `git ls-tree`; checked current branch status and main revisions.
- Verification result: `origin/main` docs set is `tts/android/docs/API.md`, `DELIVERY.md`, `INTEGRATION.md`, `LICENSE.md`, `PSEUDOCODE.md`, plus `tts/android/README.md`, `LICENSE`, and `NOTICE`.
- Notes: next step is to replace `.secure/delivery/.../docs/` with those `origin/main` files and recreate the zip.

## 2026-06-24 18:09

- Goal: Replace delivery zip `docs/` with the remote `origin/main` documentation set and verify the result.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/docs/`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/VERSION.txt`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: Python script used `git show origin/main:<path>` to write `API.md`, `DELIVERY.md`, `INTEGRATION.md`, `LICENSE.md`, `PSEUDOCODE.md`, `README.md`, `LICENSE`, and `NOTICE` into the staging `docs/`; recreated zip and checksum; Python zip verifier checked required and forbidden docs entries.
- Verification result: zip docs now come from `origin/main` commit `f31eadd1cf9b`; old current-branch docs `STREAMING_ANDROID_PLAN.md`, `V2_STREAMING_INFERENCE.md`, and `CHANGELOG.md` are not present; new zip SHA256 is `1e467053ae746f88c73f67710b250d0e15ffbac08a72efe00828abd317ba4e8a`.
- Notes: package remains local-only under ignored `.secure/`; private key and SN source list are not included.

## 2026-06-24 18:10

- Goal: List the current delivery zip contents for review.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: Python `zipfile` listing of `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`.
- Verification result: zip contains `README.txt`, `VERSION.txt`, one AAR under `aar/`, eight documentation files under `docs/`, and one license under `license/`.
- Notes: no package contents were modified by this query.

## 2026-06-24 18:14

- Goal: Add missing demo APK to the local Android v2.5 delivery zip.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none yet.
- Verification result: identified that current zip lacks `demo/`.
- Notes: will build local sample APK with sample package license asset, then recreate zip with `demo/lits-tts-sample-debug.apk`; private key and SN source list remain excluded.

## 2026-06-24 18:15

- Goal: Build demo APK and rebuild delivery zip with `demo/lits-tts-sample-debug.apk`.
- Files changed: `.git/info/exclude`, local sample asset `tts/android/sample/src/main/assets/lits-tts-license.lic`, build output `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/demo/lits-tts-sample-debug.apk`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip.sha256`, `README.txt`, `VERSION.txt`, and `docs/OPERATION_LOG.md`.
- Commands run: read sample `build.gradle.kts` and local exclude; copied sample license to sample assets; ran `./tts/android/gradlew -p tts/android --no-daemon :sample:assembleDebug`; copied APK into `demo/`; regenerated zip and checksum; verified zip entries with Python `zipfile`.
- Verification result: sample APK build successful; demo APK size 255M; demo APK SHA256 `0da8121fdc1333738f1c8c1e15fa04c6cdfd8196a429a4bc96166b1723c17485`; rebuilt zip size 411M; rebuilt zip SHA256 `75f4484da38ffbec25da4fac776a2a40bb49c1da789e7b49ad19ac0c70d5c134`; required `demo/lits-tts-sample-debug.apk` entry is present.
- Notes: sample license asset, build outputs, and delivery zip remain local-only/ignored; private key and SN source list are not included in the zip.

## 2026-06-24 18:16

- Goal: Add missing `android-src/TTS/` source snapshot to the local delivery zip.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none yet.
- Verification result: identified current zip lacks Android source snapshot.
- Notes: source snapshot will exclude build caches, compiled APK/AAR outputs, private key, SN list, `.secure/`, and local auth implementation files.

## 2026-06-24 18:18

- Goal: Add Android source snapshot and model package to delivery zip.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/android-src/TTS/`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/README.txt`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/VERSION.txt`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: Python script copied clean v2.5 Android source from `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime` into `android-src/TTS/android/AmphionRuntime`, copied the v2.5 model package into `android-src/TTS/tools/trial-export/.../0.1.0`, regenerated zip/checksum, and verified source snapshot entries.
- Verification result: `android-src/TTS/` contains 84 files; required Gradle project files and model `manifest.json` are present; source snapshot excludes build caches, APK/AAR outputs, private keys, SN list, `.secure/`, and local auth implementation files. New zip size is 599M; SHA256 is `c5848f11754b636e1b2bfda65b766cf251367da2a145ad97b7d4c099e35d91d0`.
- Notes: source snapshot is included for integration/reference; local auth secrets remain excluded.

## 2026-06-24 18:20

- Goal: Compare current delivery zip against the requested delivery-email contents.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: Python `zipfile` checklist for AAR, license, demo APK, Android source snapshot, sample source, model package, docs, `README.txt`, and `VERSION.txt`.
- Verification result: all required delivery-email content categories are present; missing items: none.
- Notes: zip remains local-only under ignored `.secure/`.

## 2026-06-24 18:22

- Goal: Check delivery package details against remote `origin/main` style and fill any gap.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/CHECKSUMS.txt`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: listed and read `origin/main` Android delivery references; added `CHECKSUMS.txt`; regenerated zip and checksum; ran final Python zip structure and forbidden-token verification.
- Verification result: `CHECKSUMS.txt` was the main missing main-style detail and is now included; final zip has 98 entries, size 599M, SHA256 `334555c7186e85a83a5422e215d5b37032eb041d77cec22685ad54030d0bb658`; required AAR/demo/license/docs/android-src/model entries are present; forbidden private key/SN/build-cache/local-property entries are absent.
- Notes: package remains local-only under ignored `.secure/`; no remote sync was performed.

## 2026-06-24 18:29

- Goal: Draft a TTS Android SDK v2.5 delivery email in the style of the Dingqiao ASR v0.2.6 formal delivery email.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: email draft prepared in chat using the current local delivery zip path, package structure, build provenance, and checksum information.
- Notes: no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:32

- Goal: Rename delivery demo APK entry from sample/debug naming to release naming.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none yet.
- Verification result: plan is to build `:sample:assembleRelease` and package the resulting release APK as `demo/lits-tts-release.apk`.
- Notes: if release build cannot produce an installable APK, record the failure before choosing a fallback.

## 2026-06-24 18:34

- Goal: Build sample release APK and update delivery package demo name.
- Files changed: sample release build outputs under `tts/android/sample/build/outputs/apk/release/`, `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/demo/lits-tts-release.apk`, `.secure/delivery/.../README.txt`, `.secure/delivery/.../VERSION.txt`, `.secure/delivery/.../CHECKSUMS.txt`, `.secure/delivery/...zip`, `.secure/delivery/...zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sample:assembleRelease`; Python script replaced `demo/lits-tts-sample-debug.apk` with `demo/lits-tts-release.apk`, updated metadata/checksums, regenerated zip; Python zip verifier checked the new demo APK name and absence of old sample-debug names.
- Verification result: sample release build succeeded; delivery demo APK is now `demo/lits-tts-release.apk`; old `sample-debug` name is absent. Demo APK SHA256 `c883c351b31d84a1572cea7eed381744fcdfc3022b6b4b3594665d3bc267129d`; new zip size 591M; new zip SHA256 `da7794f95222350d28a90e054e4e17b3def7110e8b96da2de7d6a78c6a260bd1`.
- Notes: release APK is Gradle sample release output; package remains local-only under ignored `.secure/`.

## 2026-06-24 18:36

- Goal: Refine the delivery email "version highlights" wording for TTS Android SDK v2.5.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: prepared polished highlight bullets in chat covering audio quality, engine load/first-packet/RTF, numeric/polyphone readings, stop-then-speak latency, and emoji/symbol robustness.
- Notes: no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:36

- Goal: Create a reusable delivery email document for the TTS Android SDK v0.2.5 package.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.md`, `docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: email document was written with package name, structure, integration steps, version highlights, AAR/APK checksums, and acceptance suggestions.
- Notes: document is local-only under ignored `.secure/`; no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:38

- Goal: Convert the delivery email document from Markdown to pure text.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.txt`, `docs/OPERATION_LOG.md`.
- Commands run: read the Markdown email document and created a `.txt` version.
- Verification result: pure text email file was created without Markdown headings or code fences.
- Notes: document is local-only under ignored `.secure/`; no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:49

- Goal: Correct the pure text delivery email's formal App integration steps.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.txt`, `docs/OPERATION_LOG.md`.
- Commands run: read the current txt email, read `tts/android/docs/INTEGRATION.md`, read `TextToSpeechApi.kt`, and verified the updated txt section.
- Verification result: integration steps now cover AAR dependency, optional Kotlin stdlib/noCompress guidance, license placement and constraints, `TextToSpeechSdk.init`, `setWorkPath`, callback `createEngine`, listener setup, and `speak`.
- Notes: text document is local-only under ignored `.secure/`; no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:50

- Goal: Simplify the pure text email's formal App integration steps to match the user's reference format.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.txt`, `docs/OPERATION_LOG.md`.
- Commands run: edited the txt email, read back the integration section, and removed a duplicated API reference paragraph.
- Verification result: integration section now uses the requested five-step structure: copy AAR, add dependency, place license, initialize SDK, then create engine/synthesize with examples in `docs/INTEGRATION.md` and `android-src/TTS/android/AmphionRuntime/sample/`.
- Notes: text document is local-only under ignored `.secure/`; no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 18:52

- Goal: Add nova 15 / Kirin 8020 on-device measurement summary to the pure text delivery email.
- Files changed: `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.txt`, `docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: email now lists engine load time about 3 seconds, first-packet latency about 300 ms, RTF about 0.4, Demo APK size about 247 MB, and SDK AAR size about 202 MB.
- Notes: text document is local-only under ignored `.secure/`; no package contents, code, secrets, commits, pushes, or remote sync operations were performed.

## 2026-06-24 19:00

- Goal: Final delivery zip self-check before handoff.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: Python `zipfile` CRC test, required-entry check, docs-set check, forbidden-entry check, and `CHECKSUMS.txt` hash verification for `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624.zip`.
- Verification result: self-check passed; zip size 619,978,843 bytes; SHA256 `da7794f95222350d28a90e054e4e17b3def7110e8b96da2de7d6a78c6a260bd1`; 98 entries; AAR 211,381,851 bytes; demo APK 259,131,797 bytes; `android-src/TTS/` has 84 entries; `CHECKSUMS.txt` has 5 verified lines.
- Notes: no private key, SN source list, `.secure/`, `.git`, `.gradle`, build cache, local.properties, sample-debug APK, old demo name, current-branch-only docs, or local auth implementation source files were found inside the zip.

## 2026-06-24 19:09

- Goal: Install the delivery demo APK onto the connected Android phone.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `adb devices -l`; listed target APK; attempted `adb -s 4EE9K25419002062 install -r .../demo/lits-tts-release.apk`.
- Verification result: device `4EE9K25419002062` was detected, but install failed with `INSTALL_PARSE_FAILED_NO_CERTIFICATES`; the packaged release APK is unsigned.
- Notes: next step is to sign the release APK locally, update the delivery package demo APK, and retry installation.

## 2026-06-24 19:12

- Goal: Stop modifying the delivery zip per user instruction.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: signed local release demo APK, refreshed local delivery zip/checksum, attempted install; install failed due to existing `com.lits.tts.sample` signature mismatch, then a follow-up uninstall/install command was interrupted by the user.
- Verification result: user instructed not to touch the delivery zip; no further package modification or install action will be performed without explicit confirmation.
- Notes: latest user instruction supersedes the previous install/update plan.

## 2026-06-24 19:14

- Goal: Install the existing demo APK onto the connected Android phone without modifying the delivery zip.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: checked package presence with `adb shell pm path com.lits.tts.sample`; installed `.secure/delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624/demo/lits-tts-release.apk`; verified installed package path with `pm path`.
- Verification result: install succeeded on device `4EE9K25419002062`; package path is `/data/app/~~usb77V8IvZcWMz6hTf-kuQ==/com.lits.tts.sample-4r5zFE_EvFSvTRkfl8HpMA==/base.apk`.
- Notes: command reported the package was not installed before install; delivery zip was not modified during this step.

## 2026-06-24 19:17

- Goal: Diagnose why the installed demo reports license load/check failure.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: inspected APK asset list for `assets/lits-tts-license.lic`; read sample `MainActivity.kt`; compared license `deviceSha256` against SN-derived and Android-ID-derived fingerprints using `adb shell settings get secure android_id`.
- Verification result: APK contains `assets/lits-tts-license.lic`; license is bound to SN-derived fingerprint `716AA31DBFB7580C5D157618489F8F561DE248211E37B35735C80D5D3CF2A354`, while SDK default runtime fingerprint from `ANDROID_ID=952d68c29706c6f3` is `17BAA9E54DBBC41E43E250A1707C395AC51B110030AD5CA6A19767E66863D0DF`.
- Notes: failure is caused by device fingerprint mismatch, not missing license asset. Demo must either pass the SN-derived `deviceSha256` into `TtsLicenseOptions` or use a license signed for the SDK's default Android-ID fingerprint.

## 2026-06-24 19:19

- Goal: Re-sign Demo license for the default Android-ID-derived device fingerprint and reinstall Demo APK.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: read Android ID from device `4EE9K25419002062`; generated a new local demo license for `com.lits.tts.sample` using Android-ID-derived device fingerprint; copied it into sample assets; ran `./tts/android/gradlew -p tts/android --no-daemon :sample:assembleRelease`; signed the release APK with local debug keystore; verified APK signature with `apksigner`; installed it via `adb`; verified `pm path com.lits.tts.sample`.
- Verification result: Android ID `952d68c29706c6f3`; device fingerprint `17BAA9E54DBBC41E43E250A1707C395AC51B110030AD5CA6A19767E66863D0DF`; build/sign/install succeeded; installed package path `/data/app/~~XApwRvceeuOeiniMLIfj-A==/com.lits.tts.sample-gAWA6k34PVImR6LFvWZCwA==/base.apk`; local APK SHA256 `b2b2db6d3db4df2a3e8b04b30e5735973a2d71d8d11058c3ec4736250fe9c05b`.
- Notes: user chose the Android-ID license approach; delivery zip was not modified during this install-test flow.

## 2026-06-24 19:23

- Goal: Install the latest v2.5 APK from `/Users/amphion/Documents/Lits_delivery` instead of the locally rebuilt APK.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: listed newest APKs under `/Users/amphion/Documents/Lits_delivery`; attempted uninstall of `com.lits.tts.sample`; installed `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime/sample/build/outputs/apk/debug/sample-debug.apk`; verified `pm path`; listed APK size and SHA256.
- Verification result: latest v2.5 APK installed successfully on device `4EE9K25419002062`; package path `/data/app/~~mT1q_HkQ0ujNM7xecAG4iA==/com.lits.tts.sample-beRluz4W6YaVGyaXyZ7PcA==/base.apk`; APK size 261M; SHA256 `4adff0cfdfc583bd21e8a4e72dce3f2679080e16fa5d87c2767d098ae8579d25`.
- Notes: initial uninstall returned `DELETE_FAILED_INTERNAL_ERROR`, but install succeeded afterward; installed APK came directly from `Lits_delivery` latest v2.5 build.

## 2026-06-25 10:56

- Goal: Sync v2.5.1 Android code and build authenticated/license delivery using existing license files.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: located `license/com.tdtech.tiassistant.lic` and `license/amphion-license.lic`; searched `Lits_delivery` for matching license files.
- Verification result: both requested license files exist under `/Users/amphion/Documents/AmphionRuntime/license/`; no matching files were found under `/Users/amphion/Documents/Lits_delivery`.
- Notes: User explicitly instructed to use `com.tdtech.tiassistant.lic` and `amphion-license.lic`; do not generate a replacement license.

## 2026-06-25 11:00

- Goal: Sync v2.5.1 Android source/model package and align TTS license handling with the requested existing license files.
- Files changed: `tts/android/`, `tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`, `tts/tools/android/`, `tts/tools/license/`, `docs/OPERATION_LOG.md`.
- Commands run: synced v2.5.1 Android source from `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime` into `tts/android` while preserving local auth entry points; synced v2.5.1 model package into root `tools/trial-export/...`; copied `license/amphion-license.lic` and `license/com.tdtech.tiassistant.lic` into `tts/android/sample/src/main/assets`; removed stale `lits-tts-license.lic`.
- Verification result: Updated Gradle public key property to `AMPHION_LICENSE_PUBLIC_KEY`, sample `applicationId` to `com.tdtech.tiassistant`, SDK default license asset to `amphion-license.lic`, and TTS license verifier to accept `authorizedDeviceHashes`, `bundleName`, and `signingCertDigest`. Delivery scripts now validate v2.5.1 external-loop ONNX assets instead of stale `.ort` names.
- Notes: A local payload metadata print was blocked by safety review; proceeding without exposing license payload. Build and package verification still need to confirm the requested license filenames are present in outputs.

## 2026-06-25 11:06

- Goal: Build authenticated v2.5.1 Android AAR and delivery zip using `com.tdtech.tiassistant.lic` and `amphion-license.lic`.
- Files changed: `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`, `tts/android/sdk/build/outputs/aar/sdk-release.aar`, `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1/`, `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1-20260625.zip`, `docs/OPERATION_LOG.md`.
- Commands run:
  - `ls -lh tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0 ... && echo MODEL_ONNX_PRESENT`
  - `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug`
  - `LITS_TTS_ALLOW_DIRTY=1 bash tts/tools/android/pack_lits_tts_android_delivery.sh 0.2.5.1`
  - `shasum -a 256 delivery/lits-tts-android-sdk-v0.2.5.1-20260625.zip`
  - Python zip checks for requested license assets, old license asset, batch-test assets, and `local.properties`.
  - Python BuildConfig check for non-empty `LICENSE_PUBLIC_KEY_B64`.
  - `git status --short --ignored`
- Verification result: Gradle build succeeded. First packaging run failed because `local.properties` was staged into source snapshot; fixed dirty overlay filtering and reran successfully. Delivery script verified AAR, APK, source tree, and zip. Zip SHA256: `965394a5fd2e10443dbf05310df492603e201326d6248c9c7ba2e05961324059`. APK and source snapshot contain `amphion-license.lic` and `com.tdtech.tiassistant.lic`; they do not contain `lits-tts-license.lic`, `frontend_batch`/`frontbatch`/`batch_cases`, or `local.properties`. Release/debug BuildConfig contain non-empty license public key.
- Notes: Final tree `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1`; final zip `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1-20260625.zip`; AAR `/Users/amphion/Documents/delivery/lits-tts-android-sdk-v0.2.5.1/aar/lits-tts-sdk-0.2.5.1.aar`.

## 2026-06-25 13:04

- Goal: Sync salted SN license authentication from remote `main` into the current TTS Android SDK and align the public license interface with `语音识别SDK接口-20260622.md`.
- Files changed: `tts/android/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechApi.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechLicense.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/DeviceLicenseFingerprint.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LicenseClaims.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LicenseVerifier.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LicenseGuard.kt`, `tts/android/sdk/build.gradle.kts`, `tts/tools/license/verify_license.py`, `tts/tools/license/issue_license.py`, `tts/android/sdk/src/test/java/com/lits/tts/sdk/internal/LicenseVerifierTest.kt`, `docs/OPERATION_LOG.md`.
- Commands run: read the ASR SDK interface document; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest`; verified `/Users/amphion/Documents/AmphionRuntime/amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic` with `--device-id 4EE9K25419002062`; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:assembleRelease`.
- Verification result: TTS now supports salted SN device binding via `SHA-256(normalizedSn + deviceIdSaltId)`, while preserving legacy `deviceSha256` verification. Public license interface now includes `TextToSpeechSdk.setLicense(licensePath, callback)`, `TextToSpeechSdk.getLicenseInfo()`, `LicenseInfo`, and `LicenseActivationResult`, matching the ASR document shape. Unit tests and release AAR build passed. The v0.2.7 Dingqiao license passed offline verification for `com.tdtech.tiassistant`, certificate `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, SDK major `1`, release date `2026-06-23`, and required feature `TTS`.
- Notes: Removed the conflicting old two-string `deviceLicenseFingerprint(applicationId, deviceCode)` public overload because it had the same JVM/Kotlin signature as the new `deviceLicenseFingerprint(deviceSerial, deviceIdSaltId)` interface. The `deviceLicenseFingerprint(context)` legacy Android-ID helper remains available.

## 2026-06-25 13:12

- Goal: Align TTS public functional structure with `语音合成SDK接口.md`.
- Files changed: `tts/android/sdk/src/main/java/com/lits/tts/sdk/TextToSpeechApi.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/PcmSynthesizer.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt`, `tts/android/sdk/src/test/java/com/lits/tts/sdk/TextToSpeechSdkTest.kt`, `docs/OPERATION_LOG.md`.
- Commands run: read `语音合成SDK接口.md`; inspected TTS API/runtime implementation; searched sample-rate and callback response usage; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest`; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:assembleRelease`.
- Verification result: The TTS interface already exposes the documented objects and methods (`TextToSpeechSdk.createEngine`, `listVoices`, `setWorkPath`; `TextToSpeechEngine.setListener`, `speak`, `stop`, `isBusy`, `shutdown`) and documented request/response structures. Updated default/fallback PCM output sample rate from 16000 to 24000 to match the document's PCM 24000 Hz constraint. Unit tests and release AAR build passed.
- Notes: Kept existing optional streaming/profiling fields in response data classes because they are additive and support frontend/streaming diagnostics required by the current APK work.

## 2026-06-25 13:17

- Goal: Test whether the current AAR license authentication can succeed.
- Files changed: `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`, `docs/OPERATION_LOG.md`.
- Commands run: verified both current sample asset licenses with `verify_license.py` using `com.tdtech.tiassistant`, Dingqiao release certificate `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, SDK major `1`, release date `2026-06-23`, and required feature `TTS`; verified `/Users/amphion/Documents/AmphionRuntime/amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic` with the same inputs; ran `./tts/android/gradlew -p tts/android --no-daemon :sample:assembleDebug`; extracted sample debug APK signing cert with `apksigner`; read release `BuildConfig.java` to confirm non-empty `LICENSE_PUBLIC_KEY_B64`.
- Verification result: The AAR is armed (`LICENSE_PUBLIC_KEY_B64` non-empty, `SDK_MAJOR=1`, `SDK_RELEASE_DATE=2026-06-23`). Current sample assets `amphion-license.lic` and `com.tdtech.tiassistant.lic` fail TTS verification because their `features` only include `ASR`. The v0.2.7 Dingqiao license passes TTS verification under Dingqiao official app conditions. The local sample debug APK is signed with certificate `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`, so any license bound to Dingqiao certificate `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8` fails on this debug APK with `LICENSE_CERT_MISMATCH`.
- Notes: Conclusion: AAR authentication logic can succeed with the v0.2.7 TTS-enabled Dingqiao license in the official Dingqiao-signed host app. The currently packaged sample asset licenses cannot pass TTS auth, and the local debug APK cannot prove success because its signing cert is not Dingqiao's release cert.

## 2026-06-25 13:24

- Goal: Rework demo APK auth to use local demo signing certificate with expiry-only license restriction and no SN binding.
- Files changed: `tts/android/sample/src/main/assets/amphion-license.lic`, removed `tts/android/sample/src/main/assets/com.tdtech.tiassistant.lic`, `tts/android/docs/LICENSE.md`, `tts/android/sample/build/outputs/apk/debug/sample-debug.apk`, `docs/OPERATION_LOG.md`.
- Commands run: extracted current demo APK signing cert with `apksigner`; issued a new TTS demo license using `tts/tools/license/issue_license.py` and `amphion-license-private.pem`; verified the new license with `verify_license.py` without any `--device-id`; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug`; inspected the APK zip license assets; verified the embedded APK license by extracting it from the APK and running `verify_license.py`.
- Verification result: New active license is bound to `com.tdtech.tiassistant` and demo APK signing certificate `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`, expires on `2026-08-25`, has `features=["TTS"]`, and has `authorizedDeviceHashes=[]` (no SN/device restriction). The rebuilt demo APK contains only `assets/amphion-license.lic`; `assets/com.tdtech.tiassistant.lic` is no longer packaged. Unit tests, release AAR build, sample APK build, and embedded license verification passed.
- Notes: This demo APK can be installed on other devices as the same APK/signature; auth is limited by expiry and APK signing certificate, not by device SN.

## 2026-06-25 13:36

- Goal: Build a new old-email-style delivery zip under `~/Documents/AmphionRuntime-Delivery` using the current demo-auth AAR/APK/license.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625/`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: inspected the prior email and prior delivery package structure; rebuilt artifacts with `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleDebug`; assembled a new delivery tree with old-email top-level layout (`aar/`, `demo/`, `license/`, `android-src/TTS/`, `docs/`, `README.txt`, `VERSION.txt`, `CHECKSUMS.txt`); generated the zip and sha256 file; verified zip structure, AAR/APK model contents, APK embedded license, license verification, source snapshot exclusions, and APK signing certificate.
- Verification result: Delivery verification passed. Zip SHA256: `3d1239cf13c43160f65ec7cc6ceb7fe29ea37ecfb4e5bce6aa2a696627d4bdd0`. AAR SHA256: `a9b9796a970739a510a95a3aef509b5371dde28c02d8c1f1d371e73a40a65ff0`. Demo APK SHA256: `ec82129905b414dec2ab1e923f79e171dcd5ecbe264291ff0b359db463fa5b4d`. License SHA256: `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`. Zip size is about 777 MB; unpacked tree is about 1.0 GB.
- Notes: The zip contains exactly one top-level directory named `lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625`. Top-level license is `license/amphion-license.lic`; old `lits-tts-license.lic` and `com.tdtech.tiassistant.lic` are not included. Source snapshot excludes private keys, `.lic`, `local.properties`, APK/AAR, and build outputs.

## 2026-06-25 13:40

- Goal: Correct the delivery package so top-level `license/` contains the AAR integration auth license, not the demo APK-only license.
- Files changed: `tts/android/docs/LICENSE.md`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625/license/amphion-license.lic`, package `README.txt`, `VERSION.txt`, `CHECKSUMS.txt`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: replaced top-level `license/amphion-license.lic` with `/Users/amphion/Documents/AmphionRuntime/amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic`; refreshed package README/VERSION/CHECKSUMS; rezipped the delivery; verified zip structure; verified top-level license with Dingqiao AAR integration inputs (`com.tdtech.tiassistant`, cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, feature `TTS`); verified the demo APK embedded license separately with demo signing cert `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`.
- Verification result: Corrected zip verification passed. New zip SHA256: `19cd99f87b0df725deb2041821254ea4c1e4de34aaf2a8829cad61c4e50fc419`. Top-level AAR integration license SHA256: `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`. Demo APK embedded license SHA256 remains `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`. Zip size remains about 777 MB.
- Notes: There are now two distinct license roles: package top-level `license/amphion-license.lic` is for AAR/customer host app integration; demo APK `assets/amphion-license.lic` is only for the packaged demo APK install test and remains no-SN-bound.

## 2026-06-25 13:46

- Goal: Draft a new delivery email based on the prior `AmphionRuntime-Delivery` email format.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625-delivery-email.md`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625-delivery-email.txt`, `docs/OPERATION_LOG.md`.
- Commands run: read the prior `lits-transsion-tts-android-sdk-vocos24k-0.2.5-auth-20260624-delivery-email.md`; read corrected package `VERSION.txt`, `README.txt`, and `.zip.sha256`; measured AAR/APK/zip sizes.
- Verification result: New Markdown and plain-text email drafts were written next to the delivery package. The draft explicitly distinguishes top-level AAR integration license `license/amphion-license.lic` from the demo APK embedded demo-only license, and includes corrected zip SHA256 `19cd99f87b0df725deb2041821254ea4c1e4de34aaf2a8829cad61c4e50fc419`.
- Notes: The email uses the same high-level structure as the 2026-06-24 delivery email: greeting, delivery artifacts, important notes, update points, package structure, integration steps, test results, acceptance suggestions, and closing.

## 2026-06-25 14:04

- Goal: Add a v2.5.1 TTS input rule that appends terminal punctuation when the input text does not end with `!`, `?`, `。`, or `.`.
- Files changed: `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/TextToSpeechEngineImpl.kt`, `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/TtsInputTextNormalizer.kt`, `tts/android/sdk/src/test/java/com/lits/tts/sdk/internal/TtsInputTextNormalizerTest.kt`, `docs/OPERATION_LOG.md`.
- Commands run: searched frontend and synthesis entry points; initially checked `LitsTtsFrontend.encode` / `splitForStreaming`, then moved the rule to the SDK `speak()` input normalization layer to avoid changing low-level `encodeNormalized` semantics; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest`; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:assembleRelease :sample:assembleDebug`.
- Verification result: Rule behavior is covered by unit tests: `zh-en` appends `。`, `en-US` appends `.`, and existing `!`, `?`, `。`, or `.` are not duplicated. SDK unit tests, release AAR build, and sample debug APK build passed.
- Notes: The rule is applied before creating the synthesis task in `TextToSpeechEngineImpl.speak`, so both buffered and streaming synthesis paths receive the normalized input text.

## 2026-06-25 14:12

- Goal: Install the latest `sample-debug.apk` onto the connected Android phone.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `adb devices -l`; `adb install -r /Users/amphion/Documents/AmphionRuntime/tts/android/sample/build/outputs/apk/debug/sample-debug.apk`; `adb -s 4EE9K25419002062 shell pm path com.tdtech.tiassistant`.
- Verification result: Device `4EE9K25419002062` was online; install succeeded; installed package path is `/data/app/~~AnkAwqduvd4qyz0U2fpzKw==/com.tdtech.tiassistant-A0JInU50LZCIQhAKbBpbaQ==/base.apk`.
- Notes: Installed APK is the current sample debug build with package `com.tdtech.tiassistant`.

## 2026-06-25 14:20

- Goal: Start rebuilding authenticated release AAR and demo-licensed release demo APK, then refresh the 0625 `AmphionRuntime-Delivery` zip.
- Files changed: `docs/OPERATION_LOG.md`, `/Users/amphion/Documents/Lits_delivery/docs/OPERATION_LOG.md`.
- Commands run: none.
- Verification result: Read the Lits delivery project skill and inspected `tts/tools/android/pack_lits_tts_android_delivery.sh`, `verify_lits_tts_android_delivery.sh`, `tts/android/build.gradle.kts`, and `tts/android/sample/build.gradle.kts`. The generic pack script still builds `:sample:assembleDebug` and old `lits-tts-android-sdk-v...` naming, while the active 0625 delivery uses the manually assembled `lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625` layout with `demo/lits-tts-release.apk`.
- Notes: Need build release AAR/APK from current source and refresh the old-email/demo-auth delivery tree and zip without leaking private key material.

## 2026-06-25 14:22

- Goal: Verify current source/license state before release rebuild.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `git status --short --ignored`; `git log -1 --oneline`; file reads for current delivery `VERSION.txt`/`CHECKSUMS.txt`, SDK/sample Gradle files, manifest, and sample embedded demo license.
- Verification result: Current source has many existing modified/untracked/ignored files; ignored local secrets include `.secure/`, `amphion-license-private.pem`, and `.lic` files. SDK release uses `AMPHION_LICENSE_PUBLIC_KEY`; sample has `src/main/assets/amphion-license.lic` demo license. Current 0625 delivery package is `lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625` with `demo/lits-tts-release.apk`.
- Notes: Proceed with current workspace state and preserve existing local changes; do not package private keys or local-only files.

## 2026-06-25 14:24

- Goal: Rebuild authenticated release AAR and release demo APK from current source.
- Files changed: `tts/android/sdk/build/`, `tts/android/sample/build/`, `docs/OPERATION_LOG.md`.
- Commands run: `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm ./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleRelease`; read `sample/build/outputs/apk/release/output-metadata.json`.
- Verification result: Gradle build succeeded. Release APK metadata output is `sample-release-unsigned.apk`, so the demo APK must be signed before packaging as `demo/lits-tts-release.apk`.
- Notes: Gradle emitted NDK strip warnings for `liblits_tn.so`, `libonnxruntime.so`, and `libonnxruntime4j_jni.so`; build still completed successfully.

## 2026-06-25 14:25

- Goal: Sign the release demo APK for installable demo delivery.
- Files changed: `tts/android/sample/build/outputs/apk/release/lits-tts-release.apk`, `docs/OPERATION_LOG.md`.
- Commands run: `apksigner sign --ks ~/.android/debug.keystore --ks-key-alias androiddebugkey --out tts/android/sample/build/outputs/apk/release/lits-tts-release.apk tts/android/sample/build/outputs/apk/release/sample-release-unsigned.apk`; `apksigner verify --print-certs .../lits-tts-release.apk`.
- Verification result: APK signature verification passed. Signing cert SHA-256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`.
- Notes: This matches the intended demo license signing certificate.

## 2026-06-25 14:26

- Goal: Clarify license roles before refreshing delivery package.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: verified the signed demo APK's embedded `assets/amphion-license.lic` with `tts/tools/license/verify_license.py`.
- Verification result: Demo APK embedded license is `applicationId=com.tdtech.tiassistant`, cert `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`, no device binding, expires `2026-08-25`, feature `TTS`.
- Notes: User clarified that the AAR integration license must remain the salted SN-bound license, and only the demo APK should use the demo license. Do not refresh/reissue the AAR integration license; preserve top-level `license/amphion-license.lic` as the salted SN-bound customer integration license.

## 2026-06-25 14:28

- Goal: Refresh `/Users/amphion/Documents/AmphionRuntime-Delivery` 0625 package with current authenticated release AAR and signed release demo APK while preserving license roles.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625/`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625.zip.sha256`, `docs/OPERATION_LOG.md`.
- Commands run: verified top-level `license/amphion-license.lic` with `verify_license.py` using Dingqiao cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8` and SN `4EE9K25419002062`; copied current `sdk-release.aar` and signed `lits-tts-release.apk`; refreshed `android-src/TTS`, `README.txt`, `VERSION.txt`, `CHECKSUMS.txt`; regenerated zip and `.zip.sha256`; ran zip CRC, required-entry, checksum, source-forbidden-file, APK signature, top-level license, and demo embedded license checks; verified AAR has no `.lic` and non-empty `BuildConfig.LICENSE_PUBLIC_KEY_B64`.
- Verification result: All checks passed. New zip SHA256: `22aa7c43b00f5a9865e036f0e23e0d7794dd9526a31bbea0ddfc28039af96cd5`. New AAR SHA256: `ddbfcdf1e19648f3602aabf1f24eb2ceefa454a45a255d6fcb41b1e6ff0d8ab3`. New demo APK SHA256: `254a910e4c499981e0dae39c11338ea0eaecb9fd5e55f515bb1439a0f033fd57`. Top-level SN-bound integration license SHA256 remains `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`; demo embedded license SHA256 remains `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`.
- Notes: An initial `javap | python` pipeline for BuildConfig verification failed due to shell heredoc piping syntax; reran with a temporary file and passed. The delivery zip keeps one top-level directory and source snapshot excludes `.lic`, `.pem`, keystore, `local.properties`, `.gradle`, and build outputs.

## 2026-06-25 14:31

- Goal: Confirm the refreshed AAR can authenticate with the top-level salted SN-bound license.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: extracted `classes.jar` from the refreshed delivery AAR; checked the AAR contains no `.lic`; used `javap` to read non-empty `BuildConfig.LICENSE_PUBLIC_KEY_B64` from the AAR; ran `adb devices`; ran `tts/tools/license/verify_license.py` using the AAR-extracted public key, top-level `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625/license/amphion-license.lic`, Dingqiao cert SHA256 `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, and device SN `4EE9K25419002062`.
- Verification result: Auth verification passed. The top-level license has non-empty `authorizedDeviceHashes`, `deviceIdSaltId=DQ-TIASSISTANT-20260623-69CD375699165832C1D2E9EA77C8BE71`, includes feature `TTS`, and is valid for `com.tdtech.tiassistant` with the Dingqiao certificate.
- Notes: This confirmation used the refreshed AAR's embedded public key and the top-level SN-bound integration license, not the demo APK license.

## 2026-06-25 14:35

- Goal: Install the refreshed release TTS demo APK onto the connected Android phone.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `adb devices`; `adb install -r /Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.1-demo-auth-20260625/demo/lits-tts-release.apk`; `adb shell pm path com.tdtech.tiassistant`.
- Verification result: Device `4EE9K25419002062` was connected; install returned `Success`; installed package path is `/data/app/~~5HUKi-t58HRz5oubDb5LFg==/com.tdtech.tiassistant-DHiXcL5LlLmpuVJj3vHGHQ==/base.apk`.
- Notes: Installed APK is the refreshed signed release demo APK from the 0625 delivery package.

## 2026-06-25 14:46

- Goal: Pull latest remote `main`, push current AmphionRuntime TTS code to the remote branch, and check whether it can merge into `main`.
- Files changed: committed TTS Android/Harmony SDK and license tooling changes in commit `b48c6e6602b7ff06b04e1ae1d48fd3953cc62138`; `docs/OPERATION_LOG.md`.
- Commands run: `git status --short --ignored`; `git diff --stat`; `git log --oneline --decorate -10`; `git fetch origin main`; compared branch against `origin/main`; checked ignored auth source status; staged safe TTS code files while excluding `.lic`, private keys, signing material, APK/AAR/zip, build outputs, and local delivery artifacts; ran `git diff --cached --check`; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleRelease`; committed `feat(tts): add authenticated v2.5 delivery updates`; pushed `tts-android-harmony-v2.4`; created a temporary worktree at `origin/main`; ran `git merge --no-commit --no-ff origin/tts-android-harmony-v2.4`; aborted and removed the temporary worktree.
- Verification result: Remote `origin/main` fetched at `68c8f5538a45caea9219a4ff37e30801886aeb7e`. Push succeeded: `fc8a243..b48c6e6  tts-android-harmony-v2.4 -> tts-android-harmony-v2.4`. Pre-push Gradle build passed. Merge check did not merge cleanly; conflict status includes TTS Android docs (`INTEGRATION.md`, `LICENSE.md`), Gradle config (`gradle.properties`, `sdk/build.gradle.kts`), SDK API/license files (`TextToSpeechApi.kt`, `TextToSpeechLicense.kt`, `DeviceLicenseFingerprint.kt`, `LicenseGuard.kt`, `LicenseVerifier.kt`, `LicenseVerifierTest.kt`), Harmony project files with add/add conflicts, and license tooling scripts.
- Notes: Current working tree still has uncommitted local files not pushed, including root `LICENSE` deletion, delivery/license artifacts, operation logs, Harmony signing/build outputs, and local Chinese docs. These were intentionally left out of the pushed commit.

## 2026-06-25 15:06

- Goal: Resolve merge conflicts with `origin/main` without changing Android TTS core synthesis behavior, and verify the result can merge into `main`.
- Files changed: created merge worktree `/Users/amphion/Documents/AmphionRuntime-merge-main`; committed merge resolution `951b656` on branch `tts-android-harmony-v2.4-merge-main`; `docs/OPERATION_LOG.md`.
- Commands run: created worktree from `origin/tts-android-harmony-v2.4`; merged `origin/main`; resolved TTS Android core conflicts mostly with the TTS branch version; took main's Harmony project skeleton/license docs/tooling where appropriate; manually merged `tts/android/gradle.properties` and `tts/android/sdk/build.gradle.kts`; added `Base64Codec.kt` and `Base64CodecTest.kt` required by retained TTS `LicenseVerifier`; synced ignored local model inputs into the merge worktree for test/build only; ran `./tts/android/gradlew -p tts/android --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleRelease`; cleaned accidental `tts/tools/trial-export` working-tree changes; checked no staged `.lic`, private key, signing material, APK/AAR/zip, build output, root `tools/trial-export`, or generated Android assets; fixed whitespace in `third_party/patches/sherpa-amphion/0004-build-harmony-har-arm64-only.patch`; pushed `origin/tts-android-harmony-v2.4-merge-main`; ran `git merge-tree --write-tree origin/main origin/tts-android-harmony-v2.4-merge-main`.
- Verification result: Android TTS unit tests and release AAR/APK build passed after supplying ignored local model inputs. Final mergeability check passed with `merge_tree_exit=0`, tree `51fa037a557c87d5d57b19e1e3616f369e6b9f30`; the pushed branch can merge into `origin/main` without conflicts.
- Notes: Ignored model inputs under `tools/trial-export/` and generated assets were used only to run tests/build and were not committed. Android TTS core synthesis files were preserved from the TTS branch except for minimal config/doc compatibility merges.

## 2026-06-25 15:19

- Goal: Build a new signed release TTS demo APK from the resolved `tts-android-harmony-v2.4-merge-main` branch.
- Files changed: `/Users/amphion/Documents/AmphionRuntime-merge-main/tts/android/sample/build/outputs/apk/release/lits-tts-release-merge-main.apk`, `docs/OPERATION_LOG.md`.
- Commands run: `./tts/android/gradlew -p tts/android --no-daemon :sample:assembleRelease`; copied local ignored demo license from the original worktree into merge worktree `sample/src/main/assets/amphion-license.lic`; signed `sample-release-unsigned.apk` with `~/.android/debug.keystore`; verified APK signature with `apksigner`; checked APK required entries and verified embedded demo license with `tts/tools/license/verify_license.py`.
- Verification result: Build and signing passed. APK SHA256: `771f9ace60a8742c3a1181b4b2893fda143a52c35eeb4ff5755652bdd052c917`. Signing cert SHA256: `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. APK contains `assets/amphion-license.lic`, TTS model resources, and arm64 ONNX Runtime libs. Embedded demo license SHA256 is `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3` and verifies for `com.tdtech.tiassistant`.
- APK path/version: `/Users/amphion/Documents/AmphionRuntime-merge-main/tts/android/sample/build/outputs/apk/release/lits-tts-release-merge-main.apk`, branch `tts-android-harmony-v2.4-merge-main`.
- Notes: The first signed APK build lacked the ignored demo license asset in the isolated worktree; rebuilt after copying the local demo license asset. The license copy is local/ignored and was not committed.

## 2026-06-25 18:36

- Goal: Check whether current AmphionRuntime Android v2.5.1 still has the stale `pinyin_fallback.json` preload failure risk.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: searched `tts/android` for `pinyin_fallback`, `PINYIN_FALLBACK`, and fallback references; inspected `tts/android/sdk/src/main/java/com/lits/tts/sdk/internal/LitsTtsAssetRegistry.kt`; inspected `tts/android/sample/build.gradle.kts` and root `tts/android/build.gradle.kts`; checked `tts/android/sample/build/outputs/apk/debug/sample-debug.apk` contents for `pinyin_fallback.json`; dumped APK package metadata with `aapt`.
- Verification result: Current AmphionRuntime Android source has no `PINYIN_FALLBACK`/`pinyin_fallback` declaration or code reference. The debug APK also contains no `pinyin_fallback.json`. APK metadata is package `com.tdtech.tiassistant`, versionName `0.2.5.1`. Current asset registry includes `ASSET_SIGNATURE_VERSION=20260624-frontend-v2.6` and `FRONTEND_RULES=frontend_rules.json`.
- Notes: The stale `pinyin_fallback.json` issue existed in the older isolated `fc8a243` baseline used for comparison, not in the current AmphionRuntime v2.5.1 branch state.

## 2026-06-25 23:14

- Goal: Build Android TTS v0.2.5.2 release AAR/APK with latest Kotlin code and re-exported ONNX model package, then produce a demo-auth delivery zip.
- Files changed: synced latest Android TTS source/model inputs into `tts/android` and `tts/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0`; updated `tts/android/build.gradle.kts` and `tts/android/sample/build.gradle.kts` to `0.2.5.2`; generated `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.2-demo-auth-20260625/` and `.zip`.
- Commands run: rsynced source/model from `/Users/amphion/Documents/Lits_delivery/lits_transsion_sdk_vocos24k_v2_5`; ran `./gradlew --no-daemon :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleRelease`; signed `sample-release-unsigned.apk` with the Android debug keystore as `lits-tts-release-v2.5.2.apk`; staged AAR/APK/docs/source/model/license; generated `CHECKSUMS.txt`; created and CRC-tested the zip.
- Verification result: Gradle build passed. APK metadata is `com.tdtech.tiassistant` / `0.2.5.2`; signed APK cert SHA-256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. AAR and APK both contain the required ONNX assets and AAR contains no `.lic`. Top-level AAR integration license was taken from `amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic` and verified for TTS with Dingqiao cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, `sdkMajor=1`, and 16 salted device hashes. Demo APK embedded license verified with demo cert `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`.
- APK path/version: `/Users/amphion/Documents/AmphionRuntime/tts/android/sample/build/outputs/apk/release/lits-tts-release-v2.5.2.apk`, versionName `0.2.5.2`.
- Delivery zip: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.2-demo-auth-20260625.zip`, size `770M`, SHA256 `2243ae96a097652e33dea01af8a3bbbda2e2dead58ce15589accef698bb5659d`.
- Notes: ONNX hashes recorded in `VERSION.txt`: hidden encoder `2979c4e7fd36878380bbb736501d8e8cdea6d3862d631b01df98b0e4c4b5104c`, condition chunk `8523bfd54d09d2d46e858606d9a68ac9aef3a2237f8cf243814e519ae2e08ba8`, condition final `b72657c2ce7fd54996dd60b835f3417cb4d26252ce2b181ac32b10700e3f7bb3`, decoder step `72653a3cf7ca92a7c0e1c011d313246dd5897563e0e661f29a074171cb005556`, vocoder `cb2b53683b0cd763a1377e9ba06939f3367cb4f08584d179a9bffcf43377c4b3`. No commit or push was performed.

## 2026-06-25 23:40

- Goal: Fix v0.2.5.2 delivery because `lits_hidden_encoder.onnx` was still stale in the Android assets/AAR/APK even though `tts/tools/trial-export` had the new model.
- Files changed: synchronized the new model package into the actual Gradle source path `/Users/amphion/Documents/AmphionRuntime/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0`, mirrored it under `tts/tools/trial-export`, rebuilt release AAR/APK, and regenerated `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.2-demo-auth-20260625.zip`.
- Commands run: compared hidden encoder hashes across source, root `tools/trial-export`, `tts/tools/trial-export`, Android assets, delivery source, AAR, and APK; rsynced the latest model package into both model roots; ran `./gradlew --no-daemon :sdk:assembleRelease :sample:assembleRelease`; signed the release APK; restaged and CRC-tested the delivery zip.
- Verification result: Root model source, mirrored model source, Android assets, AAR, APK, and delivery source snapshot now all contain `lits_hidden_encoder.onnx` SHA256 `2979c4e7fd36878380bbb736501d8e8cdea6d3862d631b01df98b0e4c4b5104c`. Corrected AAR SHA256 is `3de1d59a64185f0769e09b1968d88cd5bf3fe987640501623ffae5f6d54740d0`; corrected APK SHA256 is `77c47cabe00c1644045662bc733e4519a6f1d44101b1e6a1ecc0a643d75b7d67`; corrected zip SHA256 is `688fee8a58c09c01a73091e45ac26e2a26012d9b7487f52d831ef584eef5760e`.
- Notes: The previous mismatch happened because `tts/android/build.gradle.kts` resolves `litsModelDir` as `../../tools/trial-export/...` from `tts/android`, which points to repository-root `tools/trial-export`, not `tts/tools/trial-export`. A clean test build exposed four frontend lexicon assertion failures after the updated frontend resources were synced; the final rebuild used release assemble plus explicit ONNX packaging checks.

## 2026-06-25 23:41

- Goal: Install the corrected v0.2.5.2 release demo APK onto the connected Android phone.
- Files changed: `docs/OPERATION_LOG.md`.
- Commands run: `adb devices`; checked SHA256 for `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.2-demo-auth-20260625/demo/lits-tts-release.apk`; `adb -s 4EE9K25419002062 install -r .../lits-tts-release.apk`; `adb -s 4EE9K25419002062 shell pm path com.tdtech.tiassistant`.
- Verification result: Install returned `Success`. Installed package path is `/data/app/~~929js0aagUwUOP4fuuAjeg==/com.tdtech.tiassistant-5XUskABLf2O3hynOq81LAw==/base.apk`. Installed APK SHA256 source was `77c47cabe00c1644045662bc733e4519a6f1d44101b1e6a1ecc0a643d75b7d67`.
- Notes: This is the corrected release demo APK whose packaged hidden encoder hash was verified as `2979c4e7fd36878380bbb736501d8e8cdea6d3862d631b01df98b0e4c4b5104c`.


## 2026-06-28 21:43:07 Android v2.5.3 authenticated delivery rebuild start

- Goal: Sync Lits_delivery Android v2.5.3 code/resources into AmphionRuntime, build authenticated salted-SN release AAR and demo-license release demo APK, and create a new delivery zip under `~/Documents/AmphionRuntime-Delivery`.
- Files changed: pending.
- Commands run: pending.
- Verification result: pending.
- Notes: Must verify new frontend resources (`chinese_lexicon.bin`, `polyphone_context.txt`, `polyphone_phrases.txt`, `chinese_surname_lexicon.txt`) are included in AAR, demo APK, and delivery source snapshot.


## 2026-06-28 21:47:21 Android v2.5.3 authenticated delivery rebuild complete

- Goal: Sync Lits_delivery Android v2.5.3 code/resources into `~/Documents/AmphionRuntime`, build authenticated salted-SN release AAR and demo-license release demo APK, and create a new delivery zip under `~/Documents/AmphionRuntime-Delivery`.
- Files changed: `~/Documents/AmphionRuntime/tts/android/`, `~/Documents/AmphionRuntime/tools/trial-export/`, build outputs under `tts/android/sdk/build/` and `tts/android/sample/build/`, `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.3-demo-auth-20260628/`, `.zip`, `.zip.sha256`, and operation logs.
- Commands run: synced `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime` to `AmphionRuntime/tts/android`; synced `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/tools/trial-export` to `AmphionRuntime/tools/trial-export`; verified frontend resource SHA256 in root model source and Android assets; ran `./gradlew --no-daemon :sdk:assembleRelease :sample:assembleRelease`; signed `sample-release-unsigned.apk` with `~/.android/debug.keystore` as `lits-tts-release-v2.5.3.apk`; verified AAR/APK packaged frontend resource hashes; verified top-level Dingqiao SN-bound license and demo APK embedded license with `tts/tools/license/verify_license.py`; assembled old-email-style delivery tree and zip; ran zip CRC, required-entry, forbidden-entry, CHECKSUMS, resource, license, and signature verification.
- Verification result: All checks passed. Delivery zip: `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.3-demo-auth-20260628.zip`; zip SHA256 `4ccfae63b38d88b08ee2958190f7d3a45663bcd16de96a61e29ce3491c66928d`; zip size `994083192` bytes. AAR SHA256 `238c16211f7a9ab4a1db7875090f3ec77d1d0271f5d6578c9b24c8263db2cceb`; demo APK SHA256 `00a37097996254e99113a48d098ef8d27e3d92405574dd8f92c40c92c0853c7d`; top-level license SHA256 `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`.
- Frontend resource verification: `chinese_lexicon.bin` SHA256 `9209470d9b4dca3531f067b3d53a3c3999131241c7c154e30048af2ab9ab1a29`, `chinese_surname_lexicon.txt` SHA256 `49261182e094a611d96eeaf23c6fd43ba70bdd3c06e7f9da63e66683383fe191`, `polyphone_context.txt` SHA256 `d3e84dd4d0965d49121438fa0677fe231a9dba216730bd013912dad744ccf757`, and `polyphone_phrases.txt` SHA256 `c5bbb3ba4cb6e17dadde3ca68171f2165136d2ded3b77fb1bec8fa475d70eb36` were verified in all three locations: root model source, packaged AAR, packaged demo APK, and delivery source snapshot.
- Notes: AAR contains no `.lic`; demo APK contains exactly `assets/amphion-license.lic`; source snapshot excludes private keys, `.lic`, keystore, `local.properties`, `.git`, `.gradle`, `.secure`, and build outputs. Top-level integration license validates for `com.tdtech.tiassistant`, Dingqiao cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, `sdkMajor=1`, feature `TTS`. Demo APK signing cert SHA256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c` and embedded demo license validates for feature `TTS`.


## 2026-06-28 21:48:38 Android v2.5.3 AAR auth verification

- Goal: Test whether the delivered v2.5.3 AAR can pass license authentication.
- Files changed: operation logs only.
- Commands run: extracted `classes.jar` from `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.3-demo-auth-20260628/aar/lits-transsion-tts-sdk-vocos24k-0.2.5.3-demo-auth.aar`; read `com.lits.tts.sdk.BuildConfig.LICENSE_PUBLIC_KEY_B64` with `javap`; verified `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.3-demo-auth-20260628/license/amphion-license.lic` with the AAR-extracted public key, applicationId `com.tdtech.tiassistant`, Dingqiao cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, SN `4EE9K25419002062`, `sdkMajor=1`, feature `TTS`; ran `./gradlew --no-daemon :sdk:testDebugUnitTest --tests com.lits.tts.sdk.internal.LicenseVerifierTest`.
- Verification result: AAR auth passed. The AAR contains no `.lic`, has a non-empty embedded public key (`LICENSE_PUBLIC_KEY_B64`, length 124), and the top-level SN-bound license verified successfully using that AAR-extracted public key. `LicenseVerifierTest` also passed.
- Notes: This confirms the delivered AAR is armed for auth and accepts the packaged Dingqiao SN-bound integration license under the expected package/cert/SN. Runtime integration still requires the host app to provide `license/amphion-license.lic` through the documented SDK license loading path.

## 2026-06-30 21:27 Android v0.2.5.2 demo-auth rebuild support

- Goal: Support rebuilding the Android v0.2.5.2 TTS authenticated AAR/demo-license APK from `Lits_delivery` using the current Dingqiao formal license.
- Files changed: `docs/OPERATION_LOG.md` only.
- Commands run: decoded and verified `/Users/amphion/Documents/AmphionRuntime/amphion-dingqiao-license-v0.2.7-20260625/amphion-license.lic`; compared it with prior v0.2.5.2/v0.2.5.3 delivery licenses; used its public key relationship to verify the rebuilt AAR `BuildConfig.LICENSE_PUBLIC_KEY_B64`.
- Verification result: Formal license SHA256 is `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`, matching the prior delivery license; it verifies for `com.tdtech.tiassistant`, Dingqiao cert `6e9b5aaeef2797755cd3405952d9693e8db173c0a1733e38bf5bd16f9a6022e8`, `sdkMajor=1`, and feature `TTS` with SN check skipped because no device SN was supplied.
- Notes: Build outputs were generated in `Lits_delivery/lits_transsion_sdk_vocos24k_v2_5/android/AmphionRuntime`, not in this repository.

## 2026-06-30 22:15 Android v0.2.5.4 authenticated delivery build start

- Goal: Build the latest Android v0.2.5.4 TTS authenticated AAR and demo-license release APK, then prepare a delivery zip.
- Files changed: `docs/OPERATION_LOG.md`; build outputs under `tts/android/sdk/build/` and `tts/android/sample/build/`; delivery package under `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630/`; temporarily copied and then removed `tts/android/sample/src/main/assets/amphion-license.lic` for demo APK packaging.
- Commands run: copied local demo license asset; first ran `clean :sdk:testDebugUnitTest :sdk:assembleRelease :sample:assembleRelease`, which failed in 6 lifecycle/cancellation unit tests; reran release assembly only; signed release APK with `~/.android/debug.keystore`; staged AAR/APK/license/docs/source snapshot; generated `VERSION.txt`, `README.txt`, `CHECKSUMS.txt`, zip, and `.zip.sha256`; verified zip CRC, CHECKSUMS, forbidden files, AAR public key/no-license, APK metadata/signature/license, formal license, and source/AAR/APK model/frontend resource hashes.
- Verification result: Release build/package verification passed. Zip `/Users/amphion/Documents/AmphionRuntime-Delivery/lits-transsion-tts-android-sdk-vocos24k-0.2.5.4-demo-auth-20260630.zip` SHA256 `1c9500aa1f060992d7a7c835d6e50301380719bbeb6d6e8fcd948b8ed241e824`, size `994194792` bytes. AAR SHA256 `da3f73b715f516235ce1f7a335013448140f2740736db2433d34fd97f6f91d0f`; demo APK SHA256 `1de70f284379f601e56abaa21fbe1ca324996855d5735833c9c3f19161f51e14`; formal license SHA256 `bda872951b762023f0be811b79781da252c1042078818522570a9e49a33cb503`; embedded demo license SHA256 `d84169281cea4b2bfdb824087a4234dd6594ad6f3ab1c9ff9f82f71f8c89d5a3`.
- Notes: APK metadata is `com.tdtech.tiassistant` / `versionName=0.2.5.4`; APK signing cert SHA256 is `954fd136a60416acbd8cddd4c436bec496f4e707f62680bb68a97b56c2d0755c`. Current full unit suite is not green due 6 lifecycle/cancellation failures; release assemble and package verification passed. Delivery source snapshot excludes private keys, keystores, `.secure`, build outputs, and source-tree `.lic` files.

## 2026-07-13 Dingqiao vocos24k v3 Android source sync

- Goal: Create branch `lits_dingqiao_sdk_vocos24k_v3`, compare/sync the Dingqiao vocos24k v3 Android SDK source from local delivery inputs, vendor the Android build dependencies into AmphionRuntime so the SDK compiles without external source paths, include ONNX export Python tooling, and remove legacy vendor-word/path residues from the synced scope.
- Files changed or artifacts created: synced Dingqiao Android SDK source into `tts/android`; replaced root and `tts/tools` trial-export inputs with `dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0`; added repo-local `dingqiao_lits/` with TN source, Android TN binaries, Android ICU headers/static libraries, and Python model/frontend/vocoder source excluding checkpoints and caches; added `tools/dingqiao-android/` parity tools and `tools/dingqiao-onnx-export/` ONNX export tools; generated `tts/android/sdk/build/outputs/aar/sdk-release.aar`.
- Commands run: created branch `lits_dingqiao_sdk_vocos24k_v3`; used `rsync` to sync Android source, trial-export resources, TN source/binaries, ICU dependencies, Dingqiao model/frontend Python source, and ONNX export scripts; sanitized synced text for legacy vendor wording and local absolute paths; updated `tts/android/build.gradle.kts`, `tts/android/sdk/src/main/cpp/CMakeLists.txt`, and `tts/android/sdk/src/main/jni/Android.mk` so the workspace root resolves to the AmphionRuntime checkout; ran `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm ANDROID_HOME=/Users/amphion/Library/Android/sdk ANDROID_SDK_ROOT=/Users/amphion/Library/Android/sdk ./gradlew --no-daemon :sdk:assembleRelease`.
- Verification result: first Gradle run without `ANDROID_HOME` failed as expected due to missing Android SDK location; second run with the local Android SDK surfaced the old source layout path issue; after path fixes, `:sdk:assembleRelease` passed. Generated AAR `tts/android/sdk/build/outputs/aar/sdk-release.aar` is 202M with SHA-256 `5602a49fc367127f8218cbc2a80943c4e259bf5ef4c0794394e06fbc636fe5f2`. Source-scope checks over `tts/android`, `tools/trial-export`, `tts/tools/trial-export`, `tools/dingqiao-android`, `tools/dingqiao-onnx-export`, and `dingqiao_lits` found no legacy vendor-word occurrences and no local absolute path references after excluding generated build outputs and binary model/static-library files.
- Notes/next action: Large training checkpoints were intentionally not vendored; Android compilation uses exported ONNX assets and repo-local TN/ICU inputs only. Existing unrelated untracked Harmony/signing/license files were left untouched.

## 2026-07-13 TN source moved to independent submodule

- Goal: Keep the TN implementation in its independent GitHub repository and prevent its source files from being committed to the AmphionRuntime parent repository.
- Files changed or artifacts created: added `.gitmodules` entry for `dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS`; parent repository now records only submodule commit `9cf6411c919c203351724a05fbdcc5ace5346242`; updated `tts/android/build.gradle.kts` to sync `rules_v2` and the pinyin map from the submodule layout; generated `tts/android/sdk/build/outputs/aar/sdk-release.aar`.
- Commands run: verified the independent repository with the local SSH key using `git ls-remote` and `git fetch`; replaced the copied TN directory with `git submodule add -b main git@github.com:hhk1994/Transsion_Multilingual_Text_Normalization_for_TTS.git dingqiao_lits/Dingqiao_Multilingual_Text_Normalization_for_TTS`; ran `JAVA_HOME=/Users/amphion/Documents/Lits_delivery/.venv/lib/jvm ANDROID_HOME=/Users/amphion/Library/Android/sdk ANDROID_SDK_ROOT=/Users/amphion/Library/Android/sdk ./gradlew --no-daemon :sdk:assembleRelease`.
- Verification result: `:sdk:assembleRelease` passed in 22 seconds; `git diff --cached` shows only `.gitmodules` and one mode-160000 submodule entry for the TN path, with no TN source files staged in the parent repository; submodule status is `9cf6411`.
- Notes/next action: The copied pre-submodule directory was preserved at `/tmp/amphion-tn-source-before-submodule-20260713104527`; clone consumers should initialize submodules before building, for example with `git clone --recurse-submodules`.

## 2026-07-13 Portable Android ICU/TN build handoff

- Goal: remove build dependence on the current machine's absolute paths and provide a reproducible Android ICU/TN build entry point while keeping ONNX and TN binaries outside the parent repository.
- Files changed: `scripts/build_dingqiao_android_native.sh`, `scripts/build_dingqiao_harmony_tn.sh`, `docs/DINGQIAO_V3_BUILD.md`, `tts/harmony/hvigorfile.ts`, `tts/harmony/sdk/src/main/ets/TextToSpeechApi.ets`.
- Commands run: `bash -n scripts/build_dingqiao_android_native.sh`; ran the new script with an external ICU 78.1 source archive, Android NDK, and temporary `/tmp` output directories; inspected generated ELF and ICU static library outputs.
- Verification result: ICU host tools and Android arm64 static libraries built successfully; `zh_tts` and `en_tts` built as Android arm64 ELF executables. The first run exposed and fixed ICU archive-root handling and macOS NDK host-tag detection.
- Notes: ONNX export remains outside the colleague workflow; the pre-exported ONNX/model package is delivered separately. Temporary build outputs were not added to the parent repository.

## 2026-07-13 Exclude local training and runtime data from parent push

- Goal: Keep training filelists, test data, ONNX models, and TN binaries local-only; do not commit or push them from AmphionRuntime.
- Files changed or artifacts created: updated `.gitignore`; removed the listed data and binary files from the parent repository index while preserving them in the working tree; retained pure preprocessing scripts, model rules, and the TN submodule gitlink.
- Commands run: inspected staged paths and sizes; used `git restore --staged` for training filelists, Android test assets, frontend case data, TN binaries, and the old TN-binary deletion paths; re-added only filelist processing scripts; added local-only ignore rules.
- Verification result: staged-path scan found no training filelist data, test asset data, ONNX files, TN binaries, or TN-binary deletion paths; no commit or push was performed.
- Notes/next action: Local build inputs remain available in the working tree. Any later commit should preserve these exclusions.

## 2026-07-03 15:10 Harmony v3.0 API 12 GitHub push

- Goal: Pull remote `origin/tts-android-harmony-v3.0`, merge local Harmony v3.0 API 12 changes with the remote license-auth update, verify the build, and push back to GitHub branch `tts-android-harmony-v3.0`.
- Files changed: `tts/harmony/build-profile.json5`, `tts/harmony/sdk/src/main/ets/TextToSpeechApi.ets`, `tts/harmony/sample/src/main/ets/pages/Index.ets`, and `docs/OPERATION_LOG.md`.
- Commands run: `git fetch origin tts-android-harmony-v3.0`; `git pull --rebase --autostash origin tts-android-harmony-v3.0`; resolved `TextToSpeechApi.ets` autostash conflict; checked for conflict markers and API14 `application.getApplicationContext`; ran `hvigorw --mode module -p product=default -p module=sdk@default assembleHar --no-daemon`; ran `hvigorw --mode module -p product=default -p module=sample@default assembleHap --no-daemon`; unpacked `sample-default-unsigned.hap` to inspect SDK metadata and native libraries.
- Verification result: Remote was fast-forwarded to `499da36` before local changes were applied. HAR and HAP builds passed. HAP `pack.info` reports `compatible=12` and `target=12`; `module.json` app metadata reports `minAPIVersion=50000012` and `targetAPIVersion=50000012`. Packaged native libraries include `libs/arm64-v8a/liblitsttsnative.so`, `libonnxruntime.so`, and `libc++_shared.so`.
- Notes: Kept the remote Harmony license gate and added API12-compatible context injection via `TextToSpeechSdk.setContext(common.Context)` for bundled model extraction. The sample now passes `getContext(this) as common.Context` before engine creation and no longer imports `@ohos.app.ability.application`.

## 2026-07-13 15:19 Dingqiao v3 delivery parity audit

- Goal: Recompare the integrated Android and HarmonyOS projects with `Lits_delivery/lits_dingqiao_sdk_vocos24k_v3_0`, find omissions or regressions, and verify that the colleague build remains independent of this machine's paths.
- Files changed: `tts/harmony/sdk/src/main/ets/TextToSpeechApi.ets`, `tts/harmony/sdk/src/main/cpp/lits_tts_native.cpp`, `tts/harmony/sdk/src/main/cpp/CMakeLists.txt`, `tts/harmony/sdk/src/main/cpp/types/liblitsttsnative/Index.d.ts`, Harmony vendored TN source directory renamed to `tts/harmony/sdk/src/main/cpp/third_party/dingqiao_tn`, `scripts/build_dingqiao_android_native.sh`, `scripts/build_dingqiao_harmony_tn.sh`, and this log.
- Commands run: `bash -n scripts/build_dingqiao_android_native.sh scripts/build_dingqiao_harmony_tn.sh`; `python3 -m py_compile tools/dingqiao-android/build_frontend_binary_assets.py`; rebuilt Android ICU/TN with the local Android NDK into `/tmp/dingqiao-native-tn-test2`; rebuilt Harmony arm64 TN with the local DevEco native SDK into `/tmp/dingqiao-harmony-tn-test2`; ran Harmony `ohpm install --all` and `hvigorw ... assembleHar --no-daemon`; ran Android `./gradlew --no-daemon :sdk:assembleRelease` with the local JDK17 and Android SDK; compared Android/Harmony source file lists and model package file lists against `Lits_delivery`.
- Verification result: Android and Harmony builds passed. Newly generated TN binaries are arm64 ELF, contain no `/Users`, `Lits_delivery`, `AmphionRuntime`, or source checkout path strings, and resolve their `rules_v2` files relative to the model package working directory. Restored bounded TN process shutdown, runtime active-call protection, TN cache release, long-text TN segmentation, fullwidth digit/Latin normalization, and streaming chunk bounds.
- Notes: Delivery-only Harmony stability/evaluation runners are not required for SDK/HAR compilation. `rules_v2` differs from the older delivery mirror because the integrated model package carries the newer hand-authored rule source; both Android and Harmony builds package the same current model directory. License/signing warnings remain intentionally out of scope. No commit or push was performed.

## 2026-07-13 16:18 Dingqiao v3 rules_v2-only resource migration

- Goal: Make the intentional `rules_v2` upgrade authoritative and remove legacy v1 TN rule assets from the SDK workflow.
- Files changed: moved `rules/zh_pinyin.json` to `rules_v2/zh_pinyin.json`; removed `rules/zh.json` and `rules/en.json` from the model source; updated Android/Harmony resource lists, native pinyin-map loading paths, packaging tasks, tests, and build documentation; removed stale generated v1 assets from Android and Harmony package inputs.
- Commands run: ran Android `./gradlew --no-daemon :sdk:assembleRelease` with local JDK17/Android SDK; ran Harmony `ohpm install --all` and `hvigorw --mode module -p product=default -p module=sdk@default assembleHar --no-daemon`; inspected source, Android assets/AAR, and gzip-tar HAR contents; ran `git diff --check`.
- Verification result: Android and Harmony builds passed. Source, Android assets/AAR, and Harmony rawfile/HAR contain only `rules_v2/en.full.json`, `rules_v2/zh.full.json`, and `rules_v2/zh_pinyin.json`; no v1 rule paths remain in the Android/Harmony code or docs.
- Notes: The pinyin map remains because the v2 native pipeline needs it, but it is now packaged under `rules_v2`. No commit or push was performed.

## 2026-07-13 17:53 Android AAR v2 stability 100-case device test

- Goal: Run `test/dingqiao_test_cases/android_v3_sdk_stability_100_cases_improved_v2.jsonl` against the locally built Android AAR on device `4EE9K25419002062`.
- Commands run: built `:aarHost:connectedDebugAndroidTest` with the local JDK17/Android SDK; installed the AAR host and test APK; ran only `AarStability1000DeviceTest#runAndroidV3SdkStability1000CasesThroughAar` with `caseStart=0` and `caseLimit=100`; pulled the device results and summary.
- Verification result: all 100 cases executed. Summary: 85 PASS, 9 EXPECTED_ERROR, 6 FAIL. Failures: four native-heap-delta checks in memory-leak-soak cases, one longtext TN case with a 522000 ms terminal-callback timeout, and one stress-recovery case with a native-heap-delta check.
- Notes: The test asset was temporarily replaced in the built AAR host APK with the requested v2 100-line JSONL and the source asset was restored after the run. The runner's native heap check compares immediate `Debug.getNativeHeapAllocatedSize()` before/after without post-loop GC or settling; these four native-heap failures are therefore warnings requiring a better leak-validation rerun, not proof of a native leak. No commit or push was performed.

## 2026-07-13 18:09 Android AAR index 90 focused rerun

- Goal: Re-run only `android-v3-sdk-stability-longtext-tn-stability-005` and collect first-packet, RTF, memory, and temperature indicators.
- Commands run: cleared `com.lits.tts.aarhost` data; ran `AarStability1000DeviceTest#runAndroidV3SdkStability1000CasesThroughAar` with `caseStart=90` and `caseLimit=1`; collected the device JSONL result and logcat frontend progress.
- Verification result: the failure reproduced after 532185 ms. The case produced `startCallbacks=1`, `dataCallbacks=0`, `completeCallbacks=0`, `firstPacketMs=-1`, and `rtf=-1`; it timed out before the first PCM callback. Resource samples reported Java heap average/peak 128.5/167.5 MB, native heap average/peak 297.6/317.2 MB, PSS average/peak 417.9/507.3 MB, RSS average/peak 511.6/608.4 MB, and temperature average/peak 36.3/38.0 C.
- Notes: Logcat showed frontend/TN segment processing continuing through the long request, so this is a reproducible pre-first-packet latency/throughput problem for the 3600-character, three-repeat `SYNTHESIZE_AND_PLAY` case, not an OOM or device thermal failure. The current runner still cannot calculate first-packet or RTF when no PCM callback is emitted. No commit or push was performed.

## 2026-07-13 19:04 Android AAR playback-aware index 90 rerun

- Goal: Correct the playback-mode measurement path and re-run index 90 with an explicit playback-start metric.
- Files changed: `tts/android/aarHost/src/androidTest/java/com/lits/tts/aarhost/AarStability1000DeviceTest.kt`.
- Changes: used the existing optional `SpeakListener.onPlaybackStart` and existing `firstAudioMs`/`playbackStartMs` result fields; added a `preserveWorkPath` test argument so externally staged model resources are not deleted during the test.
- Verification result: Android AAR Host test APK compiled successfully. With the requested v2 asset and external model resources staged on device, index 90 reproduced after 530730 ms with `firstPacketMs=-1`, `firstAudioMs=-1`, `playbackStartMs=-1`, `dataCallbacks=0`, and `completeCallbacks=0`. This confirms no PCM reached the internal AudioTrack within the timeout, rather than merely being hidden from the listener callback.
- Resource result: Java heap average/peak 129.0/235.4 MB, native heap average/peak 298.3/311.4 MB, PSS average/peak 419.9/448.1 MB, RSS average/peak 513.8/542.3 MB, temperature average/peak 31.6/33.0 C. No OOM or thermal trigger was observed.
- Notes: The per-segment frontend encode timings remained tens to hundreds of milliseconds; the long wall-clock gaps occur after segment submission in the streaming inference/playback pipeline. No commit or push was performed.

## 2026-07-13 Dingqiao v3 Android/Harmony source build docs

- Goal: Add clear SDK build documentation for compiling the Dingqiao v3 TTS Android and HarmonyOS SDKs from the current AmphionRuntime source plus initialized submodules.
- Files changed or artifacts created: added `tts/android/docs/BUILD_FROM_SOURCE.md`; added `tts/harmony/docs/BUILD_FROM_SOURCE.md`; linked the new docs from `tts/android/README.md`, `tts/harmony/README.md`, and `tts/harmony/docs/BUILD.md`; updated this operation log.
- Commands run: inspected recent operation history and existing Android/Harmony build docs; inspected `.gitmodules`, `scripts/build_dingqiao_android_native.sh`, `scripts/build_dingqiao_harmony_tn.sh`, `tts/android/build.gradle.kts`, `tts/harmony/hvigorfile.ts`, and native CMake inputs; ran `git diff --check` on the new and linked documentation files.
- Verification result: `git diff --check` passed for the documentation changes. No Android or HarmonyOS SDK build was run because this task only added build instructions.
- Notes/next action: The docs describe `git submodule update --init --recursive`, the expected model package path under `tts/tools/trial-export/...`, optional Android/Harmony TN native rebuild scripts, AAR/HAR output paths, and local-only files that must not be committed.

## 2026-07-13 Dingqiao v3 Android batch-test cases and docs

- Goal: Bring local Dingqiao v3 TTS Android batch-test cases and batch-test code into the repository, and document how to run stability and pronunciation batch tests.
- Files changed or artifacts created: added `tts/android/testdata/dingqiao_batch_cases/` with the requested 100-case stability corpus, 1000-case stability corpus, pronunciation correctness corpus, and the locally available 424-case middle corpus plus summaries/design notes; added stability assets under `tts/android/aarHost/src/androidTest/assets/`; added the pronunciation asset under `tts/android/sdk/src/androidTest/assets/`; added batch generation scripts under `tools/dingqiao-android/`; updated `AarStability1000DeviceTest` to accept 100/424/1000-case assets via `inputAsset`; added `tts/android/docs/BATCH_TESTING.md`; updated `tts/android/README.md` and `.gitignore`; updated this operation log.
- Commands run: inspected local `test /dingqiao_test_cases/` and `Lits_delivery/dingqiao_test_cases/`; copied the selected JSONL/summary/script files into repository-scoped paths; ran `python3 -m py_compile` on Dingqiao Android helper scripts; ran `git diff --check`; checked line counts for the copied corpora.
- Verification result: script syntax checks passed; `git diff --check` passed; copied corpus counts are 100 for `android_v3_sdk_stability_100_cases_improved_v2.jsonl`, 424 for `android_v3_sdk_stability_424_cases_improved_v3.jsonl`, 1000 for `android_v3_sdk_stability_1000_cases_improved.jsonl`, and 675 for `pronunciation-golden-round3-results-with-pinyin-fixed-round15.jsonl`. No Android device batch test was run in this documentation/data import step.
- Notes/next action: No 432-case corpus was found in the workspace or `Lits_delivery`; the available middle corpus is 424 cases and is documented as such. Build outputs, pulled device reports, model binaries, license files, and signing materials remain local-only.
