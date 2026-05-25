#!/usr/bin/env bash
# 把"自己导出 + 量化好"的 ONNX 模型 push 到一台已经装好 sample app 的设备。
#
# 期望本地目录布局（4 个文件名固定，SDK 内部按这套名字加载，参考 MODEL_LAYOUT.md）：
#
#   <src>/
#   ├── encoder.int8.onnx
#   ├── decoder.onnx
#   ├── joiner.int8.onnx
#   ├── tokens.txt
#   └── manifest.json    # 可选；建议带，能让 EngineImpl 直接读到 model_type / decoding_method
#
# Push 之后 sample app 重启时，ModelImporter 会把：
#   /sdcard/Android/data/<pkg>/files/asr-models-import/<id>/<v>/
# 一次性迁移到内部存储：
#   /data/data/<pkg>/files/asr-models/<id>/<v>/
# SDK 加载的就是后者。
#
# 用法：
#   bash tools/asr/00_push_my_model.sh \
#       --src /path/to/your/model-dir \
#       --id  asr-streaming-zipformer-zh-en \
#       --version 1.0.1
#
# 可选参数：
#   --serial <adb-serial>     连了多个设备时指定目标
#   --pkg <package-name>      默认 com.amphion.asr.sample；改了 applicationId 的话用这个传
#   --skip-checks             跳过文件名/tokens.txt 头检查（不建议）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

SRC=""
MODEL_ID=""
MODEL_VERSION=""
DEVICE_SERIAL=""
SAMPLE_PKG="com.amphion.asr.sample"
SKIP_CHECKS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src)        SRC="$2"; shift 2 ;;
    --id)         MODEL_ID="$2"; shift 2 ;;
    --version)    MODEL_VERSION="$2"; shift 2 ;;
    --serial)     DEVICE_SERIAL="$2"; shift 2 ;;
    --pkg)        SAMPLE_PKG="$2"; shift 2 ;;
    --skip-checks) SKIP_CHECKS="1"; shift ;;
    -h|--help)
      sed -n '2,28p' "$0"; exit 0 ;;
    *)
      echo "[ERROR] 未知参数: $1"; exit 1 ;;
  esac
done

if [[ -z "$SRC" || -z "$MODEL_ID" || -z "$MODEL_VERSION" ]]; then
  echo "[ERROR] 必需参数缺失：--src --id --version"
  echo "        参考： bash $0 --help"
  exit 1
fi

[[ -d "$SRC" ]] || { echo "[ERROR] 源目录不存在: $SRC"; exit 1; }

REQUIRED=(encoder.int8.onnx decoder.onnx joiner.int8.onnx tokens.txt)
OPTIONAL=(manifest.json)

# ----- 文件存在性检查 -----
if [[ "$SKIP_CHECKS" != "1" ]]; then
  echo "[CHECK] 校验源目录必需文件..."
  for f in "${REQUIRED[@]}"; do
    if [[ ! -f "$SRC/$f" ]]; then
      cat <<EOF
[ERROR] 缺少必需文件: $SRC/$f
        SDK 内部硬编码这 4 个文件名（见 EngineImpl.kt）：
          - encoder.int8.onnx
          - decoder.onnx
          - joiner.int8.onnx
          - tokens.txt
        如果你的导出脚本输出名字带 epoch-99-avg-1 之类后缀，请先重命名。
        参考 tools/asr/01_export_to_onnx.md 的最后一步。
EOF
      exit 1
    fi
  done

  # tokens.txt 第一行必须是 <blk> 0
  FIRST_LINE="$(head -1 "$SRC/tokens.txt" 2>/dev/null || true)"
  if [[ "$FIRST_LINE" != "<blk> 0"* ]]; then
    cat <<EOF
[ERROR] $SRC/tokens.txt 第一行应当是 "<blk> 0"，实际是: $FIRST_LINE
        sherpa-onnx 加载 transducer 时会把 id=0 的 token 当作 blank。
        这一条不满足通常意味着 tokens.txt 是从 BPE 模型直接 dump 出来的、忘了
        加 <blk>。可以参考 MODEL_LAYOUT.md 第 2 节修正，或者用 --skip-checks 强行 push。
EOF
    exit 1
  fi
fi

# ----- 简要展示要 push 的清单 -----
echo
echo "================================================"
echo "Source:       $SRC"
echo "Model ID:     $MODEL_ID"
echo "Version:      $MODEL_VERSION"
echo "Sample pkg:   $SAMPLE_PKG"
[[ -n "$DEVICE_SERIAL" ]] && echo "ADB serial:   $DEVICE_SERIAL"
echo "Files:"
for f in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do
  if [[ -f "$SRC/$f" ]]; then
    SIZE="$(du -h "$SRC/$f" | awk '{print $1}')"
    printf "  %-22s %s\n" "$f" "$SIZE"
  fi
done
echo "================================================"

# ----- adb 命令拼装 -----
ADB=(adb)
if [[ -n "$DEVICE_SERIAL" ]]; then
  ADB+=(-s "$DEVICE_SERIAL")
fi

if ! command -v adb >/dev/null 2>&1; then
  echo "[ERROR] 找不到 adb，请把 \$ANDROID_HOME/platform-tools 加到 PATH"
  exit 1
fi

"${ADB[@]}" get-state >/dev/null 2>&1 || {
  echo "[ERROR] 没有连接的 adb 设备。先 'adb devices' 或 'adb connect'。"
  exit 1
}

# ----- 校验 sample 是否已安装 -----
if ! "${ADB[@]}" shell pm list packages 2>/dev/null | grep -q "package:${SAMPLE_PKG}$"; then
  cat <<EOF
[ERROR] 设备上没有安装 ${SAMPLE_PKG}。
        externalFilesDir 必须由 app 至少启动一次后才存在；请先：

          cd $REPO_ROOT/android/AmphionRuntime
          ./gradlew :sample:installDebug
          adb shell am start -n ${SAMPLE_PKG}/.eval.LandingActivity

        然后再回来跑本脚本。
EOF
  exit 1
fi

DEV_DIR="/sdcard/Android/data/${SAMPLE_PKG}/files/asr-models-import/${MODEL_ID}/${MODEL_VERSION}"
echo "[INFO] target on device: $DEV_DIR"
"${ADB[@]}" shell "rm -rf '$DEV_DIR' && mkdir -p '$DEV_DIR'"

# ----- push -----
for f in "${REQUIRED[@]}" "${OPTIONAL[@]}"; do
  if [[ -f "$SRC/$f" ]]; then
    "${ADB[@]}" push "$SRC/$f" "$DEV_DIR/$f"
  fi
done

cat <<EOF

[DONE] 模型已 push。重启 sample app 即可生效：

         adb shell am force-stop $SAMPLE_PKG
         adb shell am start -n ${SAMPLE_PKG}/.eval.LandingActivity

[HINT] 看 import / 加载日志：
         adb logcat -c && adb logcat -s AsrSdk AsrSampleImporter MainActivity *:E

[HINT] 如果设备上同时还有旧 demo 模型，sample 的 listLocal().firstOrNull() 顺序不可控。
       一次性清空所有已导入模型再 push 自己的，最简单：

         adb shell run-as $SAMPLE_PKG rm -rf files/asr-models
         bash $0 --src "$SRC" --id "$MODEL_ID" --version "$MODEL_VERSION"
EOF
