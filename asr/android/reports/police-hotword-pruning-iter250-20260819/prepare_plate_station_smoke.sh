#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <station_root> <plate_root> <output_root>" >&2
  exit 2
fi

STATION_ROOT=$1
PLATE_ROOT=$2
OUTPUT_ROOT=$3
OUTPUT_WAVS="$OUTPUT_ROOT/wav16k"
OUTPUT_MANIFEST="$OUTPUT_ROOT/manifest.tsv"
STATION_PATTERN='(观音桥|中关村|五角场|解放碑|中央大街|绳金塔|张掖路|泉城路)派出所'
PLATE_ORIG_PATTERN='^license_plate_v2_([1-5]|5[1-5])$'

command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v shasum >/dev/null
[[ -f "$STATION_ROOT/cases.tsv" ]]
[[ -f "$PLATE_ROOT/cases.tsv" ]]
mkdir -p "$OUTPUT_WAVS"
if find "$OUTPUT_WAVS" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "output directory must be empty: $OUTPUT_WAVS" >&2
  exit 1
fi

tmp_manifest="$OUTPUT_MANIFEST.tmp"
printf 'asset_file\tgroup\texpected_term\treference_text\tsource_file\tsha256\tduration_s\n' > "$tmp_manifest"

prepare_one() {
  local group=$1
  local root=$2
  local utt_id=$3
  local reference=$4
  local audio_path=$5
  local expected=$6
  local source_wav="$root/$audio_path"
  local asset_name="cross_${group}__${utt_id}.wav"
  local output_wav="$OUTPUT_WAVS/$asset_name"
  local sha
  local duration

  [[ -f "$source_wav" ]]
  ffmpeg -v error -nostdin -i "$source_wav" -ar 16000 -ac 1 -c:a pcm_s16le "$output_wav"
  sha=$(shasum -a 256 "$output_wav" | awk '{ print $1 }')
  duration=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$output_wav")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$asset_name" "$group" "$expected" "$reference" "$audio_path" "$sha" "$duration" \
    >> "$tmp_manifest"
}

while IFS=$'\t' read -r utt_id _orig_id reference audio_path; do
  expected=$(printf '%s\n' "$reference" | grep -oE "$STATION_PATTERN" | head -n 1)
  [[ -n "$expected" ]]
  prepare_one station "$STATION_ROOT" "$utt_id" "$reference" "$audio_path" "$expected"
done < <(awk -F '\t' -v pattern="$STATION_PATTERN" \
  'NR > 1 && $5 ~ pattern { print $1 "\t" $2 "\t" $5 "\t" $6 }' \
  "$STATION_ROOT/cases.tsv")

while IFS=$'\t' read -r utt_id _orig_id reference audio_path; do
  expected=$(printf '%s\n' "$reference" | grep -oE '(冀R|辽B)[0-9]{5}' | head -n 1)
  [[ -n "$expected" ]]
  prepare_one plate "$PLATE_ROOT" "$utt_id" "$reference" "$audio_path" "$expected"
done < <(awk -F '\t' -v pattern="$PLATE_ORIG_PATTERN" \
  'NR > 1 && $2 ~ pattern { print $1 "\t" $2 "\t" $5 "\t" $6 }' \
  "$PLATE_ROOT/cases.tsv")

mv "$tmp_manifest" "$OUTPUT_MANIFEST"
station_count=$(find "$OUTPUT_WAVS" -maxdepth 1 -type f -name 'cross_station__*.wav' | wc -l | tr -d ' ')
plate_count=$(find "$OUTPUT_WAVS" -maxdepth 1 -type f -name 'cross_plate__*.wav' | wc -l | tr -d ' ')
[[ "$station_count" == "27" ]]
[[ "$plate_count" == "20" ]]
echo "[OK] prepared station=$station_count plate=$plate_count at $OUTPUT_WAVS"
