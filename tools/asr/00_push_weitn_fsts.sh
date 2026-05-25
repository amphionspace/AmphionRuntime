#!/usr/bin/env bash
# Build / fetch WeTextProcessing zh_itn fsts and push them to the sample app.
#
# WeitnEngine 需要两份 FST（中文 ITN）：
#   zh_itn_tagger.fst
#   zh_itn_verbalizer.fst
# 总和约 2-4 MB；同样不打进 APK，走 adb push 推到 externalFilesDir，
# sample 启动时由 WeitnAssetInstaller 拷到 internal filesDir/asr-weitn/.
#
# 资源来源（按优先级）：
#   1) WEITN_TAGGER_URL + WEITN_VERBALIZER_URL  环境变量提供的预编译 URL，
#      可选 WEITN_TAGGER_SHA256 / WEITN_VERBALIZER_SHA256 做完整性校验；
#   2) 本机 `pip install --quiet "WeTextProcessing==${WEITN_PIP_VERSION}"` 后
#      `python -c "from itn..."` 触发 pynini build 出两份 fst。
#
# 用法：
#   bash tools/asr/00_push_weitn_fsts.sh
#   bash tools/asr/00_push_weitn_fsts.sh --serial <adb-serial>
#   bash tools/asr/00_push_weitn_fsts.sh --pkg com.example.fork.asr  # fork 改名后
#   bash tools/asr/00_push_weitn_fsts.sh --no-push                   # 只编不 push
#   WEITN_TAGGER_URL=https://your-cdn.example.com/weitn/zh_itn_tagger.fst \
#   WEITN_VERBALIZER_URL=https://your-cdn.example.com/weitn/zh_itn_verbalizer.fst \
#     bash tools/asr/00_push_weitn_fsts.sh
#
# 注意 pynini 在 macOS arm64 / Linux 上需要 OpenFST C++ 编译依赖，建议在 conda
# 环境下 `conda install -c conda-forge pynini` 预装好。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

CACHE_DIR="${REPO_ROOT}/tools/asr/weitn-fsts"
TAGGER_FILE="${CACHE_DIR}/zh_itn_tagger.fst"
VERBALIZER_FILE="${CACHE_DIR}/zh_itn_verbalizer.fst"

# Pin to a specific WeTextProcessing release for reproducibility. Override if
# you intentionally need a newer feature. Releases:
#   https://github.com/wenet-e2e/WeTextProcessing/releases
WEITN_PIP_VERSION="${WEITN_PIP_VERSION:-1.0.4.1}"

WEITN_TAGGER_URL="${WEITN_TAGGER_URL:-}"
WEITN_VERBALIZER_URL="${WEITN_VERBALIZER_URL:-}"
WEITN_TAGGER_SHA256="${WEITN_TAGGER_SHA256:-}"
WEITN_VERBALIZER_SHA256="${WEITN_VERBALIZER_SHA256:-}"

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

verify_sha256_optional() {
  local file="$1"
  local expected="$2"
  if [[ -z "${expected}" ]]; then return 0; fi
  local cur
  cur="$(calc_sha256 "${file}")"
  if [[ "${cur}" != "${expected}" ]]; then
    cat >&2 <<EOF
[ERROR] sha256 mismatch for ${file}:
        expected: ${expected}
        actual:   ${cur}
EOF
    return 1
  fi
}

mkdir -p "${CACHE_DIR}"

# ----------------------------------------------------------------------------
# step 1: obtain zh_itn_tagger.fst + zh_itn_verbalizer.fst (URL or pip-build)
# ----------------------------------------------------------------------------

download_one() {
  local url="$1"
  local dst="$2"
  echo "[INFO] downloading ${url} -> ${dst}"
  if ! curl -fL --retry 3 --connect-timeout 15 -o "${dst}" "${url}"; then
    echo "[ERROR] download failed for ${url}" >&2
    rm -f "${dst}"
    return 1
  fi
}

