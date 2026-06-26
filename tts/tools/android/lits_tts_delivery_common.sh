#!/usr/bin/env bash
# Shared helpers for Lits TTS Android delivery packaging.

lits_tts_repo_root_from_script() {
  local script_dir
  script_dir="$(cd "$(dirname "${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}")" && pwd)"
  local repo_root
  repo_root="$(cd "$script_dir/../../.." && pwd)"
  if ! git -C "$repo_root" rev-parse --show-toplevel >/dev/null 2>&1; then
    echo "[ERROR] TTS git root not found at $repo_root" >&2
    exit 1
  fi
  git -C "$repo_root" rev-parse --show-toplevel
}

lits_tts_android_root_from_repo() {
  local repo_root="$1"
  printf '%s/tts/android\n' "$repo_root"
}

lits_tts_default_model_dir() {
  local repo_root="$1"
  printf '%s/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0\n' "$repo_root"
}

lits_tts_default_version() {
  printf '0.1.0\n'
}

lits_tts_resolve_delivery_version() {
  local arg_version="${1:-}"
  if [[ -n "$arg_version" ]]; then
    printf '%s\n' "$arg_version"
  elif [[ -n "${LITS_TTS_DELIVERY_VERSION:-}" ]]; then
    printf '%s\n' "$LITS_TTS_DELIVERY_VERSION"
  else
    lits_tts_default_version
  fi
}

lits_tts_collect_git_provenance() {
  local repo_root="$1"
  (
    cd "$repo_root"
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

lits_tts_load_git_provenance() {
  local repo_root="$1"
  eval "$(lits_tts_collect_git_provenance "$repo_root")"
}

lits_tts_assert_reproducible_build() {
  if [[ "${LITS_TTS_ALLOW_DIRTY:-}" == "1" ]]; then
    return 0
  fi
  if [[ "${GIT_DIRTY:-false}" == "true" ]]; then
    echo "[ERROR] working tree is dirty. Commit before official delivery pack." >&2
    echo "        Local preview: LITS_TTS_ALLOW_DIRTY=1 bash tts/tools/android/pack_lits_tts_android_delivery.sh" >&2
    exit 1
  fi
}

lits_tts_assert_model_dir() {
  local model_dir="$1"
  local required=(
    manifest.json
    export_report.json
    external_loop_export_report.json
    frontend_golden.json
    frontend_rules.json
    chinese_lexicon.txt
    chinese_lexicon.bin
    cmudict.txt
    cmudict.bin
    pinyin_2_bpmf.txt
    polychar.txt
    zh_en_symbols.json
    pinyin_to_tokens.json
    arpabet_to_tokens.json
    lits_hidden_encoder.onnx
    lits_stream_condition_chunk.onnx
    lits_stream_condition_final.onnx
    lits_stream_decoder_step.onnx
    vocos_vocoder.onnx
  )
  [[ -d "$model_dir" ]] || {
    echo "[ERROR] model dir not found: $model_dir" >&2
    exit 1
  }
  local file
  for file in "${required[@]}"; do
    [[ -f "$model_dir/$file" ]] || {
      echo "[ERROR] missing model package file: $model_dir/$file" >&2
      exit 1
    }
  done
}

lits_tts_write_version_txt() {
  local out_file="$1"
  local package_id="$2"
  local delivery_version="$3"
  shift 3
  {
    printf '%s\n' \
      "package=$package_id" \
      "delivery_version=$delivery_version" \
      "sdk_version=$delivery_version" \
      "git_commit=$GIT_COMMIT_SHORT" \
      "git_commit_full=$GIT_COMMIT_FULL" \
      "git_branch=$GIT_BRANCH" \
      "git_dirty=$GIT_DIRTY" \
      "git_remote=$GIT_REMOTE" \
      "build_date=${BUILD_DATE:-$(date +%Y%m%d)}"
    local kv
    for kv in "$@"; do
      [[ -n "$kv" ]] && printf '%s\n' "$kv"
    done
  } > "$out_file"
}

lits_tts_stage_android_source() {
  local out_src="$1"
  local repo_root="$2"
  local model_dir="$3"
  rm -rf "$out_src"
  mkdir -p "$out_src"
  python3 - "$repo_root" "$out_src" <<'PY'
import shutil
import subprocess
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
out = Path(sys.argv[2]).resolve()
include_paths = [
    ".gitignore",
    "tts/android",
    "tts/tools/README.md",
    "tts/tools/verify_lits_delivery_16k_package.py",
    "tts/tools/verify_transsion_vocos24k_package.py",
    "tts/tools/license",
    "tts/tools/trial-export",
    "tts/tools/android",
]
raw = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z", "--", *include_paths])
for item in raw.split(b"\0"):
    if not item:
        continue
    rel = item.decode("utf-8")
    src = repo / rel
    dst = out / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_symlink():
        target = src.readlink()
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(target)
    else:
        shutil.copy2(src, dst)

if __import__("os").environ.get("LITS_TTS_ALLOW_DIRTY") == "1":
    dirty_roots = [
        repo / "tts" / "android",
        repo / "tts" / "tools",
    ]
    for root_path in dirty_roots:
        if not root_path.exists():
            continue
        for extra in sorted(root_path.rglob("*")):
            rel = extra.relative_to(repo)
            rel_posix = rel.as_posix()
            parts = set(rel.parts)
            if "build" in parts or ".gradle" in parts:
                continue
            if extra.name == "local.properties":
                continue
            if rel_posix.startswith("tts/android/sdk/src/main/assets/"):
                continue
            if rel_posix.startswith("tts/tools/trial-export/lits_delivery_16k_hifigan/1.0.0/") and extra.name != ".gitkeep":
                continue
            if extra.is_dir():
                (out / rel).mkdir(parents=True, exist_ok=True)
                continue
            dst = out / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(extra, dst)
PY
  local source_model_dir="$out_src/tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0"
  rm -rf "$source_model_dir"
  mkdir -p "$source_model_dir"
  python3 - "$model_dir" "$source_model_dir" <<'PY'
import shutil
import sys
from pathlib import Path

src = Path(sys.argv[1]).resolve()
dst = Path(sys.argv[2]).resolve()
for item in src.iterdir():
    if item.name in {".DS_Store", "__pycache__"}:
        continue
    target = dst / item.name
    if item.is_dir():
        shutil.copytree(item, target, dirs_exist_ok=True)
    else:
        shutil.copy2(item, target)
PY
  cat > "$out_src/README_ANDROID_SOURCE.txt" <<'EOF'
Lits TTS Android SDK source tree
================================

This source snapshot is staged from git-tracked files plus the model package
used to build the AAR in this delivery package.

Build:
  cd tts/android
  python ../../tts/tools/verify_transsion_vocos24k_package.py --model-dir ../../tools/trial-export/transsion_lits_en_zh_vocos24k_streaming_proto/0.1.0
  ./gradlew :sdk:testDebugUnitTest
  ./gradlew :sdk:assembleRelease

Do not edit tts/android/sdk/src/main/assets directly. Gradle copies
the model package from tools/trial-export into Android assets during preBuild.
EOF
}

lits_tts_zip_delivery() {
  local source_dir="$1"
  local dest_zip="$2"
  python3 - "$source_dir" "$dest_zip" <<'PY'
import sys
import zipfile
from pathlib import Path

source = Path(sys.argv[1]).resolve()
dest = Path(sys.argv[2]).resolve()
dest.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
    for path in sorted(source.rglob("*")):
        if path.is_dir():
            continue
        arcname = source.name / path.relative_to(source)
        zf.write(path, arcname.as_posix())
PY
}
