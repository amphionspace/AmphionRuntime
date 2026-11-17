# DeepFilterNet3 + Sortformer 角色分离链路

## 当前范围

本分支保存已在 Harmony 手机验证的 DeepFilterNet3 CPU 前端接入；角色分离沿用 Sortformer，测试使用模型槽位身份模式。未接入 NPU、GTCRN、UL-UNAS 或 NVIDIA Audio Effects，未修改 Android。

```text
原始 PCM16 → SessionAudioDispatcher → DeepFilterNet3 → 同一份增强 PCM
                                                     ├→ ASR → 文本
                                                     └→ Sortformer → 槽位与时间区间
文本 + 槽位时间区间 → 既有匹配与定稿逻辑 → 角色回调
```

ASR 和角色分离共享增强后的音频与时间轴。这里的“仅 diarization”指身份配置为 model，不加载 CAMPPlus 做公开身份解析；不是移除 ASR，也没有将降噪限制成只送给 Sortformer。

## 调用

```typescript
const params = new StartParams();
params.sessionId = 'df3-sortformer';
params.audioInfo = new AudioInfo();
params.speakerDiarization = new SpeakerDiarizationConfig();
params.speakerDiarization.speakerIdentityMode = 'model';
params.extraParams['noiseSuppressionModel'] = 'deepfilternet3';
engine.startListening(params);
```

持续输入 16 kHz、单声道 PCM16 little-endian；测试采用每 20 ms 一帧。降噪默认 none，只有显式设置 deepfilternet3 才启用。旧 enableGtcrn=true 和其他模型名报错；与目标说话人提取同时启用也报错。普通降噪不将重叠人声分成独立音轨。

## 源码入口

- `asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets`：创建前端、增强 PCM 分发、结束和取消。
- 同目录 `NoiseSuppressionConfig.ts`、`GtcrnDenoiser.ets`、`GtcrnFrontend.ts`：选择校验、native 桥接、PCM 转换与样本长度契约。
- 同目录 `diarization/SpeakerDiarizationSession.ets`、`SortformerLocalClient.ets`、`SortformerSpeakerIdentity.ts`：既有模型推理、身份与文本对齐链路。
- `asr/harmony/sdk/src/main/cpp/gtcrn_denoiser.cpp`：异步 native 所有权与模型桥接。
- 同目录 `stream_denoisers.cpp`、`denoise_dsp.h`：DF3 三图、显式状态、FFT、重采样、频谱合成。
- `asr/tools/prepare_df3_streaming.py`：从官方序列图导出单帧带状态图，并先验证序列输出一致性。

`Gtcrn*` 和 `createGtcrnDenoiser/processGtcrn` 是沿用的内部命名，不表示仍包含 GTCRN 模型；当前 native 创建入口仅接受 DeepFilterNet3。保留命名以复用已验证二进制，不夹带重命名重构。

## 模型资产恢复

权重不进入 Git，COS 前缀：

```text
cos://anfeiweng-audiollm-resource-1373259071/sortformer4SPK/DeepFilterNet3/sdk-streaming-v1/
```

从上述位置取 `df3_enc_stream.onnx`、`df3_erb_dec_stream.onnx`、`df3_df_dec_stream.onnx`，放入 `shared/models/asr/dingqiao/`。三图共 8,577,664 字节。许可证、来源及固定 SHA-256 清单随源码提交；`sdk-dingqiao/hvigorfile.ts` 构建时逐文件校验，不匹配即失败。远端 manifest.json 是该目录的注册清单。不要下载历史 GTCRN/UL-UNAS 模型。

Sortformer 四图和辅助资源按 `delivery/harmony-dingqiao/delivery/sortformer_diarization_v1.json` 恢复，ASR/VAD/标点等其他既有资源沿用项目资产准备流程。本分支更新的 Sortformer ORT 字节哈希对应本机实际重新转换并验证的产物；源 ONNX 哈希不变。

DF3 官方来源为 https://github.com/Rikorose/DeepFilterNet ，MIT 许可证见 `shared/models/asr/dingqiao/df3.LICENSE`。转换保持权重，仅显式暴露卷积历史和 GRU 状态。可用 `prepare_df3_streaming.py --archive <官方归档> --output <输出目录>` 重建，运行依赖 numpy、onnx、onnxruntime；本次使用 1.26 / 1.15 / 1.16.3。重建结果仍须匹配固定资产清单。

## 状态、时间轴与边界

16→48→16 kHz 重采样；FFT 960、hop 480、Vorbis 窗；32 ERB 带，低频 96 个复数频点采用 5 阶深度滤波、2 帧 lookahead。状态每会话独立；未加入 30 秒声纹 PCM 环形缓存。

补偿 STFT/模型的 30 ms 延迟及有界 FIR 延迟，保持公开音频时间轴，不消除实际等待。finish 排空输入、补齐尾部，输出样本数严格等于输入后，再结束两条分支。cancel 关闭旧会话队列，异步 native 任务安全持有模型，generation 校验丢弃迟到输出。

SDK 对静音也推进状态；与官方 Rust CLI 的低能量捷径在静音边界不保证逐样本相同。不做逐块响度归一化，不改变原来的文本/角色时间戳匹配逻辑。

## 已有验证与限制

2026-11-17 当前仅 DF3 二进制：18 项前端配置、样本契约及队列检查通过；四个 HAR 共 56 个实现文件通过 API 23 编译检查。真机 55.44 秒原音的 paced、cancel、finish-shutdown-relicense 三项通过。正常模式输入/输出均 887040 样本，0 error、1 complete，结束后 native stream 为零。

同次实测降噪累计 20.385 秒（RTF 0.368），Sortformer 累计 15.037 秒（RTF 0.271），首个非空识别结果距送音频开始 2.973 秒。计算耗时不是额外墙钟延迟；角色结果本次在结束时返回，不能声称约 3 秒产出确定角色。

此前同一 DF3 实现完成三条原始录音及七类生命周期检查；本次仅做删除其他模型后的最小回归。短三人录音仍有 UNKNOWN 与角色混淆，未通过该精度场景验收；不作为正式发布包。短跑内存指标为 INCONCLUSIVE，未执行完整发布或断网网络观测矩阵。

源码上传使用经过仓库历史清理的等价基线 2f0f35d3；对应此前测试基线的运行源码不变。上传前逐文件核对当前链路源码与已测工作区一致；文档和忽略规则调整不影响二进制。未混入更晚主线的其他运行逻辑。

最小本地检查：

```bash
python -m unittest asr.tools.tests.test_harmony_noise_suppression asr.tools.tests.test_harmony_gtcrn asr.tools.tests.test_harmony_async_audio_dispatch -q
```
