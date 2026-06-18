#!/usr/bin/env bash
# 阶段 A.3：在 Linux 上验证 ONNX 模型识别效果
# - 用 sherpa-onnx Python 包做流式识别，吐出 hypothesis
# - 与 PyTorch / icefall 的 reference 解码结果对比，算 WER
# - 同时给一段用 sherpa-onnx C++ binary 跑同一份 wav 的命令，方便交叉验证

set -euo pipefail

# ---------- 解析参数 ----------
print_usage() {
  cat <<EOF
Usage: $0 \\
  --onnx-dir   <dir>                # 含 encoder.int8.onnx / decoder.onnx / joiner.int8.onnx / tokens.txt
  --test-wav-scp <file>             # 每行: <utt-id> <wav-path>
  --test-text    <file>             # 每行: <utt-id> <reference text>
  [--icefall-dir <dir>]             # icefall checkout 路径（用来跑 PyTorch reference 解码）
  [--exp-dir <dir>]                 # icefall 训练 exp 目录（含 epoch-X.pt）
  [--bpe-model <file>]              # BPE 模型，PyTorch 解码需要
  [--epoch <int>] [--avg <int>]     # icefall 解码用的 average 设置
  [--num-threads <int>]             # ONNX 推理线程数，默认 2
  [--decoding-method <str>]         # greedy_search / modified_beam_search，默认 greedy_search
  [--out-dir <dir>]                 # 中间产物目录，默认 ./verify-out
  [--skip-pytorch]                  # 跳过 PyTorch reference 解码（如果已经有结果文件）

PyTorch reference 路径与 ONNX 路径任选其一比对，最终会算两个数字：
  - WER(ONNX) vs ground-truth
  - WER(ONNX vs PyTorch)（前提：跑了 PyTorch 解码）
EOF
  exit 1
}

ONNX_DIR=""
TEST_WAV_SCP=""
TEST_TEXT=""
ICEFALL_DIR=""
EXP_DIR=""
BPE_MODEL=""
EPOCH=""
AVG=""
NUM_THREADS=2
DECODING_METHOD="greedy_search"
OUT_DIR="./verify-out"
SKIP_PYTORCH=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --onnx-dir)         ONNX_DIR="$2";        shift 2;;
    --test-wav-scp)     TEST_WAV_SCP="$2";    shift 2;;
    --test-text)        TEST_TEXT="$2";       shift 2;;
    --icefall-dir)      ICEFALL_DIR="$2";     shift 2;;
    --exp-dir)          EXP_DIR="$2";         shift 2;;
    --bpe-model)        BPE_MODEL="$2";       shift 2;;
    --epoch)            EPOCH="$2";           shift 2;;
    --avg)              AVG="$2";             shift 2;;
    --num-threads)      NUM_THREADS="$2";     shift 2;;
    --decoding-method)  DECODING_METHOD="$2"; shift 2;;
    --out-dir)          OUT_DIR="$2";         shift 2;;
    --skip-pytorch)     SKIP_PYTORCH=1;       shift;;
    -h|--help)          print_usage;;
    *) echo "unknown arg: $1"; print_usage;;
  esac
done

if [[ -z "$ONNX_DIR" || -z "$TEST_WAV_SCP" || -z "$TEST_TEXT" ]]; then
  echo "Missing required args."
  print_usage
fi

mkdir -p "$OUT_DIR"

ENCODER="$ONNX_DIR/encoder.int8.onnx"
DECODER="$ONNX_DIR/decoder.onnx"
JOINER="$ONNX_DIR/joiner.int8.onnx"
TOKENS="$ONNX_DIR/tokens.txt"

for f in "$ENCODER" "$DECODER" "$JOINER" "$TOKENS"; do
  if [[ ! -f "$f" ]]; then
    echo "missing: $f"; exit 1
  fi
done

# ---------- 检查 sherpa-onnx Python 包 ----------
if ! python3 -c "import sherpa_onnx" 2>/dev/null; then
  echo "[INFO] sherpa-onnx python package not found, installing..."
  pip install sherpa-onnx==1.13.1
fi

# ---------- ONNX 推理：用 sherpa-onnx Python 流式 API ----------
ONNX_HYP="$OUT_DIR/onnx_hyp.txt"
echo "[1/3] Running ONNX streaming decoding -> $ONNX_HYP"

python3 - "$ENCODER" "$DECODER" "$JOINER" "$TOKENS" "$TEST_WAV_SCP" "$ONNX_HYP" \
        "$NUM_THREADS" "$DECODING_METHOD" <<'PY'
import sys, wave, numpy as np
import sherpa_onnx

(encoder, decoder, joiner, tokens, wav_scp, out_hyp,
 num_threads, decoding_method) = sys.argv[1:9]

recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=tokens,
    encoder=encoder,
    decoder=decoder,
    joiner=joiner,
    num_threads=int(num_threads),
    sample_rate=16000,
    feature_dim=80,
    enable_endpoint_detection=True,
    rule1_min_trailing_silence=2.4,
    rule2_min_trailing_silence=1.4,
    rule3_min_utterance_length=20.0,
    decoding_method=decoding_method,
    provider="cpu",
)

def read_wave(path):
    with wave.open(path) as f:
        assert f.getnchannels() == 1, f"{path} not mono"
        assert f.getsampwidth() == 2, f"{path} not int16"
        sr = f.getframerate()
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0, sr

