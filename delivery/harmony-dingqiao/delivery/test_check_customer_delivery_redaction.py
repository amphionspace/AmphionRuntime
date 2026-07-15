import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("check_customer_delivery_redaction.py")
SPEC = importlib.util.spec_from_file_location("customer_delivery_redaction", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
find_violations = MODULE.find_violations


class CustomerDeliveryRedactionTest(unittest.TestCase):
    def write(self, name: str, content: str) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_accepts_redacted_customer_evidence(self) -> None:
        path = self.write(
            "evidence.json",
            json.dumps(
                {
                    "device_model": "REDACTED",
                    "device_identifier": "REDACTED",
                    "source_identifiers": "REDACTED",
                }
            ),
        )
        self.assertEqual(find_violations(path), [])

    def test_rejects_local_home_and_internal_run_id(self) -> None:
        path = self.write(
            "report.md",
            "/Users/example/Downloads/test.wav\n20260716-032413-user-sequence-63937379\n",
        )
        violations = find_violations(path)
        self.assertTrue(any("local user home path" in item for item in violations))
        self.assertTrue(any("internal stress run identifier" in item for item in violations))

    def test_rejects_raw_device_and_hardware_model(self) -> None:
        path = self.write(
            "report.md",
            "SN: A1B2C3D4E5F6G7H8\nRaw value: Z9Y8X7W6V5U4T3S2\nModel: MIA-AL00\n",
        )
        violations = find_violations(path)
        self.assertTrue(any("literal device identifier" in item for item in violations))
        self.assertTrue(any("probable device serial" in item for item in violations))
        self.assertTrue(any("hardware product code" in item for item in violations))

    def test_rejects_sensitive_json_values_and_container_types(self) -> None:
        path = self.write(
            "evidence.json",
            json.dumps(
                {
                    "deviceId": "A1B2C3D4E5F6",
                    "serialNumber": "Z9Y8X7W6V5U4",
                    "source_identifiers": ["raw.wav"],
                }
            ),
        )
        violations = find_violations(path)
        sensitive = [item for item in violations if "sensitive JSON value" in item]
        self.assertEqual(len(sensitive), 3)


if __name__ == "__main__":
    unittest.main()
