"""鸿蒙 DiarizationPcmWindow 的门禁：用 node 执行真实 TS。

重点钉住"取不到就返回 undefined"——嵌入拿到错位音频会安静地判错身份，
比直接说"这段没法判"糟得多。
"""
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WINDOW = (
    REPO_ROOT
    / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization/DiarizationPcmWindow.ts"
)


class HarmonyDiarizationPcmWindowTest(unittest.TestCase):
    def run_window(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ DiarizationPcmWindow, PCM_WINDOW_RETAIN_SECONDS }} from {WINDOW.as_uri()!r};

            const SR = 16000;
            // 第 n 个样本的值取 (n % 1000) - 500，便于校验取回的是哪一段
            const pcm = (fromSample, count) => {{
              const a = new Int16Array(count);
              for (let i = 0; i < count; i++) a[i] = ((fromSample + i) % 1000) - 500;
              return a.buffer;
            }};
            const expected = (fromSample, count) => {{
              const a = new Float32Array(count);
              for (let i = 0; i < count; i++) a[i] = (((fromSample + i) % 1000) - 500) / 32768;
              return a;
            }};
            const close = (a, b) => {{
              assert.equal(a.length, b.length, 'length');
              for (let i = 0; i < a.length; i++) {{
                assert.ok(Math.abs(a[i] - b[i]) < 1e-6, `sample ${{i}}: ${{a[i]}} vs ${{b[i]}}`);
              }}
            }};
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_slice_returns_the_requested_span(self) -> None:
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            w.append(pcm(0, SR * 3));                      // 0~3000ms
            close(w.slice(1000, 2000), expected(SR, SR));  // 第 1000~2000ms
            assert.equal(w.totalSamples(), SR * 3);
            """
        )

    def test_span_evicted_by_wraparound_returns_undefined(self) -> None:
        """被覆盖的区间必须说"取不到"，不能返回环绕后的错位音频。"""
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 2);      // 只留 2 秒
            w.append(pcm(0, SR * 5));                       // 写了 5 秒，前 3 秒已被覆盖
            assert.equal(w.slice(0, 1000), undefined, '已覆盖的区间必须 undefined');
            assert.equal(w.slice(2500, 3500), undefined, '跨越覆盖边界也必须 undefined');
            close(w.slice(3000, 4000), expected(SR * 3, SR));   // 仍在窗内的能取回
            assert.equal(w.earliestSample(), SR * 3);
            """
        )

    def test_future_span_returns_undefined(self) -> None:
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            w.append(pcm(0, SR));                           // 只有 0~1000ms
            assert.equal(w.slice(500, 1500), undefined, '超过已写入位置必须 undefined');
            assert.equal(w.slice(1000, 2000), undefined);
            """
        )

    def test_wraparound_span_is_reassembled_in_order(self) -> None:
        """跨环形首尾的区间必须按顺序拼回来，不能首尾颠倒。"""
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 2);
            w.append(pcm(0, SR * 3));                       // 容量 2 秒，写了 3 秒
            // 保留范围是 1000~3000ms，取 1500~2500ms 正好跨过物理首尾
            close(w.slice(1500, 2500), expected(Math.round(SR * 1.5), SR));
            """
        )

    def test_empty_and_inverted_spans_return_undefined(self) -> None:
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            w.append(pcm(0, SR * 2));
            assert.equal(w.slice(1000, 1000), undefined, '空区间');
            assert.equal(w.slice(1500, 1200), undefined, '倒置区间');
            assert.equal(w.slice(-100, 500), undefined, '负起点');
            assert.equal(w.slice(NaN, 500), undefined, 'NaN');
            """
        )

    def test_odd_byte_length_drops_the_partial_sample(self) -> None:
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            w.append(new ArrayBuffer(5));                   // 2 个完整样本 + 1 个半样本
            assert.equal(w.totalSamples(), 2);
            """
        )

    def test_appends_across_calls_are_contiguous(self) -> None:
        """分多次 append 必须拼成连续音频：运行时是按帧喂进来的。"""
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            for (let i = 0; i < 10; i++) w.append(pcm(i * 1600, 1600));   // 10 × 100ms
            close(w.slice(250, 750), expected(Math.round(SR * 0.25), SR / 2));
            assert.equal(w.totalSamples(), 16000);
            """
        )

    def test_reset_clears_everything(self) -> None:
        self.run_window(
            """
            const w = new DiarizationPcmWindow(SR, 5);
            w.append(pcm(0, SR * 2));
            w.reset();
            assert.equal(w.totalSamples(), 0);
            assert.equal(w.earliestSample(), 0);
            assert.equal(w.slice(0, 1000), undefined);
            """
        )

    def test_retain_default_covers_a_commit_chunk(self) -> None:
        """默认保留时长必须远大于 9.92 s 的块提交周期，否则收尾时轨道音频可能已被覆盖。"""
        self.run_window(
            """
            assert.ok(PCM_WINDOW_RETAIN_SECONDS >= 20,
                      `保留 ${PCM_WINDOW_RETAIN_SECONDS}s 不足以覆盖 9.92s 块提交与收尾`);
            """
        )


if __name__ == "__main__":
    unittest.main()
