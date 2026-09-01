import unittest

from tools.delivery.device_stress_metrics import MemorySample, memory_verdict


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


if __name__ == "__main__":
    unittest.main()
