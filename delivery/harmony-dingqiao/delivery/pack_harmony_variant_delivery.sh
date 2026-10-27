#!/usr/bin/env bash
# 打包 HarmonyOS「变体」交付包：换 ASR 模型、可选裁掉警务后处理、独立 bundleName。
#
# 为什么独立成一条链路：既有打包脚本把基线的模型身份、完整警务资产、版本号序列都
# 写死为不变量，那些断言对基线是对的。变体若去放宽它们，等于让基线从此不再断言
# 自己的身份。所以变体自带工作区、自带校验，既有链路一行不改 —— 打基线包或其他
# 系统的包，走的代码路径与 main 完全相同。
#
# 产出（完整三件套 + 诊断子包）：
#   release-sdk/       自包含 amphion_dingqiao.har + 客户文档
#   diagnostics-sdk/   四个 diagnostics HAR + 采集工具
#   diagnostics-demo/  签名 demo HAP
#   demo-source/       demo 源码（git archive，按提交固定）
#   docs/              变体说明、溯源、校验清单、API 23 兼容报告
#
# 用法：
#   AMPHION_VARIANT_NAME=chuan-179m-tsx-v1 \
#   AMPHION_VARIANT_MODEL_DIR=<含 encoder.int8.onnx 等的模型目录> \
#   AMPHION_VARIANT_MODEL_POLICY=<该模型的固定 MD5 策略 json> \
#   HARMONY_API23_ES2ABC=<API 23 es2abc> \
#   HARMONY_SIGNING_CONFIG=<签名配置 json> \
#     bash delivery/harmony-dingqiao/delivery/pack_harmony_variant_delivery.sh [输出目录]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
PROJECT_REL="delivery/harmony-dingqiao"
source "$REPO_ROOT/asr/tools/harmony_env.sh"

VARIANT_NAME="${AMPHION_VARIANT_NAME:-}"
MODEL_DIR="${AMPHION_VARIANT_MODEL_DIR:-}"
MODEL_POLICY="${AMPHION_VARIANT_MODEL_POLICY:-}"
POLICE_POSTPROCESS="${AMPHION_VARIANT_POLICE_POSTPROCESS:-off}"
BUNDLE="${AMPHION_VARIANT_BUNDLE_NAME:-com.amphion.asr.harmony.repro}"
APP_LABEL="${AMPHION_VARIANT_APP_LABEL:-}"
SIGNING_CONFIG="${HARMONY_SIGNING_CONFIG:-}"
ES2ABC="${HARMONY_API23_ES2ABC:-}"
PYTHON="${LICENSE_PYTHON:-python3}"
BUILD_DATE="${AMPHION_BUILD_DATE:-$(date +%Y%m%d)}"

PREPARE_ONLY=false
KEEP_WORKSPACE="${AMPHION_VARIANT_KEEP_WORKSPACE:-false}"
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) sed -n '2,25p' "${BASH_SOURCE[0]}"; exit 0 ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --keep-workspace) KEEP_WORKSPACE=true; shift ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}

require() {
  local value="$1" name="$2"
  [[ -n "$value" ]] || { echo "[ERROR] 必须设置 $name" >&2; exit 1; }
}
require "$VARIANT_NAME" AMPHION_VARIANT_NAME
require "$MODEL_DIR" AMPHION_VARIANT_MODEL_DIR
require "$MODEL_POLICY" AMPHION_VARIANT_MODEL_POLICY
require "$SIGNING_CONFIG" HARMONY_SIGNING_CONFIG
require "$ES2ABC" HARMONY_API23_ES2ABC
[[ -d "$MODEL_DIR" ]] || { echo "[ERROR] 模型目录不存在: $MODEL_DIR" >&2; exit 1; }
[[ -s "$MODEL_POLICY" ]] || { echo "[ERROR] 模型策略不存在: $MODEL_POLICY" >&2; exit 1; }
[[ -s "$SIGNING_CONFIG" ]] || { echo "[ERROR] 签名配置不存在: $SIGNING_CONFIG" >&2; exit 1; }
[[ -x "$ES2ABC" ]] || { echo "[ERROR] es2abc 不可执行: $ES2ABC" >&2; exit 1; }
[[ "$POLICE_POSTPROCESS" == on || "$POLICE_POSTPROCESS" == off ]] || {
  echo "[ERROR] AMPHION_VARIANT_POLICE_POSTPROCESS 只接受 on 或 off" >&2; exit 1; }

