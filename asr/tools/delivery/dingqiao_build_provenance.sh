#!/usr/bin/env bash
# 鼎桥交付包 / fat AAR 构建溯源（所有 pack_*.sh 与 merge_dingqiao_fat_aar.sh 共用）。
#
# 目标：VERSION.txt、AAR 内 META-INF、BuildConfig.SDK_VERSION 与当前 git 工作区一致，
# 避免「在另一台机器/未推送分支上打包」导致同事无法复现。
#
# 环境变量：
#   DINGQIAO_ALLOW_DIRTY=1  允许脏工作区打包（仅本地预览，VERSION.txt 会标注 git_dirty=true）

_dingqiao_delivery_common="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd
)/tools/delivery/delivery_common.sh"
if [[ -f "$_dingqiao_delivery_common" ]]; then
  # shellcheck source=../../../tools/delivery/delivery_common.sh
  source "$_dingqiao_delivery_common"
fi

dingqiao_repo_root_from_script() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
  local repo_root
  repo_root="$(cd "$script_dir/../../.." && pwd)"
  if ! git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "[ERROR] AmphionRuntime git root not found (expected .git at $repo_root)" >&2
    exit 1
  fi
  printf '%s\n' "$repo_root"
}

dingqiao_ar_root_from_repo() {
  local repo_root="$1"
  printf '%s/asr/android\n' "$repo_root"
}

dingqiao_read_sdk_version() {
  local ar_root="$1"
  local v
  v="$(grep '^AMPHION_RUNTIME_VERSION=' "$ar_root/gradle.properties" | cut -d= -f2- | tr -d '[:space:]')"
  if [[ -z "$v" ]]; then
    echo "[ERROR] AMPHION_RUNTIME_VERSION missing in $ar_root/gradle.properties" >&2
    exit 1
  fi
  printf '%s\n' "$v"
}

dingqiao_resolve_delivery_version() {
  local ar_root="$1"
  local arg_version="${2:-}"
  local sdk_ver
  sdk_ver="$(dingqiao_read_sdk_version "$ar_root")"
  if [[ -z "$arg_version" ]]; then
    printf '%s\n' "$sdk_ver"
    return 0
  fi
  if [[ "$arg_version" != "$sdk_ver" ]]; then
    echo "[WARN] delivery version arg ($arg_version) != AMPHION_RUNTIME_VERSION ($sdk_ver); using arg for package name, sdk_version stays $sdk_ver" >&2
  fi
  printf '%s\n' "$arg_version"
}

dingqiao_collect_git_provenance() {
  local repo_root="$1"
  (
    cd "$repo_root" || exit 1
    GIT_COMMIT_FULL="$(git rev-parse HEAD)"
    GIT_COMMIT_SHORT="$(git rev-parse --short=12 HEAD)"
    git cat-file -e "$GIT_COMMIT_FULL" 2>/dev/null || {
      echo "[ERROR] git commit not resolvable: $GIT_COMMIT_FULL" >&2
      exit 1
    }
    GIT_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    GIT_REMOTE="$(git remote get-url origin 2>/dev/null || echo unknown)"
    if [[ -n "$(git status --porcelain)" ]]; then
      GIT_DIRTY=true
    else
      GIT_DIRTY=false
    fi
    export GIT_COMMIT_FULL GIT_COMMIT_SHORT GIT_BRANCH GIT_REMOTE GIT_DIRTY
    printf 'GIT_COMMIT_FULL=%q\n' "$GIT_COMMIT_FULL"
    printf 'GIT_COMMIT_SHORT=%q\n' "$GIT_COMMIT_SHORT"
    printf 'GIT_BRANCH=%q\n' "$GIT_BRANCH"
    printf 'GIT_REMOTE=%q\n' "$GIT_REMOTE"
    printf 'GIT_DIRTY=%q\n' "$GIT_DIRTY"
  )
}

dingqiao_load_git_provenance() {
  local repo_root="$1"
  eval "$(dingqiao_collect_git_provenance "$repo_root")"
}

