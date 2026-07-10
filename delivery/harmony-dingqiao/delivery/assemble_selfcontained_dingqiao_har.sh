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
# 用法: assemble_selfcontained_dingqiao_har.sh <输出 har 路径>
# 依赖: 四个 HAR 已由 DevEco 构建(见各模块 build/default/outputs/default/)。
set -euo pipefail
OUT="${1:?用法: $0 <输出 har 路径>}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

har_of() {  # 取模块构建输出目录里唯一的 .har
  local dir="$1"
  ls "$dir"/*.har 2>/dev/null | head -1
}
ASR_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk/build/default/outputs/default")"
POLICE_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk-police/build/default/outputs/default")"
DINGQIAO_HAR="$(har_of "$REPO_ROOT/asr/harmony/sdk-dingqiao/build/default/outputs/default")"
SHERPA_HAR="$(har_of "$REPO_ROOT/third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default")"
for h in "$ASR_HAR" "$POLICE_HAR" "$DINGQIAO_HAR" "$SHERPA_HAR"; do
  [[ -f "$h" ]] || { echo "[ERROR] 缺少已构建 HAR: $h  (请先用 DevEco 构建各模块)"; exit 1; }
done

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/ex/asr" "$WORK/ex/police" "$WORK/ex/dingqiao" "$WORK/ex/sherpa"
tar xzf "$ASR_HAR" -C "$WORK/ex/asr"
tar xzf "$POLICE_HAR" -C "$WORK/ex/police"
tar xzf "$DINGQIAO_HAR" -C "$WORK/ex/dingqiao"
tar xzf "$SHERPA_HAR" -C "$WORK/ex/sherpa"

# dingqiao 为外层;asr/police/sherpa 放入 package/_bundled/
cp -R "$WORK/ex/dingqiao/package" "$WORK/sc"
mkdir -p "$WORK/sc/_bundled"
cp -R "$WORK/ex/asr/package"    "$WORK/sc/_bundled/amphion_asr"
cp -R "$WORK/ex/police/package" "$WORK/sc/_bundled/amphion_police"
cp -R "$WORK/ex/sherpa/package" "$WORK/sc/_bundled/sherpa_onnx"

# 改写内部依赖为包内相对路径(保留 .so 依赖)
python3 - "$WORK/sc" <<'PY'
import sys, re
root = sys.argv[1]
def setdep(rel, newdeps):
    p = f"{root}/{rel}/oh-package.json5"
    s = open(p).read()
    s = re.sub(r'"dependencies":\s*\{.*?\}', '"dependencies":{' + newdeps + '}', s, flags=re.S)
    open(p, "w").write(s)
setdep(".",                       '"amphion_asr":"file:./_bundled/amphion_asr","amphion_police":"file:./_bundled/amphion_police"')
setdep("_bundled/amphion_asr",    '"sherpa_onnx":"file:../sherpa_onnx","libamphion_asr.so":"file:./src/main/cpp/types/libamphion_asr"')
setdep("_bundled/amphion_police", '"amphion_asr":"file:../amphion_asr"')
PY

# HAR 内容位于 package/ 下,打回 tgz
mkdir -p "$(dirname "$OUT")"
( cd "$WORK" && mv sc package && tar czf "$OUT" package )
echo "[DONE] 自包含 amphion_dingqiao.har -> $OUT ($(du -h "$OUT" | cut -f1))"
