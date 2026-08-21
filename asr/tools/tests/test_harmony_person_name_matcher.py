import subprocess
import textwrap
import unittest
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[3]
MATCHER = ROOT / (
    "asr/harmony/sdk-police/src/main/ets/com/amphion/police/PersonNameMatcher.ts"
)
NODE = shutil.which("node") or (
    "/Users/lucky/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
)


class HarmonyPersonNameMatcherTest(unittest.TestCase):
    def run_node(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ PersonNameMatcher }} from {MATCHER.as_uri()!r};
            {body}
            """
        )
        subprocess.run(
            [NODE, "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_replaces_same_pinyin_window_that_overlaps_person_entity(self) -> None:
        self.run_node(
            """
            const pinyin = new Map([
              ['文', 'wen2'], ['赋', 'fu4'], ['富', 'fu4'],
              ['成', 'cheng2'], ['城', 'cheng2'],
              ['余', 'yu2'], ['祁', 'qi2'], ['其', 'qi2'], ['根', 'gen1'],
            ]);
            const matcher = new PersonNameMatcher(pinyin, ['文赋成', '余祁根']);
            assert.equal(
              matcher.normalize('往往给文富城发一条信息', [{ start: 3, end: 6 }]),
              '往往给文赋成发一条信息'
            );
            assert.equal(
              matcher.normalize('给文富成发短信。', [{ start: 1, end: 4 }]),
              '给文赋成发短信。'
            );
            assert.equal(
              matcher.normalize('该文富城发短信。', []),
              '该文赋成发短信。'
            );
            assert.equal(
              matcher.normalize('给余其根发一条信息', [{ start: 1, end: 2 }]),
              '给余祁根发一条信息'
            );
            """
        )

    def test_two_character_fallback_requires_person_span_and_ambiguous_signature_is_ignored(self) -> None:
        self.run_node(
            """
            const pinyin = new Map([
              ['文', 'wen2'], ['赋', 'fu4'], ['富', 'fu4'],
              ['成', 'cheng2'], ['城', 'cheng2'],
            ]);
            assert.equal(
              new PersonNameMatcher(pinyin, ['文赋']).normalize('文富很好', []),
              '文富很好'
            );
            assert.equal(
              new PersonNameMatcher(pinyin, ['文赋成', '文富城'])
                .normalize('给文富城发信息', [{ start: 1, end: 4 }]),
              '给文富城发信息'
            );
            """
        )

    def test_ignores_names_longer_than_three_characters(self) -> None:
        self.run_node(
            """
            const pinyin = new Map([
              ['三', 'san1'], ['科', 'ke1'], ['颗', 'ke1'],
              ['真', 'zhen1'], ['澄', 'cheng2'], ['诚', 'cheng2'],
            ]);
            const matcher = new PersonNameMatcher(pinyin, ['三科真澄']);
            assert.equal(
              matcher.normalize('请联系三颗真诚', [{ start: 3, end: 7 }]),
              '请联系三颗真诚'
            );
            """
        )


if __name__ == "__main__":
    unittest.main()