with open(wav_scp) as f, open(out_hyp, "w") as fout:
    for line in f:
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2:
            continue
        utt_id, wav_path = parts
        samples, sr = read_wave(wav_path)
        if sr != 16000:
            import librosa
            samples = librosa.resample(samples, orig_sr=sr, target_sr=16000)

        stream = recognizer.create_stream()
        chunk = 1600  # 100 ms
        i = 0
        while i < len(samples):
            stream.accept_waveform(16000, samples[i:i+chunk])
            i += chunk
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        text = recognizer.get_result(stream).text
        fout.write(f"{utt_id} {text}\n")
        print(f"  {utt_id}: {text}")
PY

# ---------- 可选：PyTorch reference 解码 ----------
PT_HYP=""
if [[ $SKIP_PYTORCH -eq 0 && -n "$ICEFALL_DIR" && -n "$EXP_DIR" && -n "$BPE_MODEL" && -n "$EPOCH" && -n "$AVG" ]]; then
  PT_HYP="$OUT_DIR/pytorch_hyp.txt"
  echo "[2/3] Running PyTorch reference decoding -> $PT_HYP"

  pushd "$ICEFALL_DIR" >/dev/null
  export PYTHONPATH=$PWD:$PYTHONPATH

  python3 -c "
import torch, sys
sys.path.insert(0, 'egs/librispeech/ASR')

# 这里只给一个最小可跑的桥接示例，实际请按你训练的 recipe 调用 decode.py
# 大多数 icefall recipe 都自带 decode.py，可以直接：
#   ./zipformer/decode.py --epoch X --avg Y --use-averaged-model 1 \\
#     --exp-dir $EXP_DIR --decoding-method greedy_search --beam-size 4 \\
#     --max-duration 600
# 然后把它 dump 出来的 hyp 文件复制到 $PT_HYP
print('请在你训练的 recipe 目录下运行 decode.py，并把 hyp 保存到 $PT_HYP')
"

  popd >/dev/null

  if [[ ! -f "$PT_HYP" ]]; then
    echo "[WARN] PyTorch hyp 文件不存在，跳过双向比对。"
    PT_HYP=""
  fi
else
  echo "[2/3] 跳过 PyTorch reference 解码（参数不全或 --skip-pytorch）"
fi

# ---------- 计算 WER ----------
echo "[3/3] Computing WER..."

# 简单的中英混合 WER 计算：英文按词、中文按字
python3 - "$TEST_TEXT" "$ONNX_HYP" "$PT_HYP" <<'PY'
import sys
ref_path, onnx_path, pt_path = sys.argv[1], sys.argv[2], sys.argv[3]

import re

def is_cjk(c):
    return (
        '\u4e00' <= c <= '\u9fff' or
        '\u3400' <= c <= '\u4dbf' or
        '\uf900' <= c <= '\ufaff'
    )

def tokenize(text):
    text = text.upper().strip()
    out = []
    buf = []
    for c in text:
        if is_cjk(c):
            if buf:
                out.append("".join(buf)); buf = []
            out.append(c)
        elif c.isspace():
            if buf:
                out.append("".join(buf)); buf = []
        else:
            buf.append(c)
    if buf:
        out.append("".join(buf))
    return out

def levenshtein(ref, hyp):
    n, m = len(ref), len(hyp)
    if n == 0: return m, 0, m, 0
    dp = [[0]*(m+1) for _ in range(n+1)]
    for i in range(n+1): dp[i][0] = i
    for j in range(m+1): dp[0][j] = j
    for i in range(1, n+1):
        for j in range(1, m+1):
            if ref[i-1] == hyp[j-1]:
                dp[i][j] = dp[i-1][j-1]
            else:
                dp[i][j] = 1 + min(dp[i-1][j-1], dp[i-1][j], dp[i][j-1])
    return dp[n][m]

def load_kv(path):
    out = {}
    if not path: return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split(maxsplit=1)
            if len(parts) == 1:
                out[parts[0]] = ""
            else:
                out[parts[0]] = parts[1]
    return out

ref_d  = load_kv(ref_path)
onnx_d = load_kv(onnx_path)
pt_d   = load_kv(pt_path) if pt_path else {}

def wer(ref_d, hyp_d, label):
    total, errs = 0, 0
    miss = 0
    for utt, ref_text in ref_d.items():
        hyp_text = hyp_d.get(utt)
        if hyp_text is None:
            miss += 1; continue
        r = tokenize(ref_text)
        h = tokenize(hyp_text)
        e = levenshtein(r, h)
        total += len(r)
        errs += e
    if total == 0:
        print(f"{label}: no data")
        return
    print(f"{label}: WER = {errs/total*100:.2f}%  ({errs}/{total}, missing={miss})")

wer(ref_d, onnx_d, "ONNX  vs ground-truth")
if pt_d:
    wer(ref_d, pt_d, "PyTorch vs ground-truth")
    wer(pt_d, onnx_d, "ONNX vs PyTorch (cross check)")
PY

echo
echo "================================================"
echo " ONNX hyp:    $ONNX_HYP"
[[ -n "$PT_HYP" ]] && echo " PyTorch hyp: $PT_HYP"
echo "================================================"

# ---------- 附：用 sherpa-onnx C++ binary 复跑（可选） ----------
cat <<'EOF'

可选：用 sherpa-onnx 已编译的 C++ binary 跑同一份样本做交叉验证：

    ./build/bin/sherpa-onnx \
        --tokens=$ONNX_DIR/tokens.txt \
        --encoder=$ONNX_DIR/encoder.int8.onnx \
        --decoder=$ONNX_DIR/decoder.onnx \
        --joiner=$ONNX_DIR/joiner.int8.onnx \
        --decoding-method=greedy_search \
        --num-threads=2 \
        path/to/some.wav

如果 C++ binary 与 Python 包跑同一份 wav 得出的文本一致，说明端上 (Android) 跑的也会一致。
EOF
