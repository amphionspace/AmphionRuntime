"""Fixtures for the operator substitutions that make the ASR encoder NNRt-expressible."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

from asr.tools import rewrite_asr_encoder_npu_ops as tool


def model_of(nodes, inputs, outputs, initializers=(), name="graph"):
    graph = helper.make_graph(nodes, name, inputs, outputs, list(initializers))
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 7
    onnx.checker.check_model(model, full_check=False)
    return model


def value(name, shape, dtype=TensorProto.FLOAT):
    return helper.make_tensor_value_info(name, dtype, shape)


def constant(name, array):
    return numpy_helper.from_array(array, name)


def run(model, feeds, outputs):
    import onnxruntime as ort

    session = ort.InferenceSession(model.SerializeToString(), providers=["CPUExecutionProvider"])
    return session.run(outputs, feeds)


class FlatIndexTest(unittest.TestCase):
    def test_base_and_stride_reproduce_gather_elements(self):
        rng = np.random.default_rng(5)
        data = rng.standard_normal((3, 4, 7), dtype=np.float32)
        indices = rng.integers(0, 7, size=(3, 4, 5)).astype(np.int64)
        base, stride = tool.coordinate_base(data.shape, indices.shape, 2)
        flat = (indices * stride + base).reshape(-1)
        picked = data.reshape(-1)[flat].reshape(indices.shape)
        expected = np.take_along_axis(data, indices, axis=2)
        np.testing.assert_array_equal(picked, expected)

    def test_negative_axis_is_normalised(self):
        base_positive, stride_positive = tool.coordinate_base((2, 3, 4), (2, 3, 4), 2)
        base_negative, stride_negative = tool.coordinate_base((2, 3, 4), (2, 3, 4), -1)
        np.testing.assert_array_equal(base_positive, base_negative)
        self.assertEqual(stride_positive, stride_negative)

    def test_rank_and_axis_are_checked(self):
        with self.assertRaises(tool.RewriteError):
            tool.coordinate_base((2, 3), (2, 3, 4), 1)
        with self.assertRaises(tool.RewriteError):
            tool.coordinate_base((2, 3), (2, 3), 5)
        with self.assertRaises(tool.RewriteError):
            tool.coordinate_base((2, 3), (4, 3), 1)


class GatherElementsRewriteTest(unittest.TestCase):
    def test_rewrite_matches_the_original_and_drops_the_operator(self):
        rng = np.random.default_rng(9)
        indices = rng.integers(0, 6, size=(2, 3, 4)).astype(np.int64)
        nodes = [helper.make_node("GatherElements", ["a", "idx"], ["y"], axis=2, name="ge")]
        source = model_of(nodes, [value("a", [2, 3, 6]), value("idx", [2, 3, 4], TensorProto.INT64)],
                          [value("y", [2, 3, 4])])
        rewritten = model_of([helper.make_node("GatherElements", ["a", "idx"], ["y"], axis=2, name="ge")],
                             [value("a", [2, 3, 6]), value("idx", [2, 3, 4], TensorProto.INT64)],
                             [value("y", [2, 3, 4])])
        record = tool.rewrite(rewritten, 1)
        self.assertEqual(len(record["rewrittenNodes"]), 1)
        self.assertNotIn("GatherElements", {node.op_type for node in rewritten.graph.node})
        feeds = {"a": rng.standard_normal((2, 3, 6), dtype=np.float32), "idx": indices}
        first = run(source, feeds, ["y"])[0]
        second = run(rewritten, feeds, ["y"])[0]
        np.testing.assert_array_equal(first, second)


class LessOrEqualRewriteTest(unittest.TestCase):
    def test_substitution_preserves_the_comparison(self):
        nodes = [helper.make_node("LessOrEqual", ["a", "b"], ["flag"], name="le"),
                 helper.make_node("Where", ["flag", "a", "b"], ["y"], name="pick")]
        inputs = [value("a", [4]), value("b", [4])]
        source = model_of(nodes, inputs, [value("y", [4])])
        rewritten = model_of([helper.make_node("LessOrEqual", ["a", "b"], ["flag"], name="le"),
                              helper.make_node("Where", ["flag", "a", "b"], ["y"], name="pick")],
                             [value("a", [4]), value("b", [4])], [value("y", [4])])
        tool.rewrite(rewritten, 1)
        kinds = {node.op_type for node in rewritten.graph.node}
        self.assertNotIn("LessOrEqual", kinds)
        self.assertEqual({"Greater", "Not", "Where"}, kinds)
        feeds = {"a": np.array([1.0, 2.0, 3.0, 3.0], dtype=np.float32),
                 "b": np.array([3.0, 2.0, 1.0, 3.0], dtype=np.float32)}
        np.testing.assert_array_equal(run(source, feeds, ["y"])[0], run(rewritten, feeds, ["y"])[0])


class SoftplusGuardTest(unittest.TestCase):
    def guarded_model(self):
        nodes = [
            helper.make_node("Sub", ["a", "offset"], ["z"], name="shift"),
            helper.make_node("Exp", ["z"], ["e"], name="exp"),
            helper.make_node("Add", ["e", "one"], ["p"], name="plus"),
            helper.make_node("Log", ["p"], ["l"], name="log"),
            helper.make_node("Cast", ["l"], ["c"], to=TensorProto.FLOAT, name="cast"),
            helper.make_node("Equal", ["c", "infinity"], ["flag"], name="overflowed"),
            helper.make_node("Where", ["flag", "z", "c"], ["y"], name="guard"),
        ]
        return model_of(nodes, [value("a", [6])], [value("y", [6])],
                        [constant("offset", np.array(4.0, dtype=np.float32)),
                         constant("one", np.array(1.0, dtype=np.float32)),
                         constant("infinity", np.array(np.inf, dtype=np.float32))])

    def test_guard_is_replaced_by_the_stable_form(self):
        rewritten = self.guarded_model()
        record = tool.rewrite_softplus_guards(rewritten)
        self.assertEqual(record["rewrittenGuards"], 1)
        kinds = {node.op_type for node in rewritten.graph.node}
        self.assertNotIn("Equal", kinds)
        self.assertNotIn("Where", kinds)
        self.assertTrue({"Abs", "Neg", "Exp", "Log", "Max", "Add"} <= kinds)

    def test_stable_form_agrees_where_the_original_does_not_overflow(self):
        source, rewritten = self.guarded_model(), self.guarded_model()
        tool.rewrite_softplus_guards(rewritten)
        feeds = {"a": np.array([-10.0, 0.0, 3.9, 4.0, 10.0, 50.0], dtype=np.float32)}
        first, second = run(source, feeds, ["y"])[0], run(rewritten, feeds, ["y"])[0]
        np.testing.assert_allclose(first, second, rtol=1e-5, atol=1e-5)

    def test_stable_form_stays_finite_where_the_original_overflows(self):
        source, rewritten = self.guarded_model(), self.guarded_model()
        tool.rewrite_softplus_guards(rewritten)
        feeds = {"a": np.array([200.0, 200.0, 200.0, 200.0, 200.0, 200.0], dtype=np.float32)}
        # The guard exists because exp(196) is inf; both paths must still return z.
        np.testing.assert_allclose(run(source, feeds, ["y"])[0], run(rewritten, feeds, ["y"])[0],
                                   rtol=1e-5, atol=1e-5)
        self.assertTrue(np.all(np.isfinite(run(rewritten, feeds, ["y"])[0])))

    def test_a_finite_limit_is_not_treated_as_a_guard(self):
        model = self.guarded_model()
        for item in model.graph.initializer:
            if item.name == "infinity":
                item.CopyFrom(constant("infinity", np.array(1.0, dtype=np.float32)))
        self.assertEqual(tool.rewrite_softplus_guards(model)["rewrittenGuards"], 0)


class IdentityCastTest(unittest.TestCase):
    def test_same_type_casts_are_dropped_and_consumers_rewired(self):
        nodes = [helper.make_node("Cast", ["m"], ["m2"], to=TensorProto.BOOL, name="noop"),
                 helper.make_node("Where", ["m2", "a", "b"], ["y"], name="pick")]
        model = model_of(nodes, [value("a", [4]), value("b", [4]), value("m", [4], TensorProto.BOOL)],
                         [value("y", [4])])
        dropped = tool.drop_identity_casts(model, {"m": TensorProto.BOOL})
        self.assertEqual(dropped, 1)
        self.assertEqual([node.op_type for node in model.graph.node], ["Where"])
        self.assertEqual(list(model.graph.node[0].input), ["m", "a", "b"])

    def test_a_real_cast_is_kept(self):
        nodes = [helper.make_node("Cast", ["a"], ["i"], to=TensorProto.INT32, name="real"),
                 helper.make_node("Cast", ["i"], ["f"], to=TensorProto.FLOAT, name="back")]
        model = model_of(nodes, [value("a", [4])], [value("f", [4])])
        self.assertEqual(tool.drop_identity_casts(model, {"a": TensorProto.FLOAT,
                                                          "i": TensorProto.INT32}), 0)

    def test_dropping_a_graph_output_is_refused(self):
        nodes = [helper.make_node("Cast", ["m"], ["y"], to=TensorProto.BOOL, name="noop")]
        model = model_of(nodes, [value("m", [4], TensorProto.BOOL)], [value("y", [4], TensorProto.BOOL)])
        with self.assertRaises(tool.RewriteError):
            tool.drop_identity_casts(model, {"m": TensorProto.BOOL})


class ConstantAndShapeFoldTest(unittest.TestCase):
    def test_constant_nodes_become_initializers(self):
        tensor = numpy_helper.from_array(np.array([2, 3], dtype=np.int64), "value")
        nodes = [helper.make_node("Constant", [], ["shape"], value=tensor, name="shape_const"),
                 helper.make_node("Reshape", ["a", "shape"], ["y"], name="reshape")]
        model = model_of(nodes, [value("a", [6])], [value("y", [2, 3])])
        self.assertEqual(tool.canonicalise_constants(model), 1)
        self.assertEqual([node.op_type for node in model.graph.node], ["Reshape"])
        self.assertIn("shape", {item.name for item in model.graph.initializer})

    def test_shape_chains_fold_into_constants(self):
        nodes = [helper.make_node("Shape", ["a"], ["shape"], name="shape"),
                 helper.make_node("Gather", ["shape", "zero"], ["dim"], axis=0, name="pick"),
                 helper.make_node("Unsqueeze", ["dim", "axes"], ["dim1"], name="lift"),
                 helper.make_node("Concat", ["dim1", "tail"], ["target"], axis=0, name="join"),
                 helper.make_node("Reshape", ["a", "target"], ["y"], name="reshape")]
        model = model_of(nodes, [value("a", [2, 3])], [value("y", [2, 3])],
                         [constant("zero", np.array(0, dtype=np.int64)),
                          constant("axes", np.array([0], dtype=np.int64)),
                          constant("tail", np.array([3], dtype=np.int64))])
        record = tool.fold_static_subgraph(model, {"a": (2, 3)})
        self.assertEqual(record["foldedShapeNodes"], 1)
        self.assertEqual([node.op_type for node in model.graph.node], ["Reshape"])
        feeds = {"a": np.arange(6, dtype=np.float32).reshape(2, 3)}
        np.testing.assert_array_equal(run(model, feeds, ["y"])[0], feeds["a"])


class CommandLineTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="asr encoder npu ops ")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.source = self.directory / "encoder.onnx"
        rng = np.random.default_rng(4)
        nodes = [helper.make_node("MatMul", ["a", "w"], ["h"], name="project"),
                 helper.make_node("GatherElements", ["h", "idx"], ["y"], axis=1, name="ge")]
        model = model_of(nodes, [value("a", [1, 5]), value("idx", [1, 3], TensorProto.INT64)],
                         [value("y", [1, 3])],
                         [constant("w", rng.standard_normal((5, 6), dtype=np.float32))])
        onnx.save(model, str(self.source))

    def run_tool(self, *arguments):
        return subprocess.run([sys.executable, str(Path(tool.__file__)), *arguments],
                              capture_output=True, text=True,
                              cwd=str(Path(tool.__file__).resolve().parents[2]))

    def test_inspect_counts_refused_operators(self):
        result = self.run_tool("--source", str(self.source), "--inspect")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["refusedOperators"]["GatherElements"], 1)

    def test_rewrite_writes_a_model_without_refused_operators(self):
        output = self.directory / "rewritten.onnx"
        result = self.run_tool("--source", str(self.source), "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(output.with_suffix(output.suffix + ".provenance.json").read_text())
        self.assertEqual(record["output"]["residualRefusedOperators"], {})
        kinds = {node.op_type for node in onnx.load(str(output)).graph.node}
        self.assertNotIn("GatherElements", kinds)


if __name__ == "__main__":
    unittest.main()
