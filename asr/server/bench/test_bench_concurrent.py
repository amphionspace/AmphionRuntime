import importlib.util
import sys
import types
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("bench_concurrent.py")
SPEC = importlib.util.spec_from_file_location("bench_concurrent", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
for dependency in ("grpc", "asr_pb2", "asr_pb2_grpc"):
    sys.modules.setdefault(dependency, types.ModuleType(dependency))
SPEC.loader.exec_module(MODULE)


class BenchConcurrentReportTest(unittest.TestCase):
    def test_aggregate_includes_dashboard_percentiles(self) -> None:
        report = MODULE.aggregate(
            [
                MODULE.WorkerStats(
                    sessions=2,
                    first_partial_ms=[100.0, 300.0],
                    final_ms=[500.0, 700.0],
                    rtf=[0.2, 0.4],
                )
            ]
        )

        self.assertAlmostEqual(report["first_partial_ms"]["p95"], 290.0)
        self.assertAlmostEqual(report["rtf"]["p95"], 0.39)


if __name__ == "__main__":
    unittest.main()
