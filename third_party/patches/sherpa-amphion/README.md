# sherpa-onnx Amphion patches (v1.13.1)

Upstream submodule stays pinned at **k2-fsa/sherpa-onnx tag v1.13.1** (`f3b1a9da`).
Amphion-specific JNI is applied on top via `git am`:

| Patch | Purpose |
|-------|---------|
| `0001-*` | `TextRewriteFst` JNI — 警务域 FST 后处理 |
| `0002-*` | WeTextProcessing vendor + `WetextItn` JNI — 中文 ITN |
| `0003-*` | ITN token reorder：「两点五八万」→ `2.58万` |
| `0004-*` | Harmony HAR 只构建 arm64-v8a，避免未产出的 x86_64 native lib 破坏命令行构建 |

Apply (automatic in `04_build_android_so.sh` / `02_init_submodule.sh`):

```bash
bash asr/tools/apply_sherpa_patches.sh
```

**Do not** bump `third_party/sherpa-onnx` to a local-only commit in the parent repo.
If you need a git fork instead of patches, push branch `amphion-patched` to a company
mirror and update `.gitmodules` URL — never point at SHAs that only exist on one laptop.
