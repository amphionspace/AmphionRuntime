#!/usr/bin/env bash
# Apply Amphion patches on top of upstream sherpa-onnx v1.13.1.
#
# Why patches instead of a fork submodule SHA:
#   Our JNI additions (TextRewriteFst, WetextItn) are not on k2-fsa/sherpa-onnx.
#   Pinning a local-only commit breaks `git submodule update` for the whole team.
#   Patches live in third_party/patches/sherpa-amphion/ and ship with amphion-runtime.
#
# Usage (from repo root):
#   bash asr/tools/apply_sherpa_patches.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
PATCH_DIR="$REPO_ROOT/third_party/patches/sherpa-amphion"
UPSTREAM_TAG="v1.13.1"
MARKER_FILE="$SHERPA_ROOT/.amphion-patches-applied"

# .git is a gitfile (not a dir) in submodule layout, so test existence not dir-ness.
if [[ ! -e "$SHERPA_ROOT/.git" ]]; then
  echo "[ERROR] $SHERPA_ROOT is not a git checkout; run: git submodule update --init third_party/sherpa-onnx"
  exit 1
fi

if [[ ! -d "$PATCH_DIR" ]] || [[ -z "$(ls -A "$PATCH_DIR"/*.patch 2>/dev/null || true)" ]]; then
  echo "[ERROR] no patches under $PATCH_DIR"
  exit 1
fi

cd "$SHERPA_ROOT"

# Idempotent: skip if marker matches current patch series.
PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | shasum -a 256 | awk '{print $1}')"
if [[ -f "$MARKER_FILE" ]] && [[ "$(cat "$MARKER_FILE")" == "$PATCH_SIG" ]]; then
  echo "[SKIP] sherpa-amphion patches already applied ($PATCH_SIG)"
  exit 0
fi

echo "[INFO] reset sherpa-onnx to upstream $UPSTREAM_TAG before applying patches ..."
git fetch --tags origin 2>/dev/null || true
git checkout "$UPSTREAM_TAG"

# Drop prior Amphion patch commits if re-running on a dirty tree.
if git rev-parse --verify refs/tags/"$UPSTREAM_TAG" >/dev/null 2>&1; then
  git reset --hard "$UPSTREAM_TAG"
fi

# `reset --hard` does not remove files introduced by an earlier patch application when that
# application was later reset to the upstream tag. Remove only the patch-owned collision; never
# use a broad `git clean`, because the submodule may also contain unrelated local build inputs.
PATCH_OWNED_NEW_FILES=(
  "harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/online-stream-handle.h"
)
for path in "${PATCH_OWNED_NEW_FILES[@]}"; do
  if [[ -e "$path" ]] && ! git ls-files --error-unmatch -- "$path" >/dev/null 2>&1; then
    rm -f -- "$path"
  fi
done

echo "[INFO] applying $(ls "$PATCH_DIR"/*.patch | wc -l | tr -d ' ') patch(es) from $PATCH_DIR ..."
GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Amphion CI}" \
GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-ci@amphion.local}" \
  git am --3way "$PATCH_DIR"/*.patch

echo "$PATCH_SIG" > "$MARKER_FILE"
echo "[OK] sherpa-onnx patched at $(git rev-parse --short HEAD) (base $UPSTREAM_TAG + amphion patches)"
