import unittest

from check_pronunciation_report import report_matches_all_cases


class PronunciationReportTest(unittest.TestCase):
    def test_complete_match_passes(self):
        self.assertTrue(report_matches_all_cases({"total": 675, "pass": 675, "fail": 0, "error": 0}, 675))

    def test_observed_instrumentation_ok_with_295_mismatches_fails(self):
        self.assertFalse(report_matches_all_cases({"total": 675, "pass": 380, "fail": 295, "error": 0}, 675))

    def test_execution_errors_fail(self):
        self.assertFalse(report_matches_all_cases({"total": 675, "pass": 674, "fail": 0, "error": 1}, 675))

    def test_truncated_or_duplicate_count_fails(self):
        for total in (674, 676):
            with self.subTest(total=total):
                self.assertFalse(report_matches_all_cases({"total": total, "pass": total, "fail": 0, "error": 0}, 675))

    def test_empty_collection_fails(self):
        self.assertFalse(report_matches_all_cases({"total": 0, "pass": 0, "fail": 0, "error": 0}, 675))
        self.assertFalse(report_matches_all_cases({"total": 0, "pass": 0, "fail": 0, "error": 0}, 0))

    def test_missing_counts_fail(self):
        summary = {"total": 675, "pass": 675, "fail": 0, "error": 0}
        for field in summary:
            with self.subTest(field=field):
                self.assertFalse(report_matches_all_cases({k: v for k, v in summary.items() if k != field}, 675))

    def test_inconsistent_counts_fail(self):
        self.assertFalse(report_matches_all_cases({"total": 675, "pass": 674, "fail": 0, "error": 0}, 675))
        self.assertFalse(report_matches_all_cases({"total": 675, "pass": 675, "fail": 1, "error": 0}, 675))


if __name__ == "__main__":
    unittest.main()
