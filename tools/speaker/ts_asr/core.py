"""TS-ASR 阶段 1（方案 A 工程化加固版）核心函数。

直接对应 [android/AmphionRuntime/docs/Target_speaker.md] 第 5 节给出的 5 段骨架代码。
本文件不做二次设计，只做：

1. 把 5 个函数从"展示用 snippet"改成可复用模块，方便 01/02/04 脚本共享
2. 显式参数化 ASR modelDir / speaker model / 阈值 / 滑窗，不在脚本里写死路径
3. 输入音频统一在 load_audio_mono16k 里做"单通道 + 16k + float32"归一，避免每个调用方各自写

加固点（与 plan 第 1 节对应）：

- 加固 1 多模板注册：enroll() 接受多段音频均值并单位化
- 加固 2 最短切片 1.5s 门限：segment_score() 入口判断
- 加固 3 滑窗多打分：win_sec=2.5, hop_sec=1.0，取窗内 max 余弦
- 加固 4 双阈值：DEFAULT_HIGH / DEFAULT_LOW 仅作起点，必须 ROC 标定后回填
- 加固 5 整段流式 ASR：asr_decode_full_segment() 用 AcceptWaveform + 0.5s tail + InputFinished + while is_ready: decode

注：本模块只导入 sherpa_onnx 与 numpy，不依赖 torch / onnxruntime；保持端侧友好。
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

try:
    import sherpa_onnx
except ImportError as e:
    raise ImportError(
        "sherpa_onnx Python 包未安装。请在 .venv 里 `pip install sherpa-onnx`。"
        "调研期不与端侧打包链路共享 venv，可单独建 `.venv-speaker/`。"
    ) from e


DEFAULT_HIGH: float = 0.55
DEFAULT_LOW: float = 0.25
DEFAULT_MIN_SEG_SEC: float = 1.5
DEFAULT_WIN_SEC: float = 2.5
DEFAULT_HOP_SEC: float = 1.0
TARGET_SAMPLE_RATE: int = 16000


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度。两个向量都不要求预先单位化，但本模块内部会单位化后再调用。"""
    a = np.asarray(a, dtype=np.float32)
    b = np.asarray(b, dtype=np.float32)
    denom = float(np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9
    return float(np.dot(a, b) / denom)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def load_audio_mono16k(path: Path | str) -> Tuple[np.ndarray, int]:
    """读 wav 成单通道 float32，并在采样率不一致时重采样到 16k。

    保留实际采样率作为返回值，调用方可用来记录"原始采样率"统计。
    """
    import soundfile as sf

    data, sr = sf.read(str(path), always_2d=True, dtype="float32")
    samples = np.ascontiguousarray(data[:, 0])
    if sr != TARGET_SAMPLE_RATE:
        # 调研期允许非 16k 输入，运行时统一上采到 16k；生产期上游应保证 16k
        try:
            import librosa
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                f"输入采样率 {sr} != 16000 且未安装 librosa；"
                "请 `pip install librosa` 或预先用 ffmpeg 重采样到 16k。"
            ) from e
        samples = librosa.resample(samples, orig_sr=sr, target_sr=TARGET_SAMPLE_RATE)
    return samples, sr


def build_recognizer(
    asr_model_dir: Path | str,
    *,
    num_threads: int = 2,
    provider: str = "cpu",
    decoding_method: str = "greedy_search",
    enable_endpoint_detection: bool = True,
) -> "sherpa_onnx.OnlineRecognizer":
    """加载已经导出量化好的流式 zipformer transducer。

    asr_model_dir 必须含 4 个固定文件名（与 [tools/asr/MODEL_LAYOUT.md] 一致）：
    - encoder.int8.onnx（int8 量化的 encoder）
    - decoder.onnx（fp32，体积小不量化）
    - joiner.int8.onnx
    - tokens.txt

    决策原因（对应调研文档推导链第 1 步）：流式 onnx 模型可以直接吃整段，不需要再加非流式模型。
    """
    asr_model_dir = Path(asr_model_dir)
    encoder = asr_model_dir / "encoder.int8.onnx"
    decoder = asr_model_dir / "decoder.onnx"
    joiner = asr_model_dir / "joiner.int8.onnx"
    tokens = asr_model_dir / "tokens.txt"
    for p in (encoder, decoder, joiner, tokens):
        if not p.is_file():
            raise FileNotFoundError(
                f"ASR modelDir 缺少 {p.name}。期望 4 文件命名见 tools/asr/MODEL_LAYOUT.md。"
            )
    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(tokens),
        encoder=str(encoder),
        decoder=str(decoder),
        joiner=str(joiner),
        num_threads=num_threads,
        provider=provider,
        sample_rate=TARGET_SAMPLE_RATE,
        feature_dim=80,
        decoding_method=decoding_method,
        enable_endpoint_detection=enable_endpoint_detection,
    )


