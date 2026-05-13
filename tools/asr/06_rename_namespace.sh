#!/usr/bin/env bash
# 一键把 SDK 工程内 com.amphion / com.amphion.asr 命名空间换成下游 fork 自己的坐标。
# 仅用于 fork 出去自用的团队；上游仓库本身的默认坐标就是 com.amphion / com.amphion.asr。
#
# 替换范围：
#   - android/AmphionRuntime/gradle.properties    AMPHION_RUNTIME_GROUP_ID 行
#   - android/AmphionRuntime/{sdk,sample}/**.kt   import / package
#   - android/AmphionRuntime/**/AndroidManifest.xml
#   - android/AmphionRuntime/**/build.gradle.kts  namespace / applicationId
#   - android/AmphionRuntime/sdk/**.pro           consumer-rules / proguard-rules
#   - android/AmphionRuntime/sample/**.pro
#   - 物理目录：sdk/src/main/java/com/amphion/asr -> sdk/src/main/java/<new-pkg-path>
#   - 同上 sample
#
# 不动的（需要手工确认）：
#   - LICENSE / NOTICE / docs/PRIVACY.md 中的 "Amphion" 公司/品牌名
#   - tools/asr/*.sh / *.md 中 SAMPLE_PKG=com.amphion.asr.sample（需要先决定 sample applicationId 是否还叫 sample）
#
# 用法：
#   bash tools/asr/06_rename_namespace.sh --group-id com.example
#   bash tools/asr/06_rename_namespace.sh --group-id com.example --pkg-prefix com.example.asr
#   bash tools/asr/06_rename_namespace.sh --group-id com.example --dry-run
#
# 选项：
#   --group-id <id>      必填，新的 GroupId（gradle 坐标的 group），如 com.example
#   --pkg-prefix <pkg>   可选，Kotlin 包前缀，默认 = <group-id>.asr，如 com.example.asr
#   --dry-run            只打印将要执行的命令，不实际修改文件
#   --skip-backup        默认会在 .rename-backup-<ts>/ 下保留原文件，开此选项跳过备份
#   --root <path>        可选，工程根目录，默认 = $(git rev-parse --show-toplevel)
#
# 退出码：
#   0   全部成功
#   1   参数错误
#   2   工程结构异常 / 必备文件缺失
#   3   sed/mv 中途失败

set -euo pipefail

# ---------- 参数解析 ----------
GROUP_ID=""
PKG_PREFIX=""
DRY_RUN=0
SKIP_BACKUP=0
ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --group-id)   GROUP_ID="$2"; shift 2;;
    --pkg-prefix) PKG_PREFIX="$2"; shift 2;;
    --dry-run)    DRY_RUN=1; shift;;
    --skip-backup) SKIP_BACKUP=1; shift;;
    --root)       ROOT="$2"; shift 2;;
    -h|--help)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *) echo "[ERROR] 未知参数：$1" >&2; exit 1;;
  esac
done

if [[ -z "$GROUP_ID" ]]; then
  echo "[ERROR] 必须传 --group-id <com.target-org>，例如 --group-id com.example" >&2
  exit 1
fi
if [[ -z "$PKG_PREFIX" ]]; then
  PKG_PREFIX="${GROUP_ID}.asr"
fi
if [[ -z "$ROOT" ]]; then
  ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [[ -z "$ROOT" || ! -d "$ROOT" ]]; then
  echo "[ERROR] 找不到工程根目录，请用 --root 指定" >&2
  exit 1
fi

SDK_ROOT="$ROOT/android/AmphionRuntime"
if [[ ! -d "$SDK_ROOT" || ! -f "$SDK_ROOT/gradle.properties" ]]; then
  echo "[ERROR] 期望 $SDK_ROOT 是 AmphionRuntime 工程根目录" >&2
  exit 2
fi