PACKAGE_NAME="Amphion-Harmony-ASR-${VARIANT_NAME}-${BUILD_DATE}"
OUTPUT_ROOT="${1:-$REPO_ROOT/$PROJECT_REL/build/variant-$VARIANT_NAME-$BUILD_DATE}"
[[ "$OUTPUT_ROOT" = /* ]] || OUTPUT_ROOT="$PWD/$OUTPUT_ROOT"

# 变体交付按提交固定：产物必须能对应到仓库的某一个提交。
SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
DIRTY_INPUTS=(LICENSE asr/harmony shared/models/asr third_party/sherpa-onnx \
  third_party/patches/sherpa-amphion "$PROJECT_REL/AppScope" \
  "$PROJECT_REL/samples/dingqiao-demo" "$PROJECT_REL/delivery" "$PROJECT_REL/docs")
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain -- "${DIRTY_INPUTS[@]}")" ]]; then
  echo "[ERROR] 交付输入有未提交改动；提交或暂存后再出包" >&2
  git -C "$REPO_ROOT" status --porcelain -- "${DIRTY_INPUTS[@]}" >&2
  exit 1
fi

WORKSPACE=""
STAGING=""
cleanup() {
  if [[ "$KEEP_WORKSPACE" == true && -n "$WORKSPACE" ]]; then
    echo "[INFO] 保留工作区待排查: $WORKSPACE" >&2
  else
    [[ -z "$WORKSPACE" ]] || rm -rf "$WORKSPACE"
  fi
  [[ -z "$STAGING" ]] || rm -rf "$STAGING"
}
trap cleanup EXIT
trap 'cleanup; exit 130' INT TERM

info() { printf '\033[36m[INFO]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m   %s\n' "$*"; }

# ---------------------------------------------------------------- 隔离工作区
# 自带一份实现，不去改既有冒烟脚本 —— 共享那段代码正是污染既有链路的途径。
prepare_workspace() {
  command -v rsync >/dev/null || { echo "[ERROR] 需要 rsync" >&2; exit 1; }
  WORKSPACE="$(mktemp -d "${TMPDIR:-/tmp}/amphion-variant-build.XXXXXX")"
  local repo="$WORKSPACE/repo"

  # 工作区是仓库的本地克隆，而不是手搭的目录树：既有脚本（sherpa 源码物化、自包含
  # HAR 组装）都要读 git 索引（如 rev-parse :third_party/sherpa-onnx），手搭的树没有
  # git 就用不了它们，只能重写一份 —— 克隆让既有脚本在工作区里原样可用。
  info "克隆仓库到隔离工作区（按提交 ${SOURCE_COMMIT:0:8} 固定）"
  git clone --quiet --local --no-hardlinks "$REPO_ROOT" "$repo"
  git -C "$repo" checkout --quiet --detach "$SOURCE_COMMIT"
  # protocol.file.allow：git 2.38+ 默认禁用 submodule 的 file 传输（CVE-2022-39253
  # 缓解）。这里的来源是本机同一个仓库的 submodule 检出，只在这一条命令上放开。
  git -C "$repo" \
    -c protocol.file.allow=always \
    -c "submodule.third_party/sherpa-onnx.url=$REPO_ROOT/third_party/sherpa-onnx" \
    submodule update --quiet --init third_party/sherpa-onnx

  # 克隆只带被跟踪的文件；模型资产、原生库、license 等被 gitignore 的构建输入要补齐。
  mkdir -p "$repo/delivery"
  rsync -a --exclude='build/' --exclude='.hvigor/' --exclude='.idea/' \
    --exclude='oh_modules/' \
    "$REPO_ROOT/$PROJECT_REL/" "$repo/$PROJECT_REL/"
  for tree in asr/harmony/sdk asr/harmony/sdk-police asr/harmony/sdk-dingqiao \
      shared/models/asr asr/native/audio-processing/include; do
    mkdir -p "$repo/$(dirname "$tree")"
    rsync -a "$REPO_ROOT/$tree/" "$repo/$tree/"
  done
  mkdir -p "$repo/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime"
  rsync -a "$REPO_ROOT/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include/" \
    "$repo/tts/harmony/sdk/src/main/cpp/third_party/onnxruntime/include/"

  mkdir -p "$repo/$PROJECT_REL/hvigor"
  cat >"$repo/$PROJECT_REL/hvigor/hvigor-config.json5" <<'JSON'
{
  "modelVersion": "5.0.0",
  "dependencies": {},
  "execution": {},
  "logging": {},
  "debugging": {},
  "nodeOptions": {}
}
JSON
  find "$repo/asr/harmony" -type d \
    \( -name build -o -name .cxx -o -name .hvigor \) -prune -exec rm -rf {} +

  # 在克隆里物化打过补丁的 sherpa 源码，并补齐预编译原生库（被 gitignore）。
  info "在工作区物化打补丁的 sherpa 源码"
  local sherpa_dst sherpa_src
  sherpa_dst="$(bash "$repo/asr/tools/prepare_sherpa_source.sh")"
  sherpa_src="$(bash "$REPO_ROOT/asr/tools/prepare_sherpa_source.sh")"
  rsync -a "$sherpa_src/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/" \
    "$sherpa_dst/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/libs/"

  # prepare_sherpa_source.sh 产出的是 generation 目录 + sherpa-onnx 符号链接，而工程
  # build-profile 以 .derived/sherpa-onnx 固定引用该模块，hvigor 不跟随符号链接
  # （报 Path not found）。实体化成真实目录。
  local derived="$repo/third_party/.derived"
  if [[ -L "$derived/sherpa-onnx" ]]; then
    local generation
    generation="$(readlink "$derived/sherpa-onnx")"
    rm "$derived/sherpa-onnx"
    mv "$derived/$generation" "$derived/sherpa-onnx"
    sherpa_dst="$derived/sherpa-onnx"
  fi

  # node-addon-api：CMake 探不到 git 时（GIT_VERSION_STRING=''），直接指向已打补丁的本地源。
  if [[ -n "${NODE_ADDON_API_PREPATCHED:-}" && -d "$NODE_ADDON_API_PREPATCHED" ]]; then
    "$PYTHON" "$SCRIPT_DIR/point_fetchcontent_at_local_source.py" \
      --cmake "$sherpa_dst/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/CMakeLists.txt" \
      --source "$NODE_ADDON_API_PREPATCHED"
  fi
  # 工程的 build-profile 以固定路径引用 sherpa 模块，物化后必须能解析到。
  local expected="$repo/third_party/.derived/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx"
  if [[ ! -d "$expected" ]]; then
    echo "[ERROR] 工程引用的 sherpa 模块路径不存在: $expected" >&2
    echo "        prepare_sherpa_source.sh 返回: $sherpa_dst" >&2
    ls -la "$repo/third_party/.derived" >&2 || true
    exit 1
  fi
  WORKSPACE_REPO="$repo"
  WORKSPACE_SHERPA="$sherpa_dst"
  ok "隔离工作区就绪: $repo"
}

# ------------------------------------------------------------ 变体改写（仅工作区）
apply_variant() {
  local repo="$WORKSPACE_REPO"
  info "把变体模型转成 ORT 并装进工作区资产: $(basename "$MODEL_DIR")"
  # 调工作区副本：该脚本的输出目录由自身位置推导，这样资产只落在工作区，
  # 真实仓库的资产目录不被动过 —— 否则下一次基线出包会悄悄用上变体模型。
  ZH_EN_DIR="$MODEL_DIR" \
  PUNCT_DIR="${PUNCT_DIR:-$REPO_ROOT/asr/tools/punct-model/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8}" \
  ITN_DIR="${ITN_DIR:-$REPO_ROOT/asr/tools/weitn-fsts-v2}" \
  VAD_FILE="${VAD_FILE:-$REPO_ROOT/asr/tools/vad-model/silero_vad.onnx}" \
  HARMONY_ORT_VENV="${HARMONY_ORT_VENV:-$REPO_ROOT/.venv-harmony-ort-1.16.3}" \
  HARMONY_ORT_CACHE_DIR="${HARMONY_ORT_CACHE_DIR:-$REPO_ROOT/.cache/harmony-ort-1.16.3}" \
    bash "$repo/asr/tools/08_pack_harmony_assets.sh" --zh-en-only

  if [[ "$POLICE_POSTPROCESS" == off ]]; then
    "$PYTHON" "$SCRIPT_DIR/trim_police_postprocessing.py" --repo-root "$repo"
  fi
  "$PYTHON" "$SCRIPT_DIR/rebrand_demo_app.py" \
    --project "$repo/$PROJECT_REL" --repo-root "$repo" \
    --bundle-name "$BUNDLE" --label "$APP_LABEL"
}

# ------------------------------------------------------------------------ 构建
build_artifacts() {
  local project="$WORKSPACE_REPO/$PROJECT_REL"
  install_signing "$project"
  ( cd "$project"
    # 工作区不带被忽略的 oh_modules，构建前按工程清单重建，避免意外用上开发机的包。
    info "重建 oh_modules 依赖"
    "$OHPM" install --all >/dev/null
    for module in sherpa_onnx amphion_asr amphion_police amphion_dingqiao; do
      info "构建 $module (diagnostics)"
      "$NODE" "$HVIGOR" assembleHar --mode module \
        -p product=default -p module="${module}@default" -p buildMode=diagnostics \
        --no-daemon >/dev/null
    done
    info "构建签名 demo HAP (diagnostics)"
    "$NODE" "$HVIGOR" assembleHap --mode module \
      -p product=default -p module=amphion_asr_demo@default -p buildMode=diagnostics \
      --no-daemon >/dev/null
  )
  ok "四个 HAR 与签名 HAP 构建完成"
}

install_signing() {
  local project="$1" mode
  mode="$(stat -f '%Lp' "$SIGNING_CONFIG" 2>/dev/null || stat -c '%a' "$SIGNING_CONFIG")"
  [[ "$mode" == 600 || "$mode" == 400 ]] || {
    echo "[ERROR] 签名配置不得对组/他人可读: chmod 600 $SIGNING_CONFIG" >&2; exit 1; }
  "$PYTHON" "$SCRIPT_DIR/install_variant_signing.py" \
    --build-profile "$project/build-profile.json5" --signing-config "$SIGNING_CONFIG"
}

# ------------------------------------------------------------------------ 组包
assemble_package() {
  local repo="$WORKSPACE_REPO" project="$WORKSPACE_REPO/$PROJECT_REL"
  STAGING="$(mktemp -d "${TMPDIR:-/tmp}/amphion-variant-stage.XXXXXX")"
  local root="$STAGING/$PACKAGE_NAME"
  mkdir -p "$root"/{release-sdk/har,release-sdk/docs,diagnostics-sdk/sdk,diagnostics-sdk/tools,diagnostics-sdk/docs,diagnostics-demo,demo-source,docs}

  info "组装自包含 release HAR"
  bash "$repo/$PROJECT_REL/delivery/assemble_selfcontained_dingqiao_har.sh" \
    --zh-en-only "$root/release-sdk/har/amphion_dingqiao.har"

  for pair in "sdk:amphion_asr" "sdk-police:amphion_police" "sdk-dingqiao:amphion_dingqiao"; do
    local dir="${pair%%:*}" har="${pair##*:}"
    cp "$repo/asr/harmony/$dir/build/default/outputs/default/$har.har" \
      "$root/diagnostics-sdk/sdk/$har-diagnostics.har"
  done
  cp "$WORKSPACE_SHERPA/harmony-os/SherpaOnnxHar/sherpa_onnx/build/default/outputs/default/sherpa_onnx.har" \
    "$root/diagnostics-sdk/sdk/sherpa_onnx.har"
  cp "$SCRIPT_DIR/collect_asr_diagnostics.py" "$root/diagnostics-sdk/tools/"
  for doc in DIAGNOSTICS_GUIDE.md ISSUE_TEMPLATE.md PRIVACY_NOTICE.md; do
    cp "$REPO_ROOT/$PROJECT_REL/docs/diagnostics-sdk/$doc" "$root/diagnostics-sdk/docs/"
  done

  local hap="$project/samples/dingqiao-demo/entry/build/default/outputs/default/amphion_asr_demo-default-signed.hap"
  [[ -f "$hap" ]] || { echo "[ERROR] 签名 HAP 缺失: $hap" >&2; exit 1; }
  cp "$hap" "$root/diagnostics-demo/dingqiao-demo.hap"

  info "导出 demo 源码（按提交 ${SOURCE_COMMIT:0:8} 固定）"
  git -C "$REPO_ROOT" archive "$SOURCE_COMMIT" \
    "$PROJECT_REL/AppScope" "$PROJECT_REL/build-profile.json5" \
    "$PROJECT_REL/hvigorfile.ts" "$PROJECT_REL/oh-package.json5" \
    "$PROJECT_REL/samples/dingqiao-demo" \
    | tar -x -C "$root/demo-source" --strip-components=2
  mkdir -p "$root/demo-source/hvigor"
  cp "$repo/$PROJECT_REL/hvigor/hvigor-config.json5" "$root/demo-source/hvigor/"
  # 源码包只随附公共 HAR，变体身份也要在源码里成立。
  "$PYTHON" "$SCRIPT_DIR/rebrand_demo_app.py" \
    --project "$root/demo-source" --bundle-name "$BUNDLE" --label "$APP_LABEL"
  "$PYTHON" "$SCRIPT_DIR/prepare_variant_demo_source.py" \
    --demo-source "$root/demo-source"

  for doc in customer/DINGQIAO_ASR_INTEGRATION.md customer/DINGQIAO_ASR_LICENSE_SCHEME.md \
      customer/ASR_TROUBLESHOOTING.md PRIVACY.md 语音识别SDK接口.md; do
    cp "$REPO_ROOT/$PROJECT_REL/docs/$doc" "$root/release-sdk/docs/"
  done
  PACKAGE_ROOT="$root"
}

# ------------------------------------------------------------------------ 校验
verify_package() {
  local root="$PACKAGE_ROOT"
  info "变体专属校验（模型身份 / 警务资产裁剪态 / 包身份）"
  local verify_args=(--policy "$MODEL_POLICY"
    --police-source "$REPO_ROOT/asr/harmony/sdk-police/src/main/resources/rawfile/amphion-police"
    --har "$root/release-sdk/har/amphion_dingqiao.har"
    --hap "$root/diagnostics-demo/dingqiao-demo.hap"
    --expect-bundle "$BUNDLE"
    --report "$root/docs/VARIANT_VERIFY.json")
  [[ -z "$APP_LABEL" ]] || verify_args+=(--expect-label "$APP_LABEL")
  [[ "$POLICE_POSTPROCESS" == on ]] && verify_args+=(--skip-police-trim) || true
  "$PYTHON" "$SCRIPT_DIR/verify_variant_delivery.py" "${verify_args[@]}"

  info "复用既有校验：打包模型资产"
  "$PYTHON" "$REPO_ROOT/asr/tools/verify_packed_model_assets.py" \
    --archive "$root/diagnostics-demo/dingqiao-demo.hap" --zh-en-only

  info "复用既有校验：API 23 编译器兼容性"
  "$PYTHON" "$SCRIPT_DIR/verify_harmony_api23_compiler.py" \
    --har "$root/release-sdk/har/amphion_dingqiao.har" --es2abc "$ES2ABC" \
    --report "$root/docs/API23_COMPILER_COMPATIBILITY.json"

  info "复用既有校验：交付脱敏"
  "$PYTHON" "$SCRIPT_DIR/check_customer_delivery_redaction.py" \
    "$root/release-sdk/docs" "$root/release-sdk/har/amphion_dingqiao.har"
}

write_provenance() {
  local root="$PACKAGE_ROOT"
  "$PYTHON" "$SCRIPT_DIR/write_variant_provenance.py" \
    --package-root "$root" --repo-root "$REPO_ROOT" \
    --variant "$VARIANT_NAME" --policy "$MODEL_POLICY" \
    --bundle-name "$BUNDLE" --label "$APP_LABEL" \
    --police-postprocess "$POLICE_POSTPROCESS" \
    --source-commit "$SOURCE_COMMIT" --build-date "$BUILD_DATE"
  ( cd "$root" && find . -type f ! -name checksums.txt -print0 | sort -z \
      | xargs -0 shasum -a 256 > checksums.txt )
  ok "溯源与校验清单已写入"
}

publish() {
  mkdir -p "$OUTPUT_ROOT"
  local final="$OUTPUT_ROOT/$PACKAGE_NAME"
  rm -rf "$final"
  mv "$PACKAGE_ROOT" "$final"
  "$PYTHON" "$REPO_ROOT/asr/tools/delivery/dingqiao_zip_utf8.py" \
    create "$final" "$final.zip"
  ( cd "$OUTPUT_ROOT" && shasum -a 256 "$PACKAGE_NAME.zip" > "$PACKAGE_NAME.zip.sha256" )
  ok "$final.zip"
}

prepare_workspace
if [[ "$PREPARE_ONLY" == true ]]; then
  echo "[DONE] 隔离工作区准备完成（--prepare-only）"
  exit 0
fi
apply_variant
build_artifacts
assemble_package
verify_package
write_provenance
publish
echo "[DONE] $OUTPUT_ROOT/$PACKAGE_NAME.zip"