build_via_pip() {
  if ! command -v python3 >/dev/null 2>&1; then
    cat >&2 <<EOF
[ERROR] python3 not in PATH; either:
        - install Python 3.9+ and re-run, or
        - host the prebuilt fsts somewhere and re-run with
            WEITN_TAGGER_URL=... WEITN_VERBALIZER_URL=...
EOF
    return 1
  fi

  echo "[INFO] installing WeTextProcessing==${WEITN_PIP_VERSION} (one-time)"
  if ! python3 -m pip install --quiet --upgrade "WeTextProcessing==${WEITN_PIP_VERSION}"; then
    cat >&2 <<EOF
[ERROR] pip install WeTextProcessing failed. On macOS arm64 / Linux you usually
        need pynini, which is easiest to install via conda:

          conda install -c conda-forge "pynini>=2.1.6"
          python -m pip install --no-deps "WeTextProcessing==${WEITN_PIP_VERSION}"

        Or skip the pip path entirely by setting WEITN_TAGGER_URL +
        WEITN_VERBALIZER_URL to prebuilt fst URLs.
EOF
    return 1
  fi

  echo "[INFO] building zh_itn fsts (cache_dir=${CACHE_DIR})"
  WEITN_CACHE_DIR="${CACHE_DIR}" python3 - <<'PY'
import os
import shutil
from itn.chinese.inverse_normalizer import InverseNormalizer

cache_dir = os.environ["WEITN_CACHE_DIR"]
os.makedirs(cache_dir, exist_ok=True)

itn = InverseNormalizer(cache_dir=cache_dir, overwrite_cache=False)
# Sanity check: the cache must contain the two fsts after construction.
for f in ("zh_itn_tagger.fst", "zh_itn_verbalizer.fst"):
    path = os.path.join(cache_dir, f)
    if not os.path.isfile(path):
        raise SystemExit(f"missing expected build output: {path}")
print("[INFO] WeText InverseNormalizer ready; sample normalize result:")
print("        ", itn.normalize("两点五八万"))
PY
}

need_fetch=1
if [[ -f "${TAGGER_FILE}" && -f "${VERBALIZER_FILE}" ]]; then
  echo "[SKIP] cached: ${TAGGER_FILE} ($(wc -c <"${TAGGER_FILE}" | tr -d ' ') B)"
  echo "[SKIP] cached: ${VERBALIZER_FILE} ($(wc -c <"${VERBALIZER_FILE}" | tr -d ' ') B)"
  need_fetch=0
fi

if [[ "${need_fetch}" == "1" ]]; then
  if [[ -n "${WEITN_TAGGER_URL}" && -n "${WEITN_VERBALIZER_URL}" ]]; then
    download_one "${WEITN_TAGGER_URL}" "${TAGGER_FILE}"
    download_one "${WEITN_VERBALIZER_URL}" "${VERBALIZER_FILE}"
  else
    build_via_pip
  fi
fi

verify_sha256_optional "${TAGGER_FILE}" "${WEITN_TAGGER_SHA256}" || exit 1
verify_sha256_optional "${VERBALIZER_FILE}" "${WEITN_VERBALIZER_SHA256}" || exit 1

if [[ ! -f "${TAGGER_FILE}" || ! -f "${VERBALIZER_FILE}" ]]; then
  echo "[ERROR] missing expected fsts under ${CACHE_DIR} after fetch / build" >&2
  exit 1
fi

TAGGER_SIZE="$(wc -c <"${TAGGER_FILE}" | tr -d ' ')"
VERBALIZER_SIZE="$(wc -c <"${VERBALIZER_FILE}" | tr -d ' ')"
echo "[OK] tagger:     ${TAGGER_FILE} (${TAGGER_SIZE}B)"
echo "[OK] verbalizer: ${VERBALIZER_FILE} (${VERBALIZER_SIZE}B)"

if [[ "${NO_PUSH}" == "1" ]]; then
  cat <<EOF
[DONE] --no-push was set; fsts ready under ${CACHE_DIR} only.
       Re-run without --no-push to push to the sample app.
EOF
  exit 0
fi

# ----------------------------------------------------------------------------
# step 2: adb push
# ----------------------------------------------------------------------------

if ! command -v adb >/dev/null 2>&1; then
  echo "[ERROR] adb not in PATH; re-run with --no-push if you only need the fsts" >&2
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

DEV_DIR="/sdcard/Android/data/${SAMPLE_PKG}/files/asr-weitn-import"
DEV_TAGGER="${DEV_DIR}/zh_itn_tagger.fst"
DEV_VERBALIZER="${DEV_DIR}/zh_itn_verbalizer.fst"
echo "[INFO] pushing to ${DEV_DIR}"
"${ADB[@]}" shell "rm -rf '${DEV_DIR}' && mkdir -p '${DEV_DIR}'"
"${ADB[@]}" push "${TAGGER_FILE}" "${DEV_TAGGER}"
"${ADB[@]}" push "${VERBALIZER_FILE}" "${DEV_VERBALIZER}"

cat <<EOF

[DONE] WeText ITN fsts pushed.
       Restart the sample and the "ITN" switch becomes available:

         adb shell am force-stop ${SAMPLE_PKG}
         adb shell am start -n ${SAMPLE_PKG}/.MainActivity

[HINT] At first launch, sample's WeitnAssetInstaller migrates
         ${DEV_DIR}/zh_itn_tagger.fst
         ${DEV_DIR}/zh_itn_verbalizer.fst
       into
         /data/data/${SAMPLE_PKG}/files/asr-weitn/{zh_itn_tagger.fst,zh_itn_verbalizer.fst}
       which is the path SDK's WeitnEngine actually opens.

[HINT] Watch the migration / load logs:
         adb logcat -c && adb logcat -s AsrSdk MainActivity WeitnAssetInstaller *:E
EOF
