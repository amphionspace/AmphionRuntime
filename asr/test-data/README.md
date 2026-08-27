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

- Never put credentials, licenses, signing material, device logs, raw evidence,
  voiceprint embeddings, or customer recordings in a test-data bundle.
- Each bundle must record its origin and redistribution status in the manifest.
- `publish` refuses an object that already exists with a different size. A new
  payload requires a new dataset version or object key.
- AudioSet audio downloaded from YouTube is not publishable. Google's official
  AudioSet release contains labels and derived features, not raw audio.
- The withdrawn aidatatang corpus and derived subsets require an explicit data
  owner approval before they may be shared beyond the existing authorized team.
