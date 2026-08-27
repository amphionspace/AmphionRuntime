#!/usr/bin/env bash
# 组装"自包含" amphion_dingqiao.har:把 amphion_asr / amphion_police / sherpa_onnx 打进包内,
# 内部依赖改为 file:./ 相对路径。客户只需声明这一个 HAR,纯本地离线可解析(内网友好),
# 且整条链在 HAP 全量编译下可解析(已真机验证)。
#
# 背景:各 HAR 原本用仓库本地 file: 路径互相依赖,外部工程无法解析——
#   - 不剥离 -> ohpm 安装踩死路径失败;
#   - 剥离 -> HAP 编译期 amphion_dingqiao 找不到 amphion_asr(幽灵依赖);
#   只有自包含(file:./ 内部路径)两头都成立。
#
# 用法: assemble_selfcontained_dingqiao_har.sh [--zh-en-only]
#   [--approved-target-speaker-model-sha256 HASH] <输出 har 路径>
# 依赖: 四个 HAR 已由 DevEco 构建(见各模块 build/default/outputs/default/)。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ZH_EN_ONLY=false
APPROVED_TARGET_SPEAKER_MODEL_SHA256=""
SPEAKER_TURN_MODEL="$REPO_ROOT/shared/models/asr/dingqiao/pyannote-segmentation-3.0.onnx"
SPEAKER_TURN_METADATA="$SCRIPT_DIR/pyannote_segmentation_3_0.json"
while [[ $# -gt 1 ]]; do
  case "$1" in
    --zh-en-only) ZH_EN_ONLY=true; shift ;;
    --approved-target-speaker-model-sha256)
      [[ $# -ge 3 ]] || { echo "[ERROR] missing approved model SHA-256" >&2; exit 2; }
      APPROVED_TARGET_SPEAKER_MODEL_SHA256="$(printf '%s' "$2" | tr '[:upper:]' '[:lower:]')"
      shift 2
      ;;
    *) echo "[ERROR] unexpected argument: $1" >&2; exit 2 ;;
  esac
done
OUT="${1:?用法: $0 [--zh-en-only] [--approved-target-speaker-model-sha256 HASH] <输出 har 路径>}"
[[ $# -eq 1 ]] || { echo "[ERROR] unexpected arguments" >&2; exit 2; }
if [[ -n "$APPROVED_TARGET_SPEAKER_MODEL_SHA256" &&
  ! "$APPROVED_TARGET_SPEAKER_MODEL_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  echo "[ERROR] approved target-speaker model SHA-256 must be 64 hexadecimal characters" >&2
  exit 2
fi
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

har_of() {  # 取模块构建输出目录里唯一的 .har
  local dir="$1"
  local found=""
  local candidate
  for candidate in "$dir"/*.har; do
    [[ -f "$candidate" ]] || continue
    if [[ -n "$found" ]]; then
      echo "[ERROR] 构建输出目录存在多个 HAR: $dir" >&2
      return 1
    fi
    found="$candidate"
  done
  [[ -n "$found" ]] || { echo "[ERROR] 构建输出目录缺少 HAR: $dir" >&2; return 1; }
  printf '%s\n' "$found"
}
ASR_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default")"
POLICE_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default")"
DINGQIAO_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default")"
SHERPA_HAR="$(har_of "$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default")"

python3 - "$SPEAKER_TURN_MODEL" "$SPEAKER_TURN_METADATA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

model = Path(sys.argv[1])
metadata = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if not model.is_file():
    raise SystemExit(f"[ERROR] missing Speaker VAD boundary model: {model}")
digest = hashlib.sha256(model.read_bytes()).hexdigest()
if digest != metadata["sha256"]:
    raise SystemExit(f"[ERROR] Speaker VAD boundary model sha256 mismatch: {digest}")
PY
for h in "$ASR_HAR" "$POLICE_HAR" "$DINGQIAO_HAR" "$SHERPA_HAR"; do
  [[ -f "$h" ]] || { echo "[ERROR] 缺少已构建 HAR: $h  (请先用 DevEco 构建各模块)"; exit 1; }
  tar tzf "$h" >/dev/null || { echo "[ERROR] HAR 归档无效: $h" >&2; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/ex/asr" "$WORK/ex/police" "$WORK/ex/dingqiao" "$WORK/ex/sherpa"
tar xzf "$ASR_HAR" -C "$WORK/ex/asr"
tar xzf "$POLICE_HAR" -C "$WORK/ex/police"
tar xzf "$DINGQIAO_HAR" -C "$WORK/ex/dingqiao"
tar xzf "$SHERPA_HAR" -C "$WORK/ex/sherpa"

# dingqiao 为兼容外层；asr/police/sherpa 放入 package/_bundled/。
cp -R "$WORK/ex/dingqiao/package" "$WORK/sc"
mkdir -p "$WORK/sc/_bundled"
cp -R "$WORK/ex/asr/package"    "$WORK/sc/_bundled/amphion_asr"
cp -R "$WORK/ex/police/package" "$WORK/sc/_bundled/amphion_police"
cp -R "$WORK/ex/sherpa/package" "$WORK/sc/_bundled/sherpa_onnx"

# 改写内部依赖为包内相对路径(保留 .so 依赖)
python3 - "$WORK/sc" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])


def set_dependencies(relative_path: str, dependencies: dict[str, str]) -> None:
    package_path = root / relative_path / "oh-package.json5"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["dependencies"] = dependencies
    package_path.write_text(json.dumps(package, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


set_dependencies(".", {
    "amphion_asr": "file:./_bundled/amphion_asr",
    "libamphion_asr.so": "file:./_bundled/amphion_asr/src/main/cpp/types/libamphion_asr",
    "amphion_police": "file:./_bundled/amphion_police",
})
set_dependencies("_bundled/amphion_asr", {
    "sherpa_onnx": "file:../sherpa_onnx",
    "libamphion_asr.so": "file:./src/main/cpp/types/libamphion_asr",
})
set_dependencies("_bundled/amphion_police", {
    "amphion_asr": "file:../amphion_asr",
})
PY

# Conv-TasNet is never inherited accidentally from a developer/test HAR. Commercial delivery keeps
# it only when release engineering supplies the exact separately-approved model digest.
TARGET_SPEAKER_MODEL="$WORK/sc/src/main/resources/rawfile/amphion-dingqiao/convtasnet_16k.onnx"
if [[ -z "$APPROVED_TARGET_SPEAKER_MODEL_SHA256" ]]; then
  rm -f "$TARGET_SPEAKER_MODEL"
elif [[ ! -f "$TARGET_SPEAKER_MODEL" ]]; then
  echo "[ERROR] approved target-speaker model is not present in the source HAR" >&2
  exit 1
else
  ACTUAL_TARGET_SPEAKER_MODEL_SHA256="$(python3 - "$TARGET_SPEAKER_MODEL" <<'PY'
import hashlib
import sys
from pathlib import Path

print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
  if [[ "$ACTUAL_TARGET_SPEAKER_MODEL_SHA256" != "$APPROVED_TARGET_SPEAKER_MODEL_SHA256" ]]; then
    echo "[ERROR] target-speaker model SHA-256 differs from the separately approved artifact" >&2
    exit 1
  fi
fi

if [[ "$ZH_EN_ONLY" == true ]]; then
  python3 "$SCRIPT_DIR/filter_zh_en_model_payload.py" \
    "$WORK/sc/_bundled/amphion_asr/src/main/resources/rawfile/amphion-models"
  python3 "$SCRIPT_DIR/sanitize_public_har_payload.py" "$WORK/sc"
fi

# HAR 内容位于 package/ 下；由归一化 writer 固定 uid/gid/mtime，并禁止 xattr/AppleDouble 泄漏。
python3 "$SCRIPT_DIR/create_normalized_tar.py" "$WORK/sc" "$OUT"
echo "[DONE] 自包含 amphion_dingqiao.har -> $OUT ($(du -h "$OUT" | cut -f1))"
