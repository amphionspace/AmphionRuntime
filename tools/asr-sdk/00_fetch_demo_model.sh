#!/usr/bin/env bash
# 准备一份"标准布局"的演示模型，用来在 你自己的 ONNX 还没导出之前 把工程跑通。
#
# 使用的是官方 sherpa-onnx 中英流式 zipformer：
#   sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20
# 大小约 380 MB（含 FP32 + INT8 多个版本），下载完只挑 INT8 版本进 SDK 目录。
#
# 用法：
#   bash tools/asr-sdk/00_fetch_demo_model.sh                    # 仅下载 + 重命名 + 生成 manifest
#   bash tools/asr-sdk/00_fetch_demo_model.sh push               # 同上，再用 adb push 到设备
#   bash tools/asr-sdk/00_fetch_demo_model.sh push <serial>      # 指定 adb 设备序列号

set -euo pipefail

ACTION="${1:-prepare}"
DEVICE_SERIAL="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ----- 模型常量（也用作 model_id 与 version；不要随意改，跟 ModelImporter 是配对的） -----
MODEL_ID="sherpa-onnx-streaming-zh-en-demo"
MODEL_VERSION="1.0.0"
SAMPLE_PKG="com.yourco.asr.sample"   # 与 sample/build.gradle.kts 中 applicationId 保持一致
UPSTREAM_NAME="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
UPSTREAM_TAR_URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${UPSTREAM_NAME}.tar.bz2"

OUT_ROOT="$REPO_ROOT/tools/asr-sdk/demo-model"
OUT_DIR="$OUT_ROOT/${MODEL_ID}/${MODEL_VERSION}"

# ----- 一些工具方法 -----
have() { command -v "$1" >/dev/null 2>&1; }

require() {
  if ! have "$1"; then
    echo "[ERROR] 需要命令: $1, 请先安装"
    exit 1
  fi
}

# ----- 步骤 1：下载并解压（只在没下载过时） -----
prepare_model() {
  mkdir -p "$OUT_ROOT"
  cd "$OUT_ROOT"

  if [[ -d "$UPSTREAM_NAME" && -f "$UPSTREAM_NAME/tokens.txt" ]]; then
    echo "[INFO] 已经有 ${OUT_ROOT}/${UPSTREAM_NAME}，跳过下载。"
  else
    echo "[INFO] 下载 $UPSTREAM_TAR_URL"
    require curl
    require tar
    curl -L --fail -o "${UPSTREAM_NAME}.tar.bz2" "$UPSTREAM_TAR_URL"
    echo "[INFO] 解压..."
    tar xjf "${UPSTREAM_NAME}.tar.bz2"
    rm -f "${UPSTREAM_NAME}.tar.bz2"
  fi

  # ----- 步骤 2：按 SDK 标准布局重命名 -----
  mkdir -p "$OUT_DIR"

  cp -fv "$UPSTREAM_NAME/encoder-epoch-99-avg-1.int8.onnx"  "$OUT_DIR/encoder.int8.onnx"
  cp -fv "$UPSTREAM_NAME/decoder-epoch-99-avg-1.onnx"       "$OUT_DIR/decoder.onnx"
  cp -fv "$UPSTREAM_NAME/joiner-epoch-99-avg-1.int8.onnx"   "$OUT_DIR/joiner.int8.onnx"
  cp -fv "$UPSTREAM_NAME/tokens.txt"                        "$OUT_DIR/tokens.txt"

  # ----- 步骤 3：生成 manifest.json（虽然 sample 走 importer，不走下载，但保留以备后续测试） -----
  if have python3; then
    ( cd "$OUT_DIR" && python3 - <<PY
import hashlib, json, os, pathlib

MODEL_ID = "$MODEL_ID"
VERSION = "$MODEL_VERSION"
BASE_URL = f"https://your-cdn.example.com/{MODEL_ID}/{VERSION}"
FILES = ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt"]

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

manifest = {
    "manifest_version": 1,
    "model_id": MODEL_ID,
    "version": VERSION,
    "min_sdk_version": "1.0.0",
    "max_sdk_version": "2.0.0",
    "model_type": "zipformer",
    "decoding_method": "greedy_search",
    "sample_rate": 16000,
    "feature_dim": 80,
    "files": [
        {
            "name": n,
            "url": f"{BASE_URL}/{n}",
            "size_bytes": os.path.getsize(n),
            "sha256": sha256(n),
        } for n in FILES
    ],
}

pathlib.Path("manifest.json").write_text(
    json.dumps(manifest, indent=2, ensure_ascii=False)
)
print("manifest.json written")
PY
    )
  else
    echo "[WARN] 没有 python3，跳过 manifest.json 生成"
  fi

  echo
  echo "================================================"
  echo "[DONE] demo 模型准备完成："
  echo "       $OUT_DIR"
  ls -lh "$OUT_DIR/"
  echo "================================================"
}

