"""Fixtures for the dynamic-quantisation rewrite that makes the ASR encoder convertible."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from asr.tools import dequantize_asr_encoder as tool


def quantized_matmul_graph(*, weight: np.ndarray, zero_point: int = 0, scale: float = 0.25,
                           extra_consumer: bool = False, batch: str = "N"):
    """One activation quantiser feeding one or two MatMulInteger groups."""
    rows, columns = weight.shape
    nodes = [
        helper.make_node("DynamicQuantizeLinear", ["x"], ["x_q", "x_scale", "x_zp"], name="quant"),
    ]
    initializers = []
    outputs = []
    groups = 2 if extra_consumer else 1
    for index in range(groups):
        suffix = f"_{index}"
        initializers += [
            numpy_helper.from_array(weight, f"w{suffix}"),
            numpy_helper.from_array(np.array(zero_point, dtype=np.int8), f"w_zp{suffix}"),
            numpy_helper.from_array(np.array(scale, dtype=np.float32), f"w_scale{suffix}"),
        ]
        nodes += [
            helper.make_node("MatMulInteger", ["x_q", f"w{suffix}", "x_zp", f"w_zp{suffix}"],
                             [f"acc{suffix}"], name=f"matmul_integer{suffix}"),
            helper.make_node("Cast", [f"acc{suffix}"], [f"acc_f{suffix}"], to=TensorProto.FLOAT,
                             name=f"cast{suffix}"),
            helper.make_node("Mul", ["x_scale", f"w_scale{suffix}"], [f"scales{suffix}"],
                             name=f"scales_mul{suffix}"),
            helper.make_node("Mul", [f"acc_f{suffix}", f"scales{suffix}"], [f"y{suffix}"],
                             name=f"output_mul{suffix}"),
        ]
        outputs.append(helper.make_tensor_value_info(f"y{suffix}", TensorProto.FLOAT, [batch, columns]))
    graph = helper.make_graph(
        nodes, "quantized",
        [helper.make_tensor_value_info("x", TensorProto.FLOAT, [batch, rows])],
        outputs, initializers)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    return model


class RewriteTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(11)
        self.weight = self.rng.integers(-127, 127, size=(4, 3), dtype=np.int8)

    def test_plan_matches_every_group(self):
        model = quantized_matmul_graph(weight=self.weight, extra_consumer=True)
        groups, stats = tool.plan(model.graph)
        self.assertEqual(stats, {"matmul_integer": 2, "dynamic_quantize_linear": 1, "groups": 2})
        self.assertEqual([group.activation for group in groups], ["x", "x"])
        self.assertEqual(sorted(group.output for group in groups), ["y_0", "y_1"])

    def test_plan_rejects_a_non_constant_weight(self):
        model = quantized_matmul_graph(weight=self.weight)
        retired = {item.name for item in model.graph.initializer if item.name == "w_0"}
        del model.graph.initializer[:]
        model.graph.initializer.extend(
            item for item in quantized_matmul_graph(weight=self.weight).graph.initializer
            if item.name not in retired)
        model.graph.input.append(helper.make_tensor_value_info("w_0", TensorProto.INT8, [4, 3]))
        with self.assertRaises(tool.RewriteError):
            tool.plan(model.graph)

    def test_rewrite_removes_quant_operators_and_keeps_values(self):
        model = quantized_matmul_graph(weight=self.weight, zero_point=3, scale=0.125,
                                       extra_consumer=True)
        groups, _ = tool.plan(model.graph)
        record = tool.rewrite(model, groups)
        self.assertEqual(record["rewritten_groups"], 2)
        kinds = {node.op_type for node in model.graph.node}
        self.assertEqual(kinds, {"MatMul"})
        onnx.checker.check_model(model, full_check=False)
        weights = {item.name: numpy_helper.to_array(item) for item in model.graph.initializer}
        expected = (self.weight.astype(np.float32) - np.float32(3)) * np.float32(0.125)
        np.testing.assert_allclose(weights["w_0_dequantized"], expected, rtol=0, atol=0)
        self.assertNotIn("w_0", weights)
        self.assertNotIn("w_scale_0", weights)

    def test_rewritten_graph_matches_the_quantised_graph_closely(self):
        try:
            import onnxruntime as ort
        except ImportError:
            self.skipTest("onnxruntime is unavailable")
        weight = self.rng.integers(-100, 100, size=(8, 5), dtype=np.int8)
        source = quantized_matmul_graph(weight=weight, scale=0.05)
        rewritten = quantized_matmul_graph(weight=weight, scale=0.05)
        groups, _ = tool.plan(rewritten.graph)
        tool.rewrite(rewritten, groups)
        feeds = {"x": self.rng.standard_normal((2, 8), dtype=np.float32)}
        values = []
        for model in (source, rewritten):
            session = ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])
            values.append(session.run(["y_0"], feeds)[0])
        # Only the activation quantisation error separates the two graphs.
        np.testing.assert_allclose(values[0], values[1], rtol=0, atol=0.05 * np.abs(values[0]).max() + 0.05)

    def test_dequantize_weight_requires_per_tensor_scale(self):
        with self.assertRaises(tool.RewriteError):
            tool.dequantize_weight(self.weight, np.array(0, dtype=np.int8),
                                   np.array([0.1, 0.2], dtype=np.float32))
        with self.assertRaises(tool.RewriteError):
            tool.dequantize_weight(self.weight.astype(np.float32), np.array(0, dtype=np.int8),
                                   np.array(0.1, dtype=np.float32))

    def test_signature_and_fixed_shape_argument(self):
        model = quantized_matmul_graph(weight=self.weight)
        signature = tool.input_signature(model.graph)
        self.assertEqual(signature, [{"name": "x", "dtype": "FLOAT", "shape": ["N", 4]}])
        self.assertEqual(tool.fixed_shape_argument(signature, 1), "x:1,4")
        self.assertEqual(tool.fixed_shape_argument(signature, 3), "x:3,4")

    def test_synthetic_inputs_follow_the_signature(self):
        signature = [{"name": "x", "dtype": "FLOAT", "shape": ["N", 4]},
                     {"name": "lens", "dtype": "INT64", "shape": ["N"]}]
        feeds = tool.synthetic_inputs(signature, 2, 7)
        self.assertEqual(feeds["x"].shape, (2, 4))
        self.assertEqual(feeds["x"].dtype, np.float32)
        self.assertEqual(feeds["lens"].tolist(), [0, 0])
        with self.assertRaises(tool.RewriteError):
            tool.synthetic_inputs([{"name": "b", "dtype": "BOOL", "shape": [1]}], 1, 7)


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="asr encoder dequant ")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = self.directory / "encoder.int8.onnx"
        weight = np.random.default_rng(3).integers(-50, 50, size=(6, 2), dtype=np.int8)
        onnx.save(quantized_matmul_graph(weight=weight), str(self.source))

    def run_tool(self, *arguments):
        return subprocess.run(
            [sys.executable, str(Path(tool.__file__)), *arguments],
            capture_output=True, text=True, cwd=str(Path(tool.__file__).resolve().parents[2]))

    def test_unpinned_source_is_refused_without_the_override(self):
        result = self.run_tool("--source", str(self.source), "--inspect")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("not the pinned delivery encoder", result.stderr)

    def test_inspect_reports_the_plan_without_writing(self):
        output = self.directory / "written.onnx"
        result = self.run_tool("--source", str(self.source), "--output", str(output),
                               "--inspect", "--allow-unpinned-source")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["plan"]["groups"], 1)
        self.assertEqual(record["converterInputShape"], "x:1,6")
        self.assertFalse(record["source"]["pinned"])
        self.assertFalse(output.exists())

    def test_conversion_writes_a_model_and_provenance(self):
        output = self.directory / "written.onnx"
        result = self.run_tool("--source", str(self.source), "--output", str(output),
                               "--allow-unpinned-source")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(output.exists())
        record = json.loads(output.with_suffix(output.suffix + ".provenance.json").read_text())
        self.assertEqual(record["rewrite"]["rewritten_groups"], 1)
        self.assertEqual(record["output"]["residualQuantOps"], {})
        kinds = {node.op_type for node in onnx.load(str(output)).graph.node}
        self.assertEqual(kinds, {"MatMul"})


if __name__ == "__main__":
    unittest.main()
