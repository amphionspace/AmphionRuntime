#!/usr/bin/env bash
# Shared helpers for customer delivery packaging and verification.

delivery_cert_sha256_from_keystore() {
  local keystore="$1"
  local alias="$2"
  local storepass="$3"
  local sha
  sha="$(
    keytool -list -v -keystore "$keystore" -alias "$alias" -storepass "$storepass" 2>/dev/null \
      | sed -n 's/.*SHA256: //p' \
      | sed -n '1p' \
      | tr -d '\r[:space:]'
  )"
  if [[ -z "$sha" ]]; then
    echo "[ERROR] unable to read SHA-256 from keystore=$keystore alias=$alias" >&2
    return 1
  fi
  printf '%s\n' "$sha"
}

delivery_verify_apk_signature() {
  local apk="$1"

  command -v apksigner >/dev/null 2>&1 || {
    echo "[ERROR] apksigner not found; install Android build-tools or add it to PATH" >&2
    return 1
  }
  [[ -f "$apk" ]] || {
    echo "[ERROR] APK not found: $apk" >&2
    return 1
  }
  apksigner verify --verbose "$apk" >/dev/null
}

delivery_apk_cert_sha256_from_apk() {
  local apk="$1"
  local sha

  command -v apksigner >/dev/null 2>&1 || {
    echo "[ERROR] apksigner not found; install Android build-tools or add it to PATH" >&2
    return 1
  }
  [[ -f "$apk" ]] || {
    echo "[ERROR] APK not found: $apk" >&2
    return 1
  }
  sha="$(
    apksigner verify --print-certs "$apk" 2>/dev/null \
      | sed -n 's/.*certificate SHA-256 digest: //p' \
      | sed -n '1p' \
      | tr -d '\r[:space:]'
  )"
  if [[ -z "$sha" ]]; then
    echo "[ERROR] unable to read certificate SHA-256 from APK: $apk" >&2
    return 1
  fi
  printf '%s\n' "$sha"
}

delivery_sign_apk() {
  local unsigned_apk="$1"
  local out_apk="$2"
  local keystore="$3"
  local alias="$4"
  local storepass="$5"
  local keypass="${6:-$storepass}"
  local aligned_apk
  aligned_apk="$(mktemp "${TMPDIR:-/tmp}/delivery-apk-aligned.XXXXXX.apk")"
  trap "rm -f '$aligned_apk'" RETURN

  command -v zipalign >/dev/null 2>&1 || {
    echo "[ERROR] zipalign not found; install Android build-tools or add it to PATH" >&2
    return 1
  }
  command -v apksigner >/dev/null 2>&1 || {
    echo "[ERROR] apksigner not found; install Android build-tools or add it to PATH" >&2
    return 1
  }
  [[ -f "$unsigned_apk" ]] || {
    echo "[ERROR] unsigned APK not found: $unsigned_apk" >&2
    return 1
  }
  [[ -f "$keystore" ]] || {
    echo "[ERROR] keystore not found: $keystore" >&2
    return 1
  }

  zipalign -f -p 4 "$unsigned_apk" "$aligned_apk"
  apksigner sign \
    --ks "$keystore" \
    --ks-key-alias "$alias" \
    --ks-pass "pass:$storepass" \
    --key-pass "pass:$keypass" \
    --out "$out_apk" \
    "$aligned_apk"
  apksigner verify --verbose "$out_apk"
}