# ----- 步骤 4：可选 adb push 到设备 -----
push_to_device() {
  require adb

  local adb_cmd=(adb)
  if [[ -n "$DEVICE_SERIAL" ]]; then
    adb_cmd+=(-s "$DEVICE_SERIAL")
  fi

  echo "[INFO] 检查设备..."
  "${adb_cmd[@]}" get-state >/dev/null || {
    echo "[ERROR] 没有连接的 adb 设备，先 adb devices 看看"; exit 1;
  }

  # externalFilesDir 路径：/sdcard/Android/data/<pkg>/files/asr-models-import/<id>/<v>/
  local DEV_DIR="/sdcard/Android/data/${SAMPLE_PKG}/files/asr-models-import/${MODEL_ID}/${MODEL_VERSION}"

  echo "[INFO] 检查 $SAMPLE_PKG 是否已安装到设备..."
  if ! "${adb_cmd[@]}" shell pm list packages 2>/dev/null | grep -q "package:${SAMPLE_PKG}$"; then
    cat <<EOF
[ERROR] 设备上没有安装 ${SAMPLE_PKG}。
        externalFilesDir 必须由 app 至少启动一次后才存在。请先：

          cd $REPO_ROOT/android/SherpaAsrSdk
          bash init_gradle_wrapper.sh
          ./gradlew :sample:installDebug
          adb shell am start -n ${SAMPLE_PKG}/.MainActivity

        然后再 重新跑本脚本 push。
EOF
    exit 1
  fi

  echo "[INFO] 创建设备目录: $DEV_DIR"
  "${adb_cmd[@]}" shell "mkdir -p $DEV_DIR"

  echo "[INFO] push 模型文件..."
  for f in encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt manifest.json; do
    if [[ -f "$OUT_DIR/$f" ]]; then
      "${adb_cmd[@]}" push "$OUT_DIR/$f" "$DEV_DIR/$f"
    fi
  done

  echo
  echo "[DONE] 模型已 push 到设备。"
  echo "       重启 sample app（按 home 退出再重新打开）即可看到 import 日志，模型自动迁移到 filesDir/asr-models/。"
  echo
  echo "[HINT] 看日志："
  echo "         adb logcat -s AsrSdk AsrSampleImporter MainActivity"
}

# ----- 主流程 -----
case "$ACTION" in
  prepare)
    prepare_model
    cat <<EOF

[NEXT] 如果你想现在 push 到测试设备：

         bash tools/asr-sdk/00_fetch_demo_model.sh push

       或者带设备序列号：

         bash tools/asr-sdk/00_fetch_demo_model.sh push <adb-serial>

EOF
    ;;
  push)
    if [[ ! -f "$OUT_DIR/encoder.int8.onnx" ]]; then
      echo "[INFO] 还没有下载，先准备模型..."
      prepare_model
    fi
    push_to_device
    ;;
  *)
    echo "Usage: $0 [prepare|push] [<adb-serial>]"
    exit 1
    ;;
esac
