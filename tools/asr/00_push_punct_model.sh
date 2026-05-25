#!/usr/bin/env bash
# 下载 sherpa-onnx 官方 CT-Transformer 中英双语标点模型并 push 到 sample app。
#
# 与 ITN 不同：标点模型体积大（~72 MB INT8），不打进 APK assets，走 adb push 推到
# externalFilesDir，sample 启动时由 PunctModelInstaller 拷到 internal filesDir/asr-punct/。
#
# 设计：
# - 把 tarball 缓存到 tools/asr/punct-model/<file>.tar.bz2（已被根 .gitignore 排除）
# - 缓存命中 sha256 时跳过下载，避免每次重新拉 60 MB
# - 同时校验 tarball 与解压后的 model.int8.onnx 的 sha256（上游若悄悄重打包，先报错再继续）
# - 默认 push 到 com.amphion.asr.sample 的 externalFilesDir；多设备时用 --serial 指定
# - --no-push：只下载 + 解压到本地 cache，不动设备
#
# 用法：
#   bash tools/asr/00_push_punct_model.sh
#   bash tools/asr/00_push_punct_model.sh --serial <adb-serial>
#   bash tools/asr/00_push_punct_model.sh --pkg com.example.fork.asr  # fork 改名后
#   bash tools/asr/00_push_punct_model.sh --no-push                   # 只下不 push
#
# 可选环境变量：
#   PUNCT_MODEL_URL    覆盖下载 URL（调试 / 内部镜像）
#   PUNCT_TAR_SHA256   覆盖 tarball 的 sha256
#   PUNCT_MODEL_SHA256 覆盖解压后 model.int8.onnx 的 sha256

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/punctuation-models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2"
DEFAULT_TAR_SHA256="c0d5aa5f8eeb686032345e180bedf39319dc2e0556781c6264bcadba8328a6e1"
DEFAULT_MODEL_SHA256="65a3fb9f5ad7bfb96bf69e0dc4481df97f6ee60513c1d94ce981ba6effd524b1"

URL="${PUNCT_MODEL_URL:-${DEFAULT_URL}}"
TAR_SHA256="${PUNCT_TAR_SHA256:-${DEFAULT_TAR_SHA256}}"
MODEL_SHA256="${PUNCT_MODEL_SHA256:-${DEFAULT_MODEL_SHA256}}"

CACHE_DIR="${REPO_ROOT}/tools/asr/punct-model"
TARBALL_BASENAME="sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8.tar.bz2"
EXTRACT_BASENAME="sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"
TAR_FILE="${CACHE_DIR}/${TARBALL_BASENAME}"
EXTRACT_DIR="${CACHE_DIR}/${EXTRACT_BASENAME}"
MODEL_FILE="${EXTRACT_DIR}/model.int8.onnx"

SAMPLE_PKG="com.amphion.asr.sample"
DEVICE_SERIAL=""
NO_PUSH="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --serial)   DEVICE_SERIAL="$2"; shift 2 ;;
    --pkg)      SAMPLE_PKG="$2"; shift 2 ;;
    --no-push)  NO_PUSH="1"; shift ;;
    -h|--help)
      sed -n '2,30p' "$0"; exit 0 ;;
    *)
      echo "[ERROR] unknown argument: $1" >&2
      exit 1 ;;
  esac
done

calc_sha256() {
  local f="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "${f}" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "${f}" | awk '{print $1}'
  else
    echo "[ERROR] neither shasum nor sha256sum found in PATH" >&2
    exit 1
  fi
}

mkdir -p "${CACHE_DIR}"

# ----- step 1: download tarball (sha256-verified, cache-hit aware) -----
need_download=1
if [[ -f "${TAR_FILE}" ]]; then
  cur="$(calc_sha256 "${TAR_FILE}")"
  if [[ "${cur}" == "${TAR_SHA256}" ]]; then
    echo "[SKIP] tarball cached: ${TAR_FILE} (sha256=${cur})"
    need_download=0
  else
    echo "[WARN] cached tarball sha256 mismatch (cur=${cur}, expected=${TAR_SHA256}); re-downloading"
    rm -f "${TAR_FILE}"
  fi
fi

if [[ "${need_download}" == "1" ]]; then
  echo "[INFO] downloading from ${URL}"
  if ! curl -fL --retry 3 --connect-timeout 15 -o "${TAR_FILE}" "${URL}"; then
    cat >&2 <<EOF
[ERROR] download failed.
        If you are behind a restricted network, set PUNCT_MODEL_URL to an internal
        mirror and retry; or download the tarball manually and drop it at
        ${TAR_FILE} before re-running this script.
