#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <police_ui_20260713_root> <output_root>" >&2
  exit 2
fi

SOURCE_ROOT=$1
OUTPUT_ROOT=$2
SOURCE_WAVS="$SOURCE_ROOT/wavs"
SOURCE_MANIFEST="$SOURCE_ROOT/manifest.tsv"
OUTPUT_WAVS="$OUTPUT_ROOT/wav16k"
OUTPUT_MANIFEST="$OUTPUT_ROOT/manifest.tsv"
INDICES=(002 003 004 005 006 007 009 010 011 012 013 014 015 016 017 018 019 020 021 022 023 024 025 026 028 031 037 038 044 075)

command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v shasum >/dev/null
[[ -f "$SOURCE_MANIFEST" ]]
mkdir -p "$OUTPUT_WAVS"
if find "$OUTPUT_WAVS" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "output directory must be empty: $OUTPUT_WAVS" >&2
  exit 1
fi

tmp_manifest="$OUTPUT_MANIFEST.tmp"
printf 'asset_file\texpected_term\treference_text\tsource_file\tsha256\tduration_s\n' > "$tmp_manifest"

for index in "${INDICES[@]}"; do
  for take in 0 1; do
    source_name="police_ui_pui_${index}_${take}_s${take}.wav"
    source_wav="$SOURCE_WAVS/$source_name"
    asset_name="ui30_${index}_${take}_s${take}.wav"
    output_wav="$OUTPUT_WAVS/$asset_name"
    [[ -f "$source_wav" ]]

    row=$(awk -F '\t' -v wav="$source_name" 'NR > 1 && $1 == wav { print; exit }' "$SOURCE_MANIFEST")
    [[ -n "$row" ]]
    term=$(printf '%s\n' "$row" | awk -F '\t' '{ print $2 }')
    reference=$(printf '%s\n' "$row" | awk -F '\t' '{ print $3 }')
    canonical_term=${term//、/}

    ffmpeg -v error -nostdin -i "$source_wav" -ar 16000 -ac 1 -c:a pcm_s16le "$output_wav"
    sha=$(shasum -a 256 "$output_wav" | awk '{ print $1 }')
    duration=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$output_wav")
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "$asset_name" "$canonical_term" "$reference" "$source_name" "$sha" "$duration" \
      >> "$tmp_manifest"
  done
done

mv "$tmp_manifest" "$OUTPUT_MANIFEST"
count=$(find "$OUTPUT_WAVS" -maxdepth 1 -type f -name 'ui30_*.wav' | wc -l | tr -d ' ')
[[ "$count" == "60" ]]
echo "[OK] prepared $count UI30 wavs at $OUTPUT_WAVS"
