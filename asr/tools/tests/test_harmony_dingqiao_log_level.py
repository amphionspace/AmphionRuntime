from pathlib import Path
import re
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = REPO_ROOT / (
    "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/SpeechRecognizeSdk.ets"
)
INDEX = REPO_ROOT / "asr/harmony/sdk-dingqiao/Index.ets"
DEMO_ABILITY = REPO_ROOT / (
    "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/entryability/EntryAbility.ets"
)


def method_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : index]
    raise AssertionError(f"unterminated method: {signature}")


class HarmonyDingqiaoLogLevelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = ADAPTER.read_text(encoding="utf-8")
        cls.index = INDEX.read_text(encoding="utf-8")

    def test_public_adapter_exposes_the_core_log_level_type(self) -> None:
        self.assertIn("export { AmphionLogLevel } from 'amphion_asr';", self.index)
        imports = re.findall(
            r"import\s*\{.*?\}\s*from 'amphion_asr';",
            self.adapter,
            flags=re.DOTALL,
        )
        self.assertIn("AmphionLogLevel", "\n".join(imports))

    def test_default_level_remains_warn_and_explicit_level_reaches_runtime_init(self) -> None:
        self.assertIn(
            "private static runtimeLogLevel: AmphionLogLevel = AmphionLogLevel.WARN;",
            self.adapter,
        )
        setter = method_body(
            self.adapter,
            "static setLogLevel(logLevel: AmphionLogLevel): void",
        )
        self.assertIn("SpeechRecognizeSdk.runtimeLogLevel = logLevel", setter)

        options = method_body(
            self.adapter,
            "private static buildRuntimeOptions(",
        )
        self.assertIn(
            "options.logLevel = SpeechRecognizeSdk.runtimeLogLevel",
            options,
        )

    def test_runtime_invalidation_does_not_reset_the_selected_level(self) -> None:
        invalidate = method_body(
            self.adapter,
            "private static invalidateRuntime(): void",
        )
        self.assertNotIn("runtimeLogLevel", invalidate)

    def test_demo_enables_info_before_initializing_the_adapter(self) -> None:
        demo = DEMO_ABILITY.read_text(encoding="utf-8")
        level = demo.index("SpeechRecognizeSdk.setLogLevel(AmphionLogLevel.INFO)")
        initialize = demo.index("SpeechRecognizeSdk.init(")
        self.assertLess(level, initialize)


if __name__ == "__main__":
    unittest.main()