dingqiao_assert_reproducible_build() {
  if [[ "${DINGQIAO_ALLOW_DIRTY:-}" == "1" ]]; then
    return 0
  fi
  if [[ "${GIT_DIRTY:-false}" == "true" ]]; then
    echo "[ERROR] working tree is dirty — commit and push before official delivery pack." >&2
    echo "        (local preview only: DINGQIAO_ALLOW_DIRTY=1 bash asr/tools/delivery/...)" >&2
    exit 1
  fi
}

dingqiao_read_buildconfig_sdk_version() {
  local ar_root="$1"
  local bc="$ar_root/sdk/build/generated/source/buildConfig/release/com/amphion/asr/BuildConfig.java"
  if [[ ! -f "$bc" ]]; then
    echo "[ERROR] missing $bc — run :sdk:assembleRelease first" >&2
    exit 1
  fi
  sed -n 's/.*SDK_VERSION = "\([^"]*\)".*/\1/p' "$bc" | head -1
}

dingqiao_assert_sdk_version_consistent() {
  local ar_root="$1"
  local gradle_ver buildconfig_ver
  gradle_ver="$(dingqiao_read_sdk_version "$ar_root")"
  buildconfig_ver="$(dingqiao_read_buildconfig_sdk_version "$ar_root")"
  if [[ "$gradle_ver" != "$buildconfig_ver" ]]; then
    echo "[ERROR] SDK version mismatch: gradle.properties=$gradle_ver BuildConfig.SDK_VERSION=$buildconfig_ver" >&2
    echo "        Re-run ./gradlew :sdk:assembleRelease after editing gradle.properties" >&2
    exit 1
  fi
  SDK_VERSION="$gradle_ver"
  BUILDCONFIG_SDK_VERSION="$buildconfig_ver"
  export SDK_VERSION BUILDCONFIG_SDK_VERSION
}

dingqiao_embed_aar_build_manifest() {
  local merge_dir="$1"
  local ar_root="$2"
  local delivery_version="${3:-}"
  mkdir -p "$merge_dir/META-INF"
  local sdk_ver
  sdk_ver="$(dingqiao_read_sdk_version "$ar_root")"
  cat > "$merge_dir/META-INF/amphion-dingqiao-build.properties" <<EOF
# Auto-generated at fat AAR merge time — do not edit.
provenance.schema=1
amphion.sdk.version=$sdk_ver
amphion.buildconfig.sdk.version=${BUILDCONFIG_SDK_VERSION:-$sdk_ver}
amphion.delivery.version=${delivery_version:-$sdk_ver}
amphion.delivery.status=${DINGQIAO_DELIVERY_STATUS_CODE:-formal}
amphion.git.commit.full=${GIT_COMMIT_FULL:-unknown}
amphion.git.commit.short=${GIT_COMMIT_SHORT:-unknown}
amphion.git.branch=${GIT_BRANCH:-unknown}
amphion.git.dirty=${GIT_DIRTY:-unknown}
amphion.build.date=${BUILD_DATE:-unknown}
amphion.repo.remote=${GIT_REMOTE:-unknown}
EOF
}

dingqiao_verify_aar_provenance() {
  local aar_path="$1"
  local expected_sdk="${2:-}"
  local expected_commit="${3:-}"
  local expected_status="${4:-}"
  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  unzip -q "$aar_path" "META-INF/amphion-dingqiao-build.properties" -d "$tmp"
  local manifest="$tmp/META-INF/amphion-dingqiao-build.properties"
  if [[ ! -f "$manifest" ]]; then
    echo "[ERROR] $aar_path missing META-INF/amphion-dingqiao-build.properties" >&2
    return 1
  fi
  if [[ -n "$expected_sdk" ]]; then
    grep -q "amphion.sdk.version=$expected_sdk" "$manifest" || {
      echo "[ERROR] AAR embedded sdk.version != $expected_sdk" >&2
      cat "$manifest" >&2
      return 1
    }
  fi
  if [[ -n "$expected_commit" ]]; then
    grep -q "amphion.git.commit.full=$expected_commit" "$manifest" || {
      echo "[ERROR] AAR embedded git commit != $expected_commit" >&2
      cat "$manifest" >&2
      return 1
    }
  fi
  if [[ -n "$expected_status" ]]; then
    grep -q "amphion.delivery.status=$expected_status" "$manifest" || {
      echo "[ERROR] AAR embedded delivery.status != $expected_status" >&2
      cat "$manifest" >&2
      return 1
    }
  fi
  echo "[OK] AAR provenance verified: $(basename "$aar_path")"
}

