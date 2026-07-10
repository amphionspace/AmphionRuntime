#!/usr/bin/env bash

ensure_license_python() {
  local venv="$1"
  local requirements="$2"
  local python="$venv/bin/python"

  if [[ -x "$python" ]] && "$python" -c 'import cryptography' >/dev/null 2>&1; then
    return
  fi

  command -v python3 >/dev/null || {
    echo "[ERROR] python3 is required to create the license environment" >&2
    return 1
  }
  echo "[INFO] creating or repairing license virtual environment: $venv" >&2
  python3 -m venv --clear "$venv"
  "$python" -m pip install -q -r "$requirements"
  "$python" -c 'import cryptography' >/dev/null
}
