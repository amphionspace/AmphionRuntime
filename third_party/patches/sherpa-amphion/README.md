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
| `0007-*` | Harmony 冷启动优化：已知模型跳过重复探测、API 11+ rawfile64 mmap + ORT 直载、Zipformer2 多 lane 建图，以及 ASR/标点异步工厂与可配置预热；当前 `zhen` 配置跳过 eager warmup |
| `0008-*` | Harmony 模型显式卸载、异步句柄安全释放，以及 prepack 生命周期控制 |
| `0009-*` | Harmony 声纹 extractor 的 N-API 异步工厂、后台静音预热与幂等显式释放，避免阻塞 ArkTS 音频链路并保证卸载回收 |
| `0010-*` | Android 识别无需解压的 ORT 资源，降低首次模型准备的文件复制开销 |
| `0011-*` | Android 直接 mmap 未压缩 ORT 资源，避免首次启动重复落盘 |
| `0012-*` | 共享 WeText 在标识符数字串中兼容 ASR 的“么/幺”同音输出，并向 Harmony HAR 暴露同一 ITN 实现 |
| `0013-*` | Harmony online decode 增加后台异步入口；recognizer/stream handle 使用共享租约，保证 cancel/unload 与在途 decode 不发生悬空访问 |
| `0014-*` | Harmony N-API 在 UTF-8 字符串转换边界计算热词 buffer 字节数，避免 ArkTS UTF-16 长度截断中文热词 |
| `0015-*` | modified beam search 在每条 hypothesis 的声学 top-50 内对热词起始/延续 token 临时 `+3` 后再做最终 beam 裁剪；入选后扣除临时分，由 ContextGraph 保持原有逐 token `+3` 与回滚语义 |
| `0016-*` | native endpoint 返回按规则优先级判定的 reason，并通过 Harmony 内部 binding 暴露，避免 Runtime 用累计 PCM 猜测 Rule3 |
| `0017-*` | Rule3 final 使用 native checkpoint 冻结已发布路径并保留连续 encoder/decoder context，避免边界丢 token 或重复 token |
| `0018-*` | Rule3 checkpoint 压缩历史 token 后保留长度归一化偏移，确保 modified beam search 的后续路径排序与 continuous 一致 |
| `0019-*` | Harmony speaker embedding 增加带 extractor/stream 租约的异步计算入口，避免在 ArkTS 音频链路同步执行 ONNX |
| `0020-*` | Harmony speaker embedding 候选评分合并为单个异步批次，在同一 extractor 锁内顺序计算，减少重复任务排队与锁竞争 |

Apply automatically from the Harmony `04_build_harmony_so.sh` entry point (Android also applies the same series from its native build flow):

```bash
bash asr/tools/apply_sherpa_patches.sh
```

**Do not** bump `third_party/sherpa-onnx` to a local-only commit in the parent repo.
If you need a git fork instead of patches, push branch `amphion-patched` to a company
mirror and update `.gitmodules` URL — never point at SHAs that only exist on one laptop.
