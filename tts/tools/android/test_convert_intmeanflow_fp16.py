import unittest
import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper as h, numpy_helper as nh, TensorProto as T
from convert_intmeanflow_fp16 import convert_model


def model(nodes, weights, out_type=T.FLOAT):
    graph = h.make_graph(nodes, 'test', [h.make_tensor_value_info('x', T.FLOAT, [1, 1])],
                         [h.make_tensor_value_info('mel_length', out_type, [1, 1])], weights)
    return h.make_model(graph, opset_imports=[h.make_opsetid('', 17)], ir_version=9)


def run(graph):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = 1
    return ort.InferenceSession(graph.SerializeToString(), opts, providers=['CPUExecutionProvider']).run(
        None, {'x': np.ones((1, 1), np.float32)})[0]


class ConversionTest(unittest.TestCase):
    def test_adjacent_fp32_math_keeps_large_mask_finite(self):
        original = model([
            h.make_node('MatMul', ['x', 'w'], ['y'], name='projection'),
            h.make_node('Constant', [], ['sentinel'], name='sentinel', value=nh.from_array(np.array(-1e10, np.float32))),
            h.make_node('Mul', ['zero', 'sentinel'], ['mask'], name='mask'),
            h.make_node('Add', ['y', 'mask'], ['mel_length'], name='sum'),
        ], [nh.from_array(np.array([[0.25]], np.float32), 'w'), nh.from_array(np.array(0, np.float32), 'zero')])
        expected = run(original)
        converted, _ = convert_model(original, 'decoder.onnx')
        np.testing.assert_allclose(run(converted), expected, atol=1e-4)

    def test_duration_branch_does_not_round_before_ceil(self):
        original = model([
            h.make_node('MatMul', ['x', 'w'], ['duration'], name='duration'),
            h.make_node('Ceil', ['duration'], ['rounded'], name='ceil'),
            h.make_node('Cast', ['rounded'], ['mel_length'], name='length', to=T.INT64),
        ], [nh.from_array(np.array([[1.0001]], np.float32), 'w')], T.INT64)
        expected = run(original)
        converted, _ = convert_model(original, 'lits_hidden_encoder.onnx')
        np.testing.assert_array_equal(run(converted), expected)


if __name__ == '__main__':
    unittest.main()
