# Versioned test data

Test corpora that are too large for Git live in Huawei Cloud OBS. The manifest
pins every object by byte size and SHA-256 so a test run on another machine uses
the same input.

The default local root is `~/.cache/amphion-runtime/test-data/v1`. Override it
with `AMPHION_TEST_DATA_DIR`.

## Configure OBS credentials

Export these variables without committing their values:

```bash
export OBS_AccesskeyID=...
export OBS_SecretAccesskey=...
export OBS_Endpoint=https://obs.cn-north-9.myhuaweicloud.com
```

Install Huawei Cloud's OBS Python SDK, then fetch and verify the data:

```bash
python3 -m pip install esdk-obs-python
python3 asr/tools/test_data.py list
python3 asr/tools/test_data.py fetch all
python3 asr/tools/test_data.py verify all
```

`fetch` downloads to a temporary file, checks SHA-256 before extraction, and
replaces only the selected versioned bundle. Interrupted multipart downloads
can resume from their checkpoint files.

## Publishing policy

- Never put credentials, SDK licenses, signing material, device logs, or
  voiceprint embeddings in a test-data bundle. Customer recordings and their
  annotation evidence require explicit user authorization and internal-only OBS
  access; they must not be committed to Git or redistributed publicly.
- Each bundle must record its origin and redistribution status in the manifest.
- `publish` refuses an object that already exists with a different size. A new
  payload requires a new dataset version or object key.
- AudioSet audio downloaded from YouTube is not publishable. Google's official
  AudioSet release contains labels and derived features, not raw audio.
- The withdrawn aidatatang corpus and derived subsets require an explicit data
  owner approval before they may be shared beyond the existing authorized team.

## Customer meeting acceptance, 2026-09-18

`dingqiao-meeting-20260918` contains the five explicitly authorized offline
customer recordings (1,010.64 seconds), original MOSS auxiliary annotations,
human adjudication history and final decisions, and source-bound comparison
evidence. The cloud-recognition recording is excluded. This bundle is internal
evaluation data, not an openly licensed corpus or fully labeled DER benchmark.

```bash
python3 asr/tools/test_data.py fetch dingqiao-meeting-20260918
python3 tools/assets/sync.py verify dingqiao-meeting-20260918
```

Read `SOURCE.md`, `samples.json` and `annotations/human-final.json` after fetching.
The manifest pins the archive and each file. Original WAV bytes are preserved;
MOSS labels are auxiliary and historical listening decisions can be superseded
by later user adjudication. Do not force four speakers in every recording.

The accepted scope is customer-audio improvement with intact sentence output;
minor measured performance cost is accepted. See the
[scoped wrap-up](../../delivery/harmony-dingqiao/docs/CUSTOMER_MEETING_SENTENCE_WRAPUP_20260918.md)
for benefits, remaining errors and evidence limits.
