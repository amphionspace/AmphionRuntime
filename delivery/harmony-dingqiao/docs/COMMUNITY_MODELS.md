# Community-1 candidate (Harmony)

The three `community-*` files are restored from the private object-storage prefix
in `delivery/harmony-dingqiao/delivery/community_diarization_1.json` with
`ab pull '<storagePrefix>' shared/models/asr/dingqiao/`. Check every file against
that manifest before building. They contain global model weights/statistics;
customer PCM and enrollment embeddings must not be added to this directory.
The existing segmentation model is shared. Runtime uses packaged assets and
requires no network access. This candidate has not passed all identity gates.
