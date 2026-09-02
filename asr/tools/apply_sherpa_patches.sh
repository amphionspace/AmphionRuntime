#!/usr/bin/env bash
# Apply Amphion patches on top of upstream sherpa-onnx v1.13.1.
#
# Why patches instead of a fork submodule SHA:
#   Our JNI additions (TextRewriteFst, WetextItn) are not on k2-fsa/sherpa-onnx.
#   Pinning a local-only commit breaks `git submodule update` for the whole team.
#   Patches live in third_party/patches/sherpa-amphion/ and ship with amphion-runtime.
#
# This low-level command only accepts an explicit derived checkout. Normal
# builds must call prepare_sherpa_source.sh, which creates that checkout from
# the superproject's pinned gitlink without mutating the canonical submodule.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CANONICAL_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
SHERPA_ROOT="${AMPHION_SHERPA_ROOT:-}"
PATCH_DIR="${AMPHION_PATCH_DIR:-$REPO_ROOT/third_party/patches/sherpa-amphion}"
BASE_COMMIT="${AMPHION_SHERPA_BASE_COMMIT:-$(git -C "$REPO_ROOT" rev-parse :third_party/sherpa-onnx)}"
MARKER_FILE="$SHERPA_ROOT/.amphion-patches-applied"

if [[ -z "$SHERPA_ROOT" ]]; then
  echo "[ERROR] AMPHION_SHERPA_ROOT is required; run prepare_sherpa_source.sh" >&2
  exit 1
fi

canonical_real="$(cd "$CANONICAL_ROOT" && pwd -P)"
sherpa_real="$(cd "$SHERPA_ROOT" 2>/dev/null && pwd -P || true)"
if [[ -n "$sherpa_real" && "$sherpa_real" == "$canonical_real" ]]; then
  echo "[ERROR] refusing to patch the canonical sherpa-onnx submodule: $CANONICAL_ROOT" >&2
  exit 1
fi

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
if command -v shasum >/dev/null 2>&1; then
  PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | shasum -a 256 | awk '{print $1}')"
else
  PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | sha256sum | awk '{print $1}')"
fi
if [[ -f "$MARKER_FILE" ]] && [[ "$(cat "$MARKER_FILE")" == "$PATCH_SIG" ]]; then
  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo "[ERROR] derived sherpa checkout has tracked modifications: $SHERPA_ROOT" >&2
    exit 1
  fi
  echo "[SKIP] sherpa-amphion patches already applied ($PATCH_SIG)"
  exit 0
fi

actual_commit="$(git rev-parse HEAD)"
if [[ "$actual_commit" != "$BASE_COMMIT" ]]; then
  echo "[ERROR] derived sherpa checkout is not at pinned base" >&2
  echo "        expected: $BASE_COMMIT" >&2
  echo "        actual:   $actual_commit" >&2
  exit 1
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "[ERROR] derived sherpa checkout is dirty; refusing to overwrite it: $SHERPA_ROOT" >&2
  exit 1
fi

echo "[INFO] applying $(ls "$PATCH_DIR"/*.patch | wc -l | tr -d ' ') patch(es) from $PATCH_DIR ..."
GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Amphion CI}" \
GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-ci@amphion.local}" \
  git am --3way --committer-date-is-author-date "$PATCH_DIR"/*.patch

echo "$PATCH_SIG" > "$MARKER_FILE"
echo "[OK] sherpa-onnx patched at $(git rev-parse --short HEAD) (base ${BASE_COMMIT:0:12} + amphion patches)"
