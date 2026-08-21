from __future__ import annotations

from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
INDEX_PAGE = (
    REPO_ROOT
    / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets"
)


class HarmonyDemoScrollLayoutTest(unittest.TestCase):
    def test_index_page_uses_a_viewport_scroll_container(self) -> None:
        source = INDEX_PAGE.read_text(encoding="utf-8")

        self.assertIn(
            "build() {\n    Scroll() {\n      Column({ space: 12 }) {",
            source,
        )
        self.assertEqual(1, source.count("Scroll()"))
        self.assertIn(".scrollBar(BarState.Auto)", source)


if __name__ == "__main__":
    unittest.main()
