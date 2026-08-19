#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <homophone_collateral_corpus_100.tsv> <output_root>" >&2
  exit 2
fi

SOURCE_TSV=$1
OUTPUT_ROOT=$2
OUTPUT_WAVS="$OUTPUT_ROOT/wav16k"
OUTPUT_MANIFEST="$OUTPUT_ROOT/manifest.tsv"
VOICE=Tingting
RATE=180

command -v say >/dev/null
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
command -v shasum >/dev/null
[[ -f "$SOURCE_TSV" ]]
mkdir -p "$OUTPUT_WAVS"
if find "$OUTPUT_WAVS" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "output directory must be empty: $OUTPUT_WAVS" >&2
  exit 1
fi

tmp_aiff=$(mktemp /private/tmp/police-collision.XXXXXX.aiff)
trap 'rm -f "$tmp_aiff"' EXIT
tmp_manifest="$OUTPUT_MANIFEST.tmp"
printf 'asset_file\tid\treference_text\tsubcategory\tvoice\tsha256\tduration_s\n' > "$tmp_manifest"

while IFS=$'\t' read -r case_id subcategory reference; do
  asset_name="negative_${case_id}.wav"
  output_wav="$OUTPUT_WAVS/$asset_name"
  say -v "$VOICE" -r "$RATE" -o "$tmp_aiff" "$reference"
  ffmpeg -v error -nostdin -y -i "$tmp_aiff" -ar 16000 -ac 1 -c:a pcm_s16le "$output_wav"
  sha=$(shasum -a 256 "$output_wav" | awk '{ print $1 }')
  duration=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$output_wav")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$asset_name" "$case_id" "$reference" "$subcategory" "$VOICE" "$sha" "$duration" \
    >> "$tmp_manifest"
done < <(awk -F '\t' 'NR > 1 && $6 == "general" && $9 == "identity" { print $1 "\t" $3 "\t" $4 }' "$SOURCE_TSV")

mv "$tmp_manifest" "$OUTPUT_MANIFEST"
count=$(find "$OUTPUT_WAVS" -maxdepth 1 -type f -name 'negative_*.wav' | wc -l | tr -d ' ')
[[ "$count" == "53" ]]
echo "[OK] prepared $count synthetic general-domain collision wavs at $OUTPUT_WAVS"
