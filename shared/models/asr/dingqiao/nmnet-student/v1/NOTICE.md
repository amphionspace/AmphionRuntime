# NMNet student v1 model resources

This is a development candidate, not a declaration of SDK release acceptance.
The five ONNX graphs were exported from the user-supplied NMNet project with
`tools/export_sdk_onnx.py`, opset 17, and checked against ONNX Runtime 1.16.3.
`manifest.json` fixes inference order, file sizes, SHA-256 and source checkpoint
identities. The graphs contain their weights; no external tensor files or
runtime downloads are used.

The student checkpoint (epoch 29) and NeSt frontend checkpoint are user-supplied.
Their redistribution authorization and upstream NeSt weight terms have not yet
been established in this repository. Do not infer a license from the runtime
source license; this is an unresolved release prerequisite.

ECAPA source: speechbrain/spkrec-ecapa-voxceleb, revision
`0f99f2d0ebe89ac095bcc5903c4dd8f72b367286`. The upstream model card declares
Apache-2.0; its model card and Apache-2.0 text accompany this bundle.
Embedding checkpoint SHA-256:
`0575cb64845e6b9a10db9bcb74d5ac32b326b8dc90352671d345e2ee3d0126a2`.

To restore ignored binary resources from the verified local export, run from
the repository root:

```
node asr/tools/nmnet_model_resources.cjs restore diarization/nmnet_v015_conformer/outputs/sdk-export-v8
node asr/tools/nmnet_model_resources.cjs verify
```

Both platforms package this directory at `amphion-dingqiao/nmnet-student/v1`.
Adding resources does not switch the public Community backend. Existing
Community resources remain required until the public backend routing is migrated.