EOF
    rm -f "${TAR_FILE}"
    exit 1
  fi
  cur="$(calc_sha256 "${TAR_FILE}")"
  if [[ "${cur}" != "${TAR_SHA256}" ]]; then
    cat >&2 <<EOF
[ERROR] tarball sha256 verification failed:
        expected: ${TAR_SHA256}
        actual:   ${cur}
        If sherpa-onnx upstream intentionally re-released the tarball, override
        PUNCT_TAR_SHA256 once or update DEFAULT_TAR_SHA256 in this script.
EOF
    rm -f "${TAR_FILE}"
    exit 1
  fi
fi

# ----- step 2: extract -----
need_extract=1
if [[ -f "${MODEL_FILE}" ]]; then
  cur="$(calc_sha256 "${MODEL_FILE}")"
  if [[ "${cur}" == "${MODEL_SHA256}" ]]; then
    echo "[SKIP] model.int8.onnx already extracted (sha256=${cur})"
    need_extract=0
  fi
fi

if [[ "${need_extract}" == "1" ]]; then
  echo "[INFO] extracting -> ${EXTRACT_DIR}"
  rm -rf "${EXTRACT_DIR}"
  tar -C "${CACHE_DIR}" -xjf "${TAR_FILE}"
  if [[ ! -f "${MODEL_FILE}" ]]; then
    echo "[ERROR] expected file missing after extract: ${MODEL_FILE}" >&2
    exit 1
  fi
  cur="$(calc_sha256 "${MODEL_FILE}")"
  if [[ "${cur}" != "${MODEL_SHA256}" ]]; then
    cat >&2 <<EOF
[ERROR] model.int8.onnx sha256 mismatch:
        expected: ${MODEL_SHA256}
        actual:   ${cur}
        Pin PUNCT_MODEL_SHA256 only after confirming upstream re-export is intentional.
EOF
    exit 1
  fi
fi

SIZE_BYTES="$(wc -c <"${MODEL_FILE}" | tr -d ' ')"
echo "[OK] ready: ${MODEL_FILE} size=${SIZE_BYTES}B sha256=${MODEL_SHA256}"

if [[ "${NO_PUSH}" == "1" ]]; then
  cat <<EOF
[DONE] --no-push was set; only downloaded + verified, did not touch the device.
       Re-run without --no-push to push to the sample app.
EOF
  exit 0
fi

# ----- step 3: adb push -----
if ! command -v adb >/dev/null 2>&1; then
  echo "[ERROR] adb not in PATH; re-run with --no-push if you only need the model file" >&2
  exit 1
fi

ADB=(adb)
if [[ -n "${DEVICE_SERIAL}" ]]; then
  ADB+=(-s "${DEVICE_SERIAL}")
fi

"${ADB[@]}" get-state >/dev/null 2>&1 || {
  echo "[ERROR] no adb device connected. Try 'adb devices' / 'adb connect' first." >&2
  exit 1
}

if ! "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "package:${SAMPLE_PKG}$"; then
  cat <<EOF
[ERROR] ${SAMPLE_PKG} is not installed on the device.
        externalFilesDir is created lazily on first app launch; install + start
        the sample first:

          cd ${REPO_ROOT}/android/AmphionRuntime
          ./gradlew :sample:installDebug
          adb shell am start -n ${SAMPLE_PKG}/.MainActivity

        Then re-run this script.
EOF
  exit 1
fi

DEV_DIR="/sdcard/Android/data/${SAMPLE_PKG}/files/asr-punct-import"
DEV_FILE="${DEV_DIR}/model.int8.onnx"
echo "[INFO] pushing to ${DEV_FILE}"
"${ADB[@]}" shell "rm -rf '${DEV_DIR}' && mkdir -p '${DEV_DIR}'"
"${ADB[@]}" push "${MODEL_FILE}" "${DEV_FILE}"

cat <<EOF

[DONE] punctuation model pushed.
       Restart the sample and the "标点" switch becomes available:

         adb shell am force-stop ${SAMPLE_PKG}
         adb shell am start -n ${SAMPLE_PKG}/.MainActivity

[HINT] At first launch, sample's PunctModelInstaller will migrate
         ${DEV_FILE}
       into
         /data/data/${SAMPLE_PKG}/files/asr-punct/model.int8.onnx
       which is the path SDK's PunctuationEngine actually opens.

[HINT] Watch the migration / load logs:
         adb logcat -c && adb logcat -s AsrSdk MainActivity PunctModelInstaller *:E
EOF
