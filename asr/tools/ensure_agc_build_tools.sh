#!/usr/bin/env bash
# Resolve or provision the pinned Meson/Ninja toolchain used by every AGC build entry point.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TOOLS_VENV="${AMPHION_AGC_TOOLS_VENV:-$REPO_ROOT/asr/native/audio-processing/.tools-venv}"
PYTHON="${PYTHON:-python3}"

MESON_CANDIDATE="$(command -v "${MESON:-meson}" 2>/dev/null || true)"
NINJA_CANDIDATE="$(command -v "${NINJA:-ninja}" 2>/dev/null || true)"
if [[ -n "$MESON_CANDIDATE" && -n "$NINJA_CANDIDATE" ]] && \
    [[ "$($MESON_CANDIDATE --version)" == "1.7.0" ]] && \
    [[ "$($NINJA_CANDIDATE --version)" == 1.11.1* ]]; then
  MESON="$MESON_CANDIDATE"
  NINJA="$NINJA_CANDIDATE"
else
  VENV_MESON_VERSION="$([[ -x "$TOOLS_VENV/bin/meson" ]] && "$TOOLS_VENV/bin/meson" --version || true)"
  VENV_NINJA_VERSION="$([[ -x "$TOOLS_VENV/bin/ninja" ]] && "$TOOLS_VENV/bin/ninja" --version || true)"
  if [[ "$VENV_MESON_VERSION" != "1.7.0" || "$VENV_NINJA_VERSION" != 1.11.1* ]]; then
    echo "[INFO] provisioning or repairing pinned AGC build tools in $TOOLS_VENV" >&2
    "$PYTHON" -m venv "$TOOLS_VENV"
    "$TOOLS_VENV/bin/python" -m pip install \
      --disable-pip-version-check \
      --upgrade \
      --force-reinstall \
      "meson==1.7.0" \
      "ninja==1.11.1.4"
  fi
  MESON="$TOOLS_VENV/bin/meson"
  NINJA="$TOOLS_VENV/bin/ninja"
fi

[[ "$($MESON --version)" == "1.7.0" ]] || {
  echo "[ERROR] AGC requires Meson 1.7.0; resolved $MESON ($($MESON --version))" >&2
  exit 1
}
[[ "$($NINJA --version)" == 1.11.1* ]] || {
  echo "[ERROR] AGC requires Ninja 1.11.1.x; resolved $NINJA ($($NINJA --version))" >&2
  exit 1
}

export MESON NINJA
export PATH="$(dirname "$NINJA"):$PATH"