dingqiao_verify_aar_native_libs() {
  local aar_path="$1"
  python3 - "$aar_path" <<'PY'
import json
import sys
import zipfile

aar_path = sys.argv[1]
required = [
    "jni/arm64-v8a/libamphion_audio_processing.so",
    "jni/arm64-v8a/libamphion_diarization_jni.so",
    "jni/arm64-v8a/libamphion_police_jni.so",
    "jni/arm64-v8a/libsherpa-onnx-jni.so",
    "jni/arm64-v8a/libonnxruntime.so",
]

try:
    with zipfile.ZipFile(aar_path) as aar:
        sizes = {info.filename: info.file_size for info in aar.infolist()}
        manifest = json.loads(aar.read("assets/amphion-models/manifest.json"))
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid AAR zip: {aar_path}: {exc}", file=sys.stderr)
    sys.exit(1)

missing = [path for path in required if path not in sizes]
empty = [path for path in required if path in sizes and sizes[path] <= 0]

if missing or empty:
    if missing:
        print("[ERROR] AAR missing required native libs:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
    if empty:
        print("[ERROR] AAR contains empty native libs:", file=sys.stderr)
        for path in empty:
            print(f"  - {path}", file=sys.stderr)
    sys.exit(1)

for path in required:
    print(f"[OK] AAR native lib present: {path} ({sizes[path]} bytes)")
PY
}

dingqiao_verify_aar_speaker_model() {
  local aar_path="$1"
  python3 - "$aar_path" <<'PY'
import sys
import zipfile

aar_path = sys.argv[1]
required = {
    "assets/amphion-dingqiao/eres2net.onnx": 30 * 1024 * 1024,
    "assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx": 5 * 1024 * 1024,
    "assets/lac/v1/lac_encoder.onnx": 20 * 1024 * 1024,
    "assets/lac/v1/lac_crf_transitions.npy": 1024,
    "assets/lac/v1/word.dic": 1024,
    "assets/lac/v1/tag.dic": 100,
}

try:
    with zipfile.ZipFile(aar_path) as aar:
        sizes = {info.filename: info.file_size for info in aar.infolist()}
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid AAR zip: {aar_path}: {exc}", file=sys.stderr)
    sys.exit(1)

for path, min_bytes in required.items():
    size = sizes.get(path)
    if size is None:
        print(f"[ERROR] AAR missing embedded enhancement asset: {path}", file=sys.stderr)
        sys.exit(1)
    if size < min_bytes:
        print(f"[ERROR] AAR enhancement asset too small: {path} ({size} bytes)", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] AAR enhancement asset present: {path} ({size} bytes)")
PY
}

dingqiao_verify_aar_asr_models() {
  local aar_path="$1"
  python3 - "$aar_path" <<'PY'
import json
import sys
import zipfile

aar_path = sys.argv[1]
required = {
    "assets/amphion-models/manifest.json": 100,
    "assets/amphion-models/itn-zh/v1/zh_itn_tagger.fst": 1024 * 1024,
    "assets/amphion-models/itn-zh/v1/zh_itn_verbalizer.fst": 100 * 1024,
    "assets/amphion-models/punct-zhen/v1/model.int8.ort.mp3": 50 * 1024 * 1024,
    "assets/amphion-models/vad/v1/silero_vad.onnx": 500 * 1024,
    "assets/amphion-models/zh-en/v1/encoder.int8.ort.mp3": 100 * 1024 * 1024,
    "assets/amphion-models/zh-en/v1/decoder.ort.mp3": 10 * 1024 * 1024,
    "assets/amphion-models/zh-en/v1/joiner.int8.ort.mp3": 1024 * 1024,
    "assets/amphion-models/zh-en/v1/tokens.txt": 10 * 1024,
    "assets/amphion-models/zh-en/v1/bbpe.vocab": 10 * 1024,
}

try:
    with zipfile.ZipFile(aar_path) as aar:
        sizes = {info.filename: info.file_size for info in aar.infolist()}
        manifest = json.loads(aar.read("assets/amphion-models/manifest.json"))
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid AAR zip: {aar_path}: {exc}", file=sys.stderr)
    sys.exit(1)

if "yue-en/v1" in manifest.get("bundles", {}):
    required.update({
        "assets/amphion-models/yue-en/v1/encoder.int8.onnx.mp3": 100 * 1024 * 1024,
        "assets/amphion-models/yue-en/v1/decoder.onnx.mp3": 10 * 1024 * 1024,
        "assets/amphion-models/yue-en/v1/joiner.int8.onnx.mp3": 1024 * 1024,
        "assets/amphion-models/yue-en/v1/tokens.txt": 10 * 1024,
        "assets/amphion-models/yue-en/v1/bbpe.vocab": 10 * 1024,
    })

for path, min_bytes in required.items():
    size = sizes.get(path)
    if size is None:
        print(f"[ERROR] AAR missing ASR model asset: {path}", file=sys.stderr)
        sys.exit(1)
    if size < min_bytes:
        print(f"[ERROR] AAR ASR model asset too small: {path} ({size} bytes, min {min_bytes})", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] AAR ASR model asset present: {path} ({size} bytes)")
PY
}

dingqiao_verify_apk_native_libs() {
  local apk_path="$1"
  python3 - "$apk_path" <<'PY'
import json
import sys
import zipfile

apk_path = sys.argv[1]
required = [
    "lib/arm64-v8a/libamphion_audio_processing.so",
    "lib/arm64-v8a/libamphion_diarization_jni.so",
    "lib/arm64-v8a/libamphion_police_jni.so",
    "lib/arm64-v8a/libsherpa-onnx-jni.so",
    "lib/arm64-v8a/libonnxruntime.so",
]

try:
    with zipfile.ZipFile(apk_path) as apk:
        entries = {info.filename: info for info in apk.infolist()}
        sizes = {name: info.file_size for name, info in entries.items()}
        manifest = json.loads(apk.read("assets/amphion-models/manifest.json"))
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid APK zip: {apk_path}: {exc}", file=sys.stderr)
    sys.exit(1)

missing = [path for path in required if path not in sizes]
empty = [path for path in required if path in sizes and sizes[path] <= 0]

if missing or empty:
    if missing:
        print("[ERROR] APK missing required native libs:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
    if empty:
        print("[ERROR] APK contains empty native libs:", file=sys.stderr)
        for path in empty:
            print(f"  - {path}", file=sys.stderr)
    sys.exit(1)

for path in required:
    print(f"[OK] APK native lib present: {path} ({sizes[path]} bytes)")
PY
}

dingqiao_verify_apk_speaker_model() {
  local apk_path="$1"
  python3 - "$apk_path" <<'PY'
import sys
import zipfile

apk_path = sys.argv[1]
required = {
    "assets/amphion-dingqiao/eres2net.onnx": 30 * 1024 * 1024,
    "assets/amphion-dingqiao/pyannote-segmentation-3.0.onnx": 5 * 1024 * 1024,
    "assets/lac/v1/lac_encoder.onnx": 20 * 1024 * 1024,
    "assets/lac/v1/lac_crf_transitions.npy": 1024,
}

try:
    with zipfile.ZipFile(apk_path) as apk:
        sizes = {info.filename: info.file_size for info in apk.infolist()}
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid APK zip: {apk_path}: {exc}", file=sys.stderr)
    sys.exit(1)

for path, min_bytes in required.items():
    size = sizes.get(path)
    if size is None:
        print(f"[ERROR] APK missing embedded enhancement asset: {path}", file=sys.stderr)
        sys.exit(1)
    if size < min_bytes:
        print(f"[ERROR] APK enhancement asset too small: {path} ({size} bytes)", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] APK enhancement asset present: {path} ({size} bytes)")
PY
}

dingqiao_verify_apk_asr_models() {
  local apk_path="$1"
  python3 - "$apk_path" <<'PY'
import json
import sys
import zipfile

apk_path = sys.argv[1]
required = {
    "assets/amphion-models/manifest.json": 100,
    "assets/amphion-models/itn-zh/v1/zh_itn_tagger.fst": 1024 * 1024,
    "assets/amphion-models/itn-zh/v1/zh_itn_verbalizer.fst": 100 * 1024,
    "assets/amphion-models/punct-zhen/v1/model.int8.ort.mp3": 50 * 1024 * 1024,
    "assets/amphion-models/vad/v1/silero_vad.onnx": 500 * 1024,
    "assets/amphion-models/zh-en/v1/encoder.int8.ort.mp3": 100 * 1024 * 1024,
    "assets/amphion-models/zh-en/v1/decoder.ort.mp3": 10 * 1024 * 1024,
    "assets/amphion-models/zh-en/v1/joiner.int8.ort.mp3": 1024 * 1024,
    "assets/amphion-models/zh-en/v1/tokens.txt": 10 * 1024,
    "assets/amphion-models/zh-en/v1/bbpe.vocab": 10 * 1024,
}

try:
    with zipfile.ZipFile(apk_path) as apk:
        entries = {info.filename: info for info in apk.infolist()}
        sizes = {path: info.file_size for path, info in entries.items()}
        manifest = json.loads(apk.read("assets/amphion-models/manifest.json"))
except zipfile.BadZipFile as exc:
    print(f"[ERROR] invalid APK zip: {apk_path}: {exc}", file=sys.stderr)
    sys.exit(1)

if "yue-en/v1" in manifest.get("bundles", {}):
    required.update({
        "assets/amphion-models/yue-en/v1/encoder.int8.onnx.mp3": 100 * 1024 * 1024,
        "assets/amphion-models/yue-en/v1/decoder.onnx.mp3": 10 * 1024 * 1024,
        "assets/amphion-models/yue-en/v1/joiner.int8.onnx.mp3": 1024 * 1024,
        "assets/amphion-models/yue-en/v1/tokens.txt": 10 * 1024,
        "assets/amphion-models/yue-en/v1/bbpe.vocab": 10 * 1024,
    })

for path, min_bytes in required.items():
    size = sizes.get(path)
    if size is None:
        print(f"[ERROR] APK missing ASR model asset: {path}", file=sys.stderr)
        sys.exit(1)
    if size < min_bytes:
        print(f"[ERROR] APK ASR model asset too small: {path} ({size} bytes, min {min_bytes})", file=sys.stderr)
        sys.exit(1)
    if path.endswith(".mp3") and entries[path].compress_type != zipfile.ZIP_STORED:
        print(f"[ERROR] APK direct-load model must be ZIP_STORED: {path}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] APK ASR model asset present: {path} ({size} bytes)")
PY
}

dingqiao_cert_sha256_from_keystore() {
  delivery_cert_sha256_from_keystore "$@"
}

dingqiao_sign_apk() {
  delivery_sign_apk "$@"
}

dingqiao_verify_apk_signature() {
  delivery_verify_apk_signature "$@"
}

dingqiao_apk_cert_sha256_from_apk() {
  delivery_apk_cert_sha256_from_apk "$@"
}

dingqiao_write_version_txt() {
  local out_file="$1"
  local package_id="$2"
  local delivery_version="$3"
  shift 3
  {
    dingqiao_standard_version_fields "$package_id" "$delivery_version"
    for kv in "$@"; do
      [[ -n "$kv" ]] && printf '%s\n' "$kv"
    done
  } > "$out_file"
}

dingqiao_write_version_txt_header() {
  dingqiao_write_version_txt "$@"
}

dingqiao_append_version_txt() {
  local out="$1"
  shift
  for kv in "$@"; do
    printf '%s\n' "$kv" >> "$out"
  done
}

dingqiao_standard_version_fields() {
  local package_id="$1"
  local delivery_version="$2"
  printf '%s\n' \
    "package=$package_id" \
    "delivery_version=$delivery_version" \
    "sdk_version=$SDK_VERSION" \
    "buildconfig_sdk_version=${BUILDCONFIG_SDK_VERSION:-$SDK_VERSION}" \
    "git_commit=$GIT_COMMIT_SHORT" \
    "git_commit_full=$GIT_COMMIT_FULL" \
    "git_branch=$GIT_BRANCH" \
    "git_dirty=$GIT_DIRTY" \
    "git_remote=$GIT_REMOTE" \
    "build_date=${BUILD_DATE:-$(date +%Y%m%d)}"
}

# 交付 zip：非 ASCII 文件名须设 UTF-8 EFS（Windows 资源管理器解压）
dingqiao_zip_delivery() {
  local source_dir="$1"
  local dest_zip="$2"
  local py
  py="$(
    cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
  )/dingqiao_zip_utf8.py"
  if [[ ! -f "$py" ]]; then
    echo "[ERROR] missing $py" >&2
    exit 1
  fi
  python3 "$py" create "$source_dir" "$dest_zip"
}

dingqiao_stage_customer_docs() {
  local out_docs="$1"
  local customer_docs="$2"
  local _legacy_dq_root="${3:-}"
  local repo_root
  repo_root="$(git -C "$customer_docs" rev-parse --show-toplevel)"
  mkdir -p "$out_docs"
  [[ -f "$customer_docs/语音识别SDK接口.md" ]] || {
    echo "[ERROR] missing customer API contract at $customer_docs/语音识别SDK接口.md" >&2
    exit 1
  }
  python3 "$repo_root/asr/tools/dingqiao_parameter_contract.py" \
    "$customer_docs/语音识别SDK接口.md"
  cp "$customer_docs/语音识别SDK接口.md" "$out_docs/"
  cp "$repo_root/shared/api-spec/dingqiao-asr-parameters.json" \
    "$out_docs/DINGQIAO_ASR_PARAMETER_CONTRACT.json"
  cp "$customer_docs/DINGQIAO_INTEGRATION.md" "$out_docs/"
  cp "$customer_docs/LICENSE.md" "$out_docs/"
  cp "$customer_docs/NOTICE" "$out_docs/NOTICE"
  mkdir -p "$out_docs/third-party"
  cp "$repo_root/LICENSE" "$out_docs/third-party/Apache-2.0.txt"
  cp "$repo_root/asr/native/audio-processing/LICENSES/WEBRTC_AUDIO_PROCESSING.txt" \
    "$out_docs/third-party/WebRTC-BSD-3-Clause.txt"
  if [[ -f "$customer_docs/DINGQIAO_VOICEPRINT_MODEL.md" ]]; then
    cp "$customer_docs/DINGQIAO_VOICEPRINT_MODEL.md" "$out_docs/"
  fi
  [[ -f "$out_docs/NOTICE" ]] || {
    echo "[ERROR] missing customer NOTICE at $customer_docs/NOTICE" >&2
    exit 1
  }
}

# Demo Release APK 内嵌 license：自签发日起 DINGQIAO_DEMO_TRIAL_MONTHS（默认 2）个月试用。
# Demo 记录包名并可绑定 Demo 签名，不绑定 SN；正式客户 license 才绑定 SN 清单。
dingqiao_issue_demo_license() {
  local repo_root="$1"
  bash "$repo_root/asr/tools/license/issue_dingqiao_demo.sh"
}