def build_speaker(
    speaker_model: Path | str,
    *,
    num_threads: int = 1,
    provider: str = "cpu",
    debug: bool = False,
) -> "sherpa_onnx.SpeakerEmbeddingExtractor":
    """加载声纹 embedding 模型。

    speaker_model 推荐：
    - 中文：3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx（27 MB，sherpa-onnx Android sample 默认款）
    - 中英混合 / 通用：wespeaker_en_voxceleb_CAM++.onnx
    其它候选见 https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models
    """
    speaker_model = Path(speaker_model)
    if not speaker_model.is_file():
        raise FileNotFoundError(f"声纹模型不存在: {speaker_model}")
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=str(speaker_model),
        num_threads=num_threads,
        debug=debug,
        provider=provider,
    )
    if not cfg.validate():
        raise ValueError(f"声纹模型配置无效: {cfg}")
    return sherpa_onnx.SpeakerEmbeddingExtractor(cfg)


def enroll(
    extractor: "sherpa_onnx.SpeakerEmbeddingExtractor",
    wavs: Sequence[Tuple[np.ndarray, int]],
) -> np.ndarray:
    """多模板注册：把多段 enrollment 音频提 embedding 后取均值并单位化。

    输入约束（与调研文档第 4.1 节加固点 1 一致）：
    - 推荐 ≥3 段，每段 5-10s
    - 不同语速 / 距离 / 设备
    - wavs 里每段都已经过 load_audio_mono16k 处理（单通道、16k、float32）
    """
    if not wavs:
        raise ValueError("enroll() 需要至少 1 段音频")
    embs: List[np.ndarray] = []
    for samples, sr in wavs:
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=samples)
        s.input_finished()
        if not extractor.is_ready(s):
            raise RuntimeError(
                "enrollment 音频太短，extractor 未 ready。建议每段 ≥3s。"
            )
        embs.append(np.asarray(extractor.compute(s), dtype=np.float32))
    e = np.mean(np.stack(embs, axis=0), axis=0)
    return _l2_normalize(e)


def segment_score(
    extractor: "sherpa_onnx.SpeakerEmbeddingExtractor",
    target_emb: np.ndarray,
    samples: np.ndarray,
    sr: int = TARGET_SAMPLE_RATE,
    *,
    win_sec: float = DEFAULT_WIN_SEC,
    hop_sec: float = DEFAULT_HOP_SEC,
    min_seg_sec: float = DEFAULT_MIN_SEG_SEC,
) -> Optional[float]:
    """对 VAD 切出的一段语音打目标说话人余弦相似度。

    返回：
    - None：段长 < min_seg_sec，调用方应丢弃或累积到下一段
    - float：窗内余弦最大值；若段长 ≥ min_seg_sec 但 < win_sec，回落到整段单次打分

    决策原因（对应调研文档推导链第 4 步与第 4.1 节加固点 2/3）：
    - 短音频 EER 暴增（VoxCeleb1 baseline 1s 20.41%），统一 1.5s 兜底
    - overlap 段 embedding 被污染，滑窗 max 比单次打分更稳
    """
    target_emb = _l2_normalize(np.asarray(target_emb, dtype=np.float32))
    n_min = int(min_seg_sec * sr)
    if len(samples) < n_min:
        return None

    n_win = int(win_sec * sr)
    n_hop = int(hop_sec * sr)

    if len(samples) < n_win:
        # 段长够 1.5s 但不够 2.5s，回落到整段单次打分
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=samples)
        s.input_finished()
        if not extractor.is_ready(s):
            return None
        emb = _l2_normalize(np.asarray(extractor.compute(s), dtype=np.float32))
        return float(np.dot(emb, target_emb))

    scores: List[float] = []
    for st in range(0, len(samples) - n_win + 1, n_hop):
        seg = samples[st : st + n_win]
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=seg)
        s.input_finished()
        if not extractor.is_ready(s):
            continue
        emb = _l2_normalize(np.asarray(extractor.compute(s), dtype=np.float32))
        scores.append(float(np.dot(emb, target_emb)))

    if not scores:
        # 兜底（理论上不应触发）
        s = extractor.create_stream()
        s.accept_waveform(sample_rate=sr, waveform=samples)
        s.input_finished()
        if not extractor.is_ready(s):
            return None
        emb = _l2_normalize(np.asarray(extractor.compute(s), dtype=np.float32))
        return float(np.dot(emb, target_emb))
    return max(scores)


def asr_decode_full_segment(
    recognizer: "sherpa_onnx.OnlineRecognizer",
    samples: np.ndarray,
    sr: int = TARGET_SAMPLE_RATE,
    *,
    tail_sec: float = 0.5,
) -> str:
    """流式 zipformer 整段推理：AcceptWaveform(整段) + 末尾 tail 静音 + InputFinished + while ready: decode。

    决策原因（对应调研文档推导链第 1 步与加固点 5）：
    - sherpa-onnx OnlineRecognizer 内部就是按 chunk 顺序喂 + 维持 left/right context cache，
      整段输入只是把这个过程一次性触发，无需第二个非流式模型
    - tail 静音用来触发 endpointing（如果模型/配置启用），并避免末尾 token 被截断
    """
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate=sr, waveform=samples)
    if tail_sec > 0:
        tail = np.zeros(int(sr * tail_sec), dtype=np.float32)
        stream.accept_waveform(sample_rate=sr, waveform=tail)
    stream.input_finished()
    while recognizer.is_ready(stream):
        recognizer.decode_stream(stream)
    return recognizer.get_result(stream)
