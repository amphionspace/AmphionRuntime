#!/usr/bin/env bash

_license_python_usable() {
  local python="$1"
  [[ -x "$python" ]] && "$python" - <<'PY' >/dev/null 2>&1
import cryptography

# tools/license/requirements.txt currently declares cryptography>=42.0.0.
major = int(cryptography.__version__.split(".", 1)[0])
if major < 42:
    raise SystemExit(1)
PY
}

ensure_license_python() {
  local venv="$1"
  local requirements="$2"
  local python="$venv/bin/python"
  local bootstrap_python="${LICENSE_PYTHON:-python3}"
  local lock="${venv}.lock"
  local attempts=0

  [[ -x "$python" ]] || python="$venv/Scripts/python.exe"
  if _license_python_usable "$python"; then
    return
  fi

  command -v "$bootstrap_python" >/dev/null || {
    echo "[ERROR] Python is required to create the license environment" >&2
    return 1
  }
  mkdir -p "$(dirname "$venv")"
  until mkdir "$lock" 2>/dev/null; do
    attempts=$((attempts + 1))
    if [[ "$attempts" -ge 300 ]]; then
      echo "[ERROR] timed out waiting for license environment lock: $lock" >&2
      return 1
    fi
    sleep 0.2
  done

  (
    cleanup_license_python_lock() {
      rm -rf "$lock"
    }
    trap cleanup_license_python_lock EXIT
    trap 'cleanup_license_python_lock; exit 130' INT TERM

    if _license_python_usable "$python"; then
      exit 0
    fi
    echo "[INFO] creating or repairing license virtual environment: $venv" >&2
    "$bootstrap_python" -m venv --clear "$venv"
    [[ -x "$venv/bin/python" ]] || python="$venv/Scripts/python.exe"
    "$python" -m pip install -q -r "$requirements"
    _license_python_usable "$python"
  )
}
