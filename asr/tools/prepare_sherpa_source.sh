#!/usr/bin/env bash
# Materialize the pinned Amphion-patched sherpa source in an isolated checkout.
# The canonical third_party/sherpa-onnx submodule is read-only input.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CANONICAL_ROOT="$REPO_ROOT/third_party/sherpa-onnx"
PATCH_DIR="$REPO_ROOT/third_party/patches/sherpa-amphion"
DERIVED_PARENT="${AMPHION_SHERPA_DERIVED_PARENT:-$REPO_ROOT/third_party/.derived}"

[[ -e "$CANONICAL_ROOT/.git" ]] || {
  echo "[ERROR] canonical sherpa-onnx submodule is missing; run git submodule update --init third_party/sherpa-onnx" >&2
  exit 1
}

PINNED_COMMIT="$(git -C "$REPO_ROOT" rev-parse :third_party/sherpa-onnx)"
if command -v shasum >/dev/null 2>&1; then
  PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | shasum -a 256 | awk '{print $1}')"
else
  PATCH_SIG="$(cat "$PATCH_DIR"/*.patch | sha256sum | awk '{print $1}')"
fi
GENERATION="sherpa-onnx-${PINNED_COMMIT:0:12}-${PATCH_SIG:0:12}"
DESTINATION="$DERIVED_PARENT/$GENERATION"
CURRENT_LINK="$DERIVED_PARENT/sherpa-onnx"
IDENTITY="$PINNED_COMMIT:$PATCH_SIG"

validate_destination() {
  [[ -e "$DESTINATION/.git" ]] || return 1
  [[ -f "$DESTINATION/.amphion-source-identity" ]] || return 1
  [[ "$(cat "$DESTINATION/.amphion-source-identity")" == "$IDENTITY" ]] || return 1
  [[ -f "$DESTINATION/.amphion-patches-applied" ]] || return 1
  [[ "$(cat "$DESTINATION/.amphion-patches-applied")" == "$PATCH_SIG" ]] || return 1
  [[ -z "$(git -C "$DESTINATION" status --porcelain --untracked-files=no)" ]] || {
    echo "[ERROR] isolated sherpa source has tracked modifications: $DESTINATION" >&2
    return 1
  }
}

mkdir -p "$DERIVED_PARENT"
if [[ -e "$DESTINATION" ]] && ! validate_destination; then
  echo "[ERROR] existing isolated sherpa generation failed identity validation: $DESTINATION" >&2
  echo "        preserve or inspect it, then move it aside before rebuilding" >&2
  exit 1
fi

if [[ ! -e "$DESTINATION" ]]; then
  STAGE="$(mktemp -d "$DERIVED_PARENT/.sherpa-ready.XXXXXX")"
  cleanup() {
    [[ -z "${STAGE:-}" || ! -e "$STAGE" ]] || rm -rf "$STAGE"
  }
  trap cleanup EXIT
  echo "[source] Creating isolated sherpa source $GENERATION" >&2
  git clone --quiet --no-hardlinks --no-checkout "$CANONICAL_ROOT" "$STAGE"
  git -C "$STAGE" checkout --quiet --detach "$PINNED_COMMIT"
  AMPHION_SHERPA_ROOT="$STAGE" \
  AMPHION_SHERPA_BASE_COMMIT="$PINNED_COMMIT" \
  AMPHION_PATCH_DIR="$PATCH_DIR" \
    bash "$SCRIPT_DIR/apply_sherpa_patches.sh" >&2
  printf '%s\n' "$IDENTITY" > "$STAGE/.amphion-source-identity"
  mv "$STAGE" "$DESTINATION"
  STAGE=""
fi

ln -sfn "$GENERATION" "$CURRENT_LINK"
printf '%s\n' "$CURRENT_LINK"