# 校验 GROUP_ID / PKG_PREFIX 形态：必须是合法 Java 包名（小写字母、数字、下划线、点）
if ! echo "$GROUP_ID" | grep -Eq '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$'; then
  echo "[ERROR] --group-id 必须是合法包名（全小写、用 . 分隔、首段以字母开头）：$GROUP_ID" >&2
  exit 1
fi
if ! echo "$PKG_PREFIX" | grep -Eq '^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$'; then
  echo "[ERROR] --pkg-prefix 必须是合法包名：$PKG_PREFIX" >&2
  exit 1
fi

# 防呆：拒绝把 group-id / pkg-prefix 设回上游默认 com.amphion
if [[ "$GROUP_ID" == "com.amphion" || "$PKG_PREFIX" == "com.amphion.asr" ]]; then
  echo "[ERROR] 新坐标与上游默认相同，没必要执行" >&2
  exit 1
fi

# ---------- sed -i 兼容（macOS BSD vs GNU） ----------
SED_INPLACE=()
if sed --version >/dev/null 2>&1; then
  SED_INPLACE=(sed -i)
else
  SED_INPLACE=(sed -i '')
fi

# ---------- 备份 ----------
BACKUP_DIR=""
if [[ $SKIP_BACKUP -eq 0 && $DRY_RUN -eq 0 ]]; then
  BACKUP_DIR="$SDK_ROOT/.rename-backup-$(date +%Y%m%d-%H%M%S)"
  echo "[INFO] 备份目录：$BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"
fi

backup_file() {
  [[ $SKIP_BACKUP -eq 1 || $DRY_RUN -eq 1 ]] && return 0
  local src="$1"
  local rel="${src#$SDK_ROOT/}"
  local dst="$BACKUP_DIR/$rel"
  mkdir -p "$(dirname "$dst")"
  cp -p "$src" "$dst"
}

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf '[DRY] %s\n' "$*"
  else
    eval "$@"
  fi
}

echo "[INFO] 工程根       : $ROOT"
echo "[INFO] SDK 根目录    : $SDK_ROOT"
echo "[INFO] new GROUP_ID  : $GROUP_ID"
echo "[INFO] new PKG_PREFIX: $PKG_PREFIX"
echo "[INFO] dry-run       : $DRY_RUN"
echo "[INFO] skip-backup   : $SKIP_BACKUP"
echo

# ---------- 1) gradle.properties ----------
echo "[STEP] 1/5 修改 gradle.properties 中的 AMPHION_RUNTIME_GROUP_ID"
PROP="$SDK_ROOT/gradle.properties"
if grep -q "^AMPHION_RUNTIME_GROUP_ID=" "$PROP"; then
  backup_file "$PROP"
  run "${SED_INPLACE[@]} \"s|^AMPHION_RUNTIME_GROUP_ID=.*|AMPHION_RUNTIME_GROUP_ID=$GROUP_ID|\" \"$PROP\""
else
  echo "[WARN] $PROP 中没有 AMPHION_RUNTIME_GROUP_ID 行，跳过"
fi

# ---------- 2) Kotlin 文件中所有 com.amphion.asr -> $PKG_PREFIX ----------
echo "[STEP] 2/5 改写 Kotlin / Manifest / Gradle / ProGuard 中的字面量 com.amphion.asr"
# 用 find prune 把 build / .gradle / .idea / 备份目录排除掉，避免动到中间产物
KT_FILES=()
while IFS= read -r f; do
  [[ -n "$f" ]] && grep -q 'com\.amphion' "$f" 2>/dev/null && KT_FILES+=("$f")
done < <(find "$SDK_ROOT" \
    \( -path '*/build' -o -path '*/.gradle' -o -path '*/.idea' -o -name '.rename-backup-*' \) -prune -o \
    -type f \( -name '*.kt' -o -name '*.kts' -o -name '*.xml' -o -name '*.pro' \) -print)

