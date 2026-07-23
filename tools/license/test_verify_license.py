from __future__ import annotations

import unittest

from tools.license.verify_license import _sdk_major_matches


class VerifyLicenseSdkMajorTest(unittest.TestCase):
    def test_zero_license_major_is_unbounded(self) -> None:
        self.assertTrue(_sdk_major_matches(0, 1))
        self.assertTrue(_sdk_major_matches(0, 99))

    def test_different_positive_majors_are_rejected(self) -> None:
        self.assertFalse(_sdk_major_matches(1, 2))
        self.assertFalse(_sdk_major_matches(2, 1))


if __name__ == "__main__":
    unittest.main()
