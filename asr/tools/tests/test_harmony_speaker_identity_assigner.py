"""鸿蒙 SpeakerIdentityAssigner 的门禁：用 node 执行真实 TS，不另写一份实现。

用例与安卓 `SpeakerIdentityAssignerTest.kt` 一一对应，两端若走偏这里会红。
"""
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSIGNER = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerIdentityAssigner.ts"
ANDROID = (
    REPO_ROOT
    / "asr/android/sdk/src/main/java/com/amphion/asr/internal/SpeakerIdentityAssigner.kt"
)


class HarmonySpeakerIdentityAssignerTest(unittest.TestCase):
    def run_assigner(self, body: str) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerIdentityAssigner, IDENTITY_UNASSIGNED }} from {ASSIGNER.as_uri()!r};

            const dir = (...values) => Float32Array.from(values);
            {body}
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_distinct_voices_get_distinct_identities(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            assert.equal(a.assign(dir(1, 0, 0), 3).identity, 0);
            assert.equal(a.assign(dir(0, 1, 0), 3).identity, 1);
            assert.equal(a.assign(dir(0, 0, 1), 3).identity, 2);
            assert.equal(a.identityCount(), 3);
            """
        )

    def test_same_voice_returning_later_rejoins_its_identity(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            assert.equal(a.assign(dir(1, 0, 0), 3).identity, 0);
            assert.equal(a.assign(dir(0, 1, 0), 3).identity, 1);
            const again = a.assign(dir(0.98, 0.2, 0), 3);
            assert.equal(again.identity, 0);
            assert.ok(again.confidence > 0.9, 'confidence 应为余弦相似度');
            assert.equal(a.identityCount(), 2);
            """
        )

    def test_new_identity_reports_zero_confidence(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            assert.equal(a.assign(dir(1, 0, 0), 3).confidence, 0);
            """
        )

    def test_short_turns_are_left_unassigned_and_do_not_move_centroids(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            a.assign(dir(1, 0, 0), 3);
            const short = a.assign(dir(0, 1, 0), 0.3);
            assert.equal(short.identity, IDENTITY_UNASSIGNED);
            assert.equal(a.identityCount(), 1);
            assert.equal(a.assign(dir(1, 0, 0), 3).identity, 0);
            """
        )

    def test_cap_reached_merges_into_nearest_instead_of_creating(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(2);
            assert.equal(a.assign(dir(1, 0, 0), 3).identity, 0);
            assert.equal(a.assign(dir(0, 1, 0), 3).identity, 1);
            assert.equal(a.assign(dir(0.6, 0, 0.8), 3).identity, 0);
            assert.equal(a.identityCount(), 2);
            """
        )

    def test_embeddings_need_not_be_normalized_by_caller(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            assert.equal(a.assign(dir(3, 0, 0), 3).identity, 0);
            const scaled = a.assign(dir(17, 0, 0), 3);
            assert.equal(scaled.identity, 0);
            assert.ok(Math.abs(scaled.confidence - 1) < 1e-6);
            """
        )

    def test_reset_clears_identities(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            a.assign(dir(1, 0, 0), 3);
            a.assign(dir(0, 1, 0), 3);
            assert.equal(a.identityCount(), 2);
            a.reset();
            assert.equal(a.identityCount(), 0);
            assert.equal(a.assign(dir(0, 1, 0), 3).identity, 0);
            """
        )

    def test_zero_vector_does_not_crash(self) -> None:
        self.run_assigner(
            """
            const a = new SpeakerIdentityAssigner(4);
            const zero = a.assign(new Float32Array(192), 3);
            assert.equal(zero.identity, 0);
            assert.equal(zero.confidence, 0);
            assert.equal(a.assign(new Float32Array(0), 3).identity, IDENTITY_UNASSIGNED);
            """
        )

    def test_matches_host_reference_on_real_embeddings(self) -> None:
        """真实嵌入的跨端等价性：TS 实现必须与主机 python 参考逐条一致。

        固件是 111223-816（Sortformer 在它上面把同一人拆到两个槽位、又把另一人并进来，
        客户症状的原形）的 36 个逐槽位发言段，嵌入是真实 CAM++ 输出。主机那份 python 就是
        量出"留一标定 34/34、对照臂 28/34"的实现，所以这条保证发出去的和量过的是同一个算法。
        """
        fixture = REPO_ROOT / "asr/test-fixtures/speaker-identity/campplus_identity_parity.json"
        self.assertTrue(fixture.is_file(), "等价性固件缺失")
        self.run_assigner(
            f"""
            import {{ readFileSync }} from 'node:fs';
            const fx = JSON.parse(readFileSync({str(fixture)!r}, 'utf-8'));
            const a = new SpeakerIdentityAssigner(fx.maxSpeakers, fx.mergeThreshold,
                                                  fx.minAssignSeconds);
            assert.ok(fx.turns.length >= 30, 'fixture too small');
            fx.turns.forEach((t, i) => {{
              const d = a.assign(Float32Array.from(t.embedding), t.duration);
              assert.equal(d.identity, t.identity, `第 ${{i}} 段身份不一致`);
              assert.ok(Math.abs(d.confidence - t.confidence) < 1e-4,
                        `第 ${{i}} 段 confidence 不一致: ${{d.confidence}} vs ${{t.confidence}}`);
            }});
            """
        )

    def test_constants_match_across_platforms(self) -> None:
        """两端常量必须一致，否则同一段音频在安卓和鸿蒙会判出不同身份。"""
        harmony = ASSIGNER.read_text(encoding="utf-8")
        android = ANDROID.read_text(encoding="utf-8")
        for name_h, name_a, value in (
            ("IDENTITY_MERGE_THRESHOLD", "MERGE_THRESHOLD", "0.45"),
            ("IDENTITY_MIN_ASSIGN_SECONDS", "MIN_ASSIGN_SECONDS", "0.5"),
            ("IDENTITY_UNASSIGNED", "UNASSIGNED", "-1"),
        ):
            self.assertIn(f"{name_h}: number = {value}", harmony, name_h)
            self.assertIn(f"const val {name_a} = {value}", android, name_a)

    def test_commit_cycle_must_not_reset_identities(self) -> None:
        """质心按 120 s 提交周期重置会让身份每周期重新编号；两端注释都要留着这条警告。"""
        for path in (ASSIGNER, ANDROID):
            source = path.read_text(encoding="utf-8")
            self.assertIn("120 s", source, path.name)
            self.assertIn("整个会话", source, path.name)


if __name__ == "__main__":
    unittest.main()