if [[ ${#KT_FILES[@]} -eq 0 ]]; then
  echo "[WARN] 没有找到任何包含 com.amphion 字面量的源码 / 配置文件"
fi
for f in "${KT_FILES[@]}"; do
  backup_file "$f"
  # 注意顺序：必须先替换更长的 com.amphion.asr 再替换 com.amphion，否则会被吃掉
  run "${SED_INPLACE[@]} \"s|com\\.amphion\\.asr|$PKG_PREFIX|g\" \"$f\""
  # 单独处理裸的 com.amphion（gradle.properties 里 GROUP_ID 用过；其它一般不出现）
  run "${SED_INPLACE[@]} \"s|com\\.amphion\\([^.]\\)|$GROUP_ID\\1|g\" \"$f\""
done

# ---------- 3) 移动物理目录 ----------
echo "[STEP] 3/5 移动 src/main/java 物理目录"
PKG_PATH="${PKG_PREFIX//./\/}"
move_pkg() {
  local module="$1"
  local src="$SDK_ROOT/$module/src/main/java/com/amphion/asr"
  local dst="$SDK_ROOT/$module/src/main/java/$PKG_PATH"
  if [[ ! -d "$src" ]]; then
    echo "[INFO] $src 不存在，跳过"
    return 0
  fi
  echo "[INFO] $module: $src -> $dst"
  if [[ -d "$dst" ]]; then
    echo "[ERROR] 目标已存在：$dst（脚本不允许覆盖，请人工合并后再跑）" >&2
    return 3
  fi
  run "mkdir -p \"$(dirname "$dst")\""
  run "mv \"$src\" \"$dst\""
}
move_pkg sdk
move_pkg sample

# ---------- 4) 清理空目录 ----------
echo "[STEP] 4/5 清理留下的空 com/amphion 目录"
for module in sdk sample; do
  base="$SDK_ROOT/$module/src/main/java"
  [[ -d "$base/com/amphion" ]] && run "find \"$base/com/amphion\" -type d -empty -delete"
  [[ -d "$base/com" ]] && run "find \"$base/com\" -type d -empty -delete"
done

# ---------- 5) 校验 ----------
echo "[STEP] 5/5 校验：grep 残留 com.amphion / 确认新包路径存在"
LEFT_OVER=$(find "$SDK_ROOT" \
    \( -path '*/build' -o -path '*/.gradle' -o -path '*/.idea' -o -name '.rename-backup-*' \) -prune -o \
    -type f \( -name '*.kt' -o -name '*.kts' -o -name '*.xml' -o -name '*.pro' \) -print | \
    xargs grep -l 'com\.amphion' 2>/dev/null || true)
if [[ -n "$LEFT_OVER" ]]; then
  echo "[WARN] 仍有残留 com.amphion 字面量："
  echo "$LEFT_OVER" | head -50
  echo "[WARN] 上面这些可能是注释 / 文档；脚本不动注释里的字面量。请人工确认"
fi

NEW_DIR_SDK="$SDK_ROOT/sdk/src/main/java/$PKG_PATH"
if [[ $DRY_RUN -eq 0 && ! -d "$NEW_DIR_SDK" ]]; then
  echo "[ERROR] 新包路径不存在：$NEW_DIR_SDK" >&2
  exit 3
fi

cat <<EOF

[DONE] 命名空间替换完成

下一步建议：

1. 进 SDK 工程目录验证编译：
     cd $SDK_ROOT
     ./gradlew :sdk:assembleRelease

2. 同步检查并人工修改下列地方（脚本不动它们）：
   - $SDK_ROOT/LICENSE / NOTICE / docs/PRIVACY.md：把 "Amphion" 替换成你公司全称
   - $ROOT/tools/asr/*.sh：SAMPLE_PKG / model_id 等业务标识是否需要同步换
   - app 集成文档中的 maven 坐标：$GROUP_ID:amphion-runtime:1.0.0

3. 如果备份目录已确认无误，可以删除：
     rm -rf $BACKUP_DIR

EOF
