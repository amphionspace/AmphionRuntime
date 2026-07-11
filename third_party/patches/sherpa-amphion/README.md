# sherpa-onnx Amphion patches (v1.13.1)

Upstream submodule stays pinned at **k2-fsa/sherpa-onnx tag v1.13.1** (`f3b1a9da`).
Amphion-specific JNI is applied on top via `git am`:

| Patch | Purpose |
|-------|---------|
| `0001-*` | `TextRewriteFst` JNI — 警务域 FST 后处理 |
| `0002-*` | WeTextProcessing vendor + `WetextItn` JNI — 中文 ITN |
| `0003-*` | ITN token reorder：「两点五八万」→ `2.58万` |
| `0004-*` | Harmony HAR 只构建 arm64-v8a，避免未产出的 x86_64 native lib 破坏命令行构建 |
| `0005-*` | Harmony recognizer 创建异常转为 ArkTS 异常，避免无效模型触发 SIGABRT |
| `0006-*` | Harmony online stream 增加显式幂等释放与存活计数，避免依赖 ArkTS GC 导致会话级泄漏 |
| `0007-*` | Harmony 冷启动优化：已知模型跳过重复探测、API 11+ rawfile64 mmap + ORT 直载、Zipformer2 双路建图，以及 ASR/标点异步工厂与后台预热 |

Apply (automatic in `04_build_android_so.sh` / `02_init_submodule.sh`):

```bash
bash asr/tools/apply_sherpa_patches.sh
```

**Do not** bump `third_party/sherpa-onnx` to a local-only commit in the parent repo.
If you need a git fork instead of patches, push branch `amphion-patched` to a company
mirror and update `.gitmodules` URL — never point at SHAs that only exist on one laptop.
