#!/usr/bin/env bash
# Merge ar-en filelists into no- / partial- / full-diacritics training rows.
#
# Usage:
#   ./data/filelists/merge_ar_diacritics.sh <no_diac.txt> <with_diac.txt> <output.txt>
#
# Example:
#   ./data/filelists/merge_ar_diacritics.sh \
#     data/filelists/train_no_diac.txt \
#     data/filelists/train_with_diac.txt \
#     data/filelists/train_mixed.txt
#
# Environment:
#   RATIO_PARTIAL=0.15   # extra partial-diac lines (homograph-prioritized)
#   RATIO_FULL=0.05      # extra full-diac lines (random)
#   SEED=42
#   SHUFFLE=1            # set 0 to keep deterministic row order
#   STRICT=0             # set 1 to fail on alignment warnings

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INVOCATION_CWD="$(pwd)"

abspath() {
  local path="$1"
  if [[ "$path" != /* ]]; then
    path="$INVOCATION_CWD/$path"
  fi
  echo "$(cd "$(dirname "$path")" && pwd)/$(basename "$path")"
}

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-1}"
}

NO_DIAC="${1:-}"
WITH_DIAC="${2:-}"
OUTPUT="${3:-}"
RATIO_PARTIAL="${RATIO_PARTIAL:-0.15}"
RATIO_FULL="${RATIO_FULL:-0.05}"
SEED="${SEED:-42}"
SHUFFLE="${SHUFFLE:-1}"
STRICT="${STRICT:-0}"

if [[ -z "$NO_DIAC" || -z "$WITH_DIAC" || -z "$OUTPUT" ]]; then
  usage
fi

NO_DIAC="$(abspath "$NO_DIAC")"
WITH_DIAC="$(abspath "$WITH_DIAC")"
OUTPUT="$(abspath "$OUTPUT")"

if [[ ! -f "$NO_DIAC" ]]; then
  echo "error: no-diac filelist not found: $NO_DIAC" >&2
  exit 1
fi
if [[ ! -f "$WITH_DIAC" ]]; then
  echo "error: with-diac filelist not found: $WITH_DIAC" >&2
  exit 1
fi

cd "$REPO_ROOT"

cmd=(python data/filelists/merge_ar_diacritics.py
  --no-diac "$NO_DIAC"
  --with-diac "$WITH_DIAC"
  --output "$OUTPUT"
  --ratio-partial "$RATIO_PARTIAL"
  --ratio-full "$RATIO_FULL"
  --seed "$SEED"
)

if [[ "$SHUFFLE" == "1" ]]; then
  cmd+=(--shuffle)
fi
if [[ "$STRICT" == "1" ]]; then
  cmd+=(--strict)
fi

echo "[merge_ar_diacritics] repo:           $REPO_ROOT"
echo "[merge_ar_diacritics] invoked from:   $INVOCATION_CWD"
echo "[merge_ar_diacritics] no-diac:        $NO_DIAC"
echo "[merge_ar_diacritics] with-diac:      $WITH_DIAC"
echo "[merge_ar_diacritics] output:         $OUTPUT"
echo "[merge_ar_diacritics] ratio_partial:  $RATIO_PARTIAL"
echo "[merge_ar_diacritics] ratio_full:     $RATIO_FULL"
echo "[merge_ar_diacritics] seed:           $SEED"
echo "[merge_ar_diacritics] shuffle:        $SHUFFLE"
echo "[merge_ar_diacritics] strict:         $STRICT"
echo

"${cmd[@]}"
