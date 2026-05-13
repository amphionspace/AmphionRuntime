# 阶段 A.2：把 encoder/joiner 做 INT8 动态量化

## 目标

- 把 `encoder.onnx`、`joiner.onnx` 做 动态量化（dynamic quantization） 得到 INT8 版本：
  - `encoder.int8.onnx`：核心收益，体积通常缩 3~4 倍、推理速度在 ARM CPU 上快 1.5~2 倍
  - `joiner.int8.onnx`：略有收益，体积变小，对 WER 影响小
- `decoder.onnx` 保持 FP32：体积本身就小（1~3 MB），且 INT8 的精度损失对 RNN-T 增量解码影响相对显著，不值得。

不用静态量化（static quant）的原因：
- 静态量化要校准集 + ONNX Runtime 的 calibration 流程，工程复杂度高一档；
- 流式 zipformer 的 encoder 内部状态多，校准时容易引入噪声；
- 经验上，动态量化在 streaming zipformer 上 WER 退化通常 < 0.3 个绝对点，而静态量化收益不大、风险更大。

## 准备

```bash
pip install onnxruntime==1.18.1 onnx==1.17.0
```

`onnxruntime.quantization` 自带 `quantize_dynamic` 工具，不需要单独装其他包。

## 量化命令

假设你已经按 `01_export_to_onnx.md` 把三件套放在 `./onnx-fp32/` 目录下：

```
onnx-fp32/
├── encoder.onnx
├── decoder.onnx
├── joiner.onnx
└── tokens.txt
```

执行下面的脚本：

```bash
mkdir -p onnx-int8
cp onnx-fp32/decoder.onnx onnx-int8/decoder.onnx
cp onnx-fp32/tokens.txt   onnx-int8/tokens.txt

python3 - <<'PY'
from onnxruntime.quantization import quantize_dynamic, QuantType
from onnxruntime.quantization.shape_inference import quant_pre_process

import os

os.makedirs("onnx-int8", exist_ok=True)

# encoder：先 shape inference，再做动态量化（避免某些算子被跳过）
quant_pre_process(
    input_model_path="onnx-fp32/encoder.onnx",
    output_model_path="onnx-int8/encoder.preproc.onnx",
    skip_optimization=False,
    skip_onnx_shape=False,
    skip_symbolic_shape=False,
    auto_merge=True,
    int_max=2**31 - 1,
    guess_output_rank=False,
    verbose=0,
)

quantize_dynamic(
    model_input="onnx-int8/encoder.preproc.onnx",
    model_output="onnx-int8/encoder.int8.onnx",
    weight_type=QuantType.QInt8,
    op_types_to_quantize=["MatMul", "Gemm", "Conv"],
    per_channel=True,
    reduce_range=False,
    extra_options={"MatMulConstBOnly": True},
)

# joiner：结构简单，直接量化
quant_pre_process(
    input_model_path="onnx-fp32/joiner.onnx",
    output_model_path="onnx-int8/joiner.preproc.onnx",
    skip_optimization=False,
    skip_onnx_shape=False,
    skip_symbolic_shape=False,
    auto_merge=True,
    int_max=2**31 - 1,
    guess_output_rank=False,
    verbose=0,
)

quantize_dynamic(
    model_input="onnx-int8/joiner.preproc.onnx",
    model_output="onnx-int8/joiner.int8.onnx",
    weight_type=QuantType.QInt8,
    op_types_to_quantize=["MatMul", "Gemm"],
    per_channel=True,
    reduce_range=False,
    extra_options={"MatMulConstBOnly": True},
)

print("done")
PY

# 量化中间产物清掉
rm -fv onnx-int8/encoder.preproc.onnx onnx-int8/joiner.preproc.onnx
```

## 关键参数解释

| 参数 | 取值 | 解释 |
| --- | --- | --- |
| `weight_type` | QInt8 | 权重存为 int8。也可选 QUInt8，但在 ARM 上 QInt8 更通用，且与 onnxruntime mobile 的 QLinearMatMul 内核更匹配 |
| `op_types_to_quantize` | `["MatMul", "Gemm", "Conv"]` (encoder) / `["MatMul", "Gemm"]` (joiner) | encoder 含 Conv1d，joiner 没有；显式列出避免量化 LayerNorm/Softmax 等带来 ARM 性能反而下降的算子 |
| `per_channel` | True | 沿权重 OC 维度做 per-channel 量化，对 zipformer 的多头注意力收益明显 |
| `reduce_range` | False | reduce_range=True 是给老 x86 SSE4 用的，ARM 上不需要，会浪费精度 |
| `MatMulConstBOnly` | True | 只量化常量权重侧，避免动态 input 被量化造成额外 dequant 开销 |

## 产物核对

```bash
ls -lh onnx-int8/
# 期望：
# encoder.int8.onnx ~ 35–50 MB
# decoder.onnx      ~ 1–3 MB（拷贝过来的 FP32）
# joiner.int8.onnx  ~ 3–6 MB
# tokens.txt
```

## sanity check：在量化后立刻验证 ONNX 能加载

```bash
python3 - <<'PY'
import onnxruntime as ort
for name in ["encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx"]:
    sess = ort.InferenceSession(f"onnx-int8/{name}", providers=["CPUExecutionProvider"])
    print(name, [i.name for i in sess.get_inputs()], "->",
          [o.name for o in sess.get_outputs()])
PY
```

如果能正常打印，说明量化模型自身没问题。WER 验证留到 `03_verify_onnx.sh`。

## 几个反复出现的坑

1. 量化报 `Unable to find data type for weight_name='...'`：忘了先做 `quant_pre_process` 的 shape inference，或者 onnx 版本太低。升 onnx 到 1.17+ 即可。
2. 量化后体积没变小：很可能是 `op_types_to_quantize` 列表写错了，或者模型里的 MatMul 是动态权重（B 不是常量），加 `MatMulConstBOnly: True` 时会跳过。先 `Netron` 看一下。
3. 量化后 WER 暴涨：通常是 `per_channel=False` 的影响。改成 True 重做。
4. 端上加载报 `[ONNXRuntimeError] Type Error: Type parameter (T) bound to different types`：opset 太旧（< 14），重新导出 ONNX 时把 `--opset 17` 之类传进去。
