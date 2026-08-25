import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("verify_harmony_native_abi.py")
SPEC = importlib.util.spec_from_file_location("verify_harmony_native_abi", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class VerifyHarmonyNativeAbiTest(unittest.TestCase):
    def test_parse_dynamic_symbols_separates_required_and_provided_symbols(self) -> None:
        undefined, defined = MODULE.parse_dynamic_symbols(
            "\n".join(
                [
                    "SherpaOnnxCreateWetextItn U 0 0",
                    "SherpaOnnxOnlineStreamCommitRule3Segment T e900c 3c",
                    "napi_get_undefined U 0 0",
                ]
            )
        )

        self.assertEqual(undefined, {"SherpaOnnxCreateWetextItn"})
        self.assertEqual(defined, {"SherpaOnnxOnlineStreamCommitRule3Segment"})

    def test_verify_pair_reports_unresolved_sherpa_symbols(self) -> None:
        outputs = {
            "napi.so": (
                {"SherpaOnnxCreateWetextItn", "SherpaOnnxOnlineStreamGetEndpointReason"},
                set(),
            ),
            "c-api.so": (set(), {"SherpaOnnxCreateWetextItn"}),
        }

        original = MODULE.dynamic_symbols
        MODULE.dynamic_symbols = lambda path, _tool: outputs[path.name]
        try:
            missing = MODULE.verify_pair(Path("napi.so"), Path("c-api.so"), ["llvm-nm"])
        finally:
            MODULE.dynamic_symbols = original

        self.assertEqual(missing, {"SherpaOnnxOnlineStreamGetEndpointReason"})


if __name__ == "__main__":
    unittest.main()
