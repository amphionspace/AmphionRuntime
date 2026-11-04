"""鸿蒙 SpeakerIdentityResolver 的门禁：用 node 执行真实 TS，嵌入函数用假的注入。

重点钉三件：
- Sortformer 按槽位报 runs，resolver 必须按**起始时间**重排后再分配（分配器是增量的）
- 取不到音频 / 嵌入失败时必须留"未赋身份"，不猜
- 返回的身份数组与入参同序（调用方要写回对应的 track）
"""
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DIARIZATION = REPO_ROOT / "asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao/diarization"
RESOLVER = DIARIZATION / "SpeakerIdentityResolver.ets"
ASSIGNER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerIdentityAssigner.ts"
WINDOW = DIARIZATION / "DiarizationPcmWindow.ts"


class HarmonySpeakerIdentityResolverTest(unittest.TestCase):
    def run_resolver(self, body: str) -> None:
        # node ESM 要求显式扩展名，且副本不在原目录时相对导入解析不到，
        # 所以把两个导入都换成绝对 file URI。
        source = (
            RESOLVER.read_text(encoding="utf-8")
            .replace("from 'amphion_asr'", f"from {ASSIGNER.as_uri()!r}")
            .replace("from './DiarizationPcmWindow'", f"from {WINDOW.as_uri()!r}")
        )
        patched = REPO_ROOT / "asr/harmony/sdk-dingqiao/build" / "SpeakerIdentityResolver.node.ts"
        patched.parent.mkdir(parents=True, exist_ok=True)
        patched.write_text(source, encoding="utf-8")
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerIdentityResolver, IDENTITY_UNRESOLVED }} from {patched.as_uri()!r};

            const SR = 16000;
            const silence = (ms) => new ArrayBuffer(Math.round(SR * ms / 1000) * 2);
            /** 假嵌入器：按该段音频的第一个样本值返回一个方向，便于控制相似度。 */
            const byFirstSample = (samples) => {{
              const key = Math.round(samples[0] * 32768);
              const v = new Float32Array(3);
              if (key === 1) v[0] = 1; else if (key === 2) v[1] = 1; else v[2] = 1;
              return v;
            }};
            {body}
            """
        )
        try:
            subprocess.run(
                ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
                check=True,
                cwd=REPO_ROOT,
            )
        finally:
            patched.unlink(missing_ok=True)

    def test_identities_follow_arrival_order_not_slot_order(self) -> None:
        """Sortformer 按槽位报 runs；若不按起始时间重排，编号会跟着槽位顺序跑偏。"""
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => Float32Array.from([1, 0, 0]));
            r.appendAudio(silence(10000));
            // 入参刻意按槽位排：槽位 1 的段在前，但它在时间上更晚
            const ids = r.resolve([[5000, 6000, 1], [1000, 2000, 0]]);
            assert.equal(ids.length, 2);
            // 同一个方向 -> 同一个身份；关键是两者都被分配且返回同序
            assert.equal(ids[0], 0);
            assert.equal(ids[1], 0);
            assert.equal(r.identityCount(), 1);
            """
        )

    def test_distinct_voices_in_one_slot_become_distinct_identities(self) -> None:
        """客户症状的修法：同在槽位 0 的两个人必须分成两个身份。"""
        self.run_resolver(
            """
            let call = 0;
            const alternating = () => {
              call += 1;
              return call === 1 ? Float32Array.from([1, 0, 0]) : Float32Array.from([0, 1, 0]);
            };
            const r = new SpeakerIdentityResolver(SR, 4, alternating);
            r.appendAudio(silence(10000));
            const ids = r.resolve([[1000, 3000, 0], [5000, 7000, 0]]);
            assert.notEqual(ids[0], ids[1], '两个人不能并成一个身份');
            assert.equal(r.identityCount(), 2);
            """
        )

    def test_evicted_audio_leaves_identity_unresolved(self) -> None:
        """音频被环形缓冲覆盖时必须留"未赋身份"，不能拿错位音频算嵌入。"""
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => Float32Array.from([1, 0, 0]), 2);
            r.appendAudio(silence(5000));            // 只留最后 2 秒
            const ids = r.resolve([[0, 1000, 0], [3500, 4500, 0]]);
            assert.equal(ids[0], IDENTITY_UNRESOLVED, '已覆盖的段必须未赋身份');
            assert.equal(ids[1], 0, '仍在窗内的段应被分配');
            assert.equal(r.audioMissCount(), 1);
            """
        )

    def test_embed_failure_leaves_identity_unresolved(self) -> None:
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => undefined);
            r.appendAudio(silence(5000));
            const ids = r.resolve([[1000, 3000, 0]]);
            assert.equal(ids[0], IDENTITY_UNRESOLVED);
            assert.equal(r.embedFailureCount(), 1);
            assert.equal(r.identityCount(), 0, '嵌入失败不得开出身份');
            """
        )

    def test_empty_embedding_is_treated_as_failure(self) -> None:
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => new Float32Array(0));
            r.appendAudio(silence(5000));
            assert.equal(r.resolve([[1000, 3000, 0]])[0], IDENTITY_UNRESOLVED);
            assert.equal(r.embedFailureCount(), 1);
            """
        )

    def test_short_turn_is_left_unresolved_by_the_assigner(self) -> None:
        """短于最小时长的段由分配器判为未赋身份；resolver 不绕过它。"""
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => Float32Array.from([1, 0, 0]));
            r.appendAudio(silence(5000));
            const ids = r.resolve([[1000, 1300, 0]]);   // 0.3 s < 0.5 s
            assert.equal(ids[0], IDENTITY_UNRESOLVED);
            assert.equal(r.identityCount(), 0);
            // 取到了音频、嵌入也成功，所以两个诊断计数都应为 0
            assert.equal(r.audioMissCount(), 0);
            assert.equal(r.embedFailureCount(), 0);
            """
        )

    def test_reset_clears_identities_and_audio(self) -> None:
        self.run_resolver(
            """
            const r = new SpeakerIdentityResolver(SR, 4, () => Float32Array.from([1, 0, 0]));
            r.appendAudio(silence(5000));
            r.resolve([[1000, 3000, 0]]);
            assert.equal(r.identityCount(), 1);
            r.reset();
            assert.equal(r.identityCount(), 0);
            assert.equal(r.resolve([[1000, 3000, 0]])[0], IDENTITY_UNRESOLVED,
                         'reset 后音频也应清空');
            """
        )

    def test_embedding_input_is_capped_but_duration_gate_uses_the_whole_turn(self) -> None:
        """嵌入只取前 3 秒，但最小时长判定必须按**整段**时长。

        否则一个 10 秒的段被截成 3 秒后仍应被分配，而不是因为"看起来短"被丢。
        实测：截到 3 s 仍 34/34，单段从 1136 KB 降到 188 KB；1 s 才掉到 32/34。
        """
        self.run_resolver(
            """
            let longest = 0;
            const probe = (samples) => {
              longest = Math.max(longest, samples.length);
              return Float32Array.from([1, 0, 0]);
            };
            const r = new SpeakerIdentityResolver(SR, 4, probe);
            r.appendAudio(silence(20000));
            // 一个 10 秒的段
            const ids = r.resolve([[1000, 11000, 0]]);
            assert.equal(ids[0], 0, '10 秒的段必须被分配，不能因为截断而当成短段');
            assert.equal(longest, SR * 3, `送入嵌入的样本数应为 3 秒，实际 ${longest}`);
            """
        )

    def test_turn_shorter_than_the_cap_is_passed_whole(self) -> None:
        self.run_resolver(
            """
            let seen = 0;
            const probe = (samples) => { seen = samples.length; return Float32Array.from([1, 0, 0]); };
            const r = new SpeakerIdentityResolver(SR, 4, probe);
            r.appendAudio(silence(10000));
            r.resolve([[1000, 2500, 0]]);          // 1.5 秒 < 3 秒上限
            assert.equal(seen, SR * 1.5, '短于上限的段应整段送入');
            """
        )

    def test_timing_constraint_is_documented(self) -> None:
        """收尾路径余量只剩约 300 ms，嵌入必须会话期间算完；注释要留着这条约束。"""
        source = RESOLVER.read_text(encoding="utf-8")
        self.assertIn("会话期间", source)
        self.assertIn("2000 ms", source)


if __name__ == "__main__":
    unittest.main()
