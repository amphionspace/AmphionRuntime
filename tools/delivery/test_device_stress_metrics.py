import unittest

from tools.delivery.device_stress_metrics import MemorySample, diarization_memory_verdict, memory_verdict


def sample(elapsed_seconds: float, rss_kb: int, threads: int = 4) -> MemorySample:
    return MemorySample(
        elapsed_seconds=elapsed_seconds,
        pid=7,
        vm_rss_kb=rss_kb,
        vm_hwm_kb=rss_kb,
        vm_data_kb=rss_kb,
        vm_swap_kb=0,
        threads=threads,
    )


class DeviceStressMetricsTest(unittest.TestCase):
    def test_short_observation_is_inconclusive(self) -> None:
        samples = [sample(float(index * 2), 1024) for index in range(6)]

        verdict = memory_verdict(samples, max_growth_mb=1.0, max_thread_growth=0)

        self.assertEqual("INCONCLUSIVE", verdict["status"])
        self.assertIn("observation shorter", verdict["reason"])

    def test_rss_growth_over_threshold_fails(self) -> None:
        rss_values = (1024, 1024, 1024, 2048, 3072, 4096)
        samples = [
            sample(float(index * 15), rss_kb)
            for index, rss_kb in enumerate(rss_values)
        ]

        verdict = memory_verdict(samples, max_growth_mb=1.0, max_thread_growth=0)

        self.assertEqual("FAIL", verdict["status"])
        self.assertGreater(verdict["rss_growth_mb"], 1.0)

    def test_diarization_keeps_raw_measurements_without_claiming_stability(self) -> None:
        for growth in (85.650, -10.0):
            with self.subTest(growth=growth):
                raw = {"status": "FAIL" if growth > 64 else "PASS", "rss_growth_mb": growth,
                       "max_rss_growth_mb": 64.0, "thread_growth": 0, "max_thread_growth": 2}
                original = dict(raw)
                verdict = diarization_memory_verdict(raw)
                self.assertEqual("INCONCLUSIVE", verdict["status"])
                self.assertEqual(original["status"], verdict["generic_status"])
                self.assertEqual(growth, verdict["rss_growth_mb"])
                self.assertEqual(original, raw)
                self.assertEqual(verdict, diarization_memory_verdict(verdict))

    def test_diarization_preserves_thread_and_explicit_budget_failures(self) -> None:
        raw = {"status": "FAIL", "rss_growth_mb": 85.650, "max_rss_growth_mb": 64.0,
               "thread_growth": 3, "max_thread_growth": 2}
        self.assertEqual("FAIL", diarization_memory_verdict(raw)["status"])
        raw["thread_growth"] = 0
        raw["rss_growth_limit_enforced"] = True
        self.assertEqual(raw, diarization_memory_verdict(raw))
        del raw["rss_growth_limit_enforced"]
        raw["max_rss_growth_mb"] = 80.0  # Older reports with a custom budget remain enforced.
        self.assertEqual(raw, diarization_memory_verdict(raw))

    def test_incomplete_evidence_cannot_erase_failure_or_prove_stability(self) -> None:
        self.assertEqual("FAIL", diarization_memory_verdict({"status": "FAIL"})["status"])
        raw = memory_verdict([sample(float(i), 1024) for i in range(6)], 64, 2)
        self.assertEqual("INCONCLUSIVE", diarization_memory_verdict(raw)["status"])
        self.assertEqual(raw["reason"], diarization_memory_verdict(raw)["reason"])


if __name__ == "__main__":
    unittest.main()
