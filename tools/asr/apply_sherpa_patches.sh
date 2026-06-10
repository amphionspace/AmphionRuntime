#!/usr/bin/env bash
# Apply Amphion patches on top of upstream sherpa-onnx v1.13.1.
#
# Why patches instead of a fork submodule SHA:
#   Our JNI additions (TextRewriteFst, WetextItn) are not on k2-fsa/sherpa-onnx.
#   Pinning a local-only commit breaks `git submodule update` for the whole team.
#   Patches live in third_party/patches/sherpa-amphion/ and ship with amphion-runtime.
#
# Usage (from repo root):
#   bash tools/asr/apply_sherpa_patches.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SHERPA_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
PATCH_DIR="$REPO_ROOT/third_party/patches/sherpa-amphion"
UPSTREAM_TAG="v1.13.1"
MARKER_FILE="$SHERPA_ROOT/.amphion-patches-applied"

if [[ ! -d "$SHERPA_ROOT/.git" ]]; then
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

echo "[INFO] applying $(ls "$PATCH_DIR"/*.patch | wc -l | tr -d ' ') patch(es) from $PATCH_DIR ..."
git am --3way "$PATCH_DIR"/*.patch

echo "$PATCH_SIG" > "$MARKER_FILE"
echo "[OK] sherpa-onnx patched at $(git rev-parse --short HEAD) (base $UPSTREAM_TAG + amphion patches)"
