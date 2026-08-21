import importlib.util
import re
import subprocess
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
POLICY = REPO_ROOT / (
    "asr/harmony/sdk/src/main/ets/com/amphion/asr/NativeEndpointTransitionPolicy.ts"
)
SHERPA_PATCH = REPO_ROOT / (
    "third_party/patches/sherpa-amphion/"
    "0016-fix-asr-report-native-endpoint-reasons.patch"
)
CHECKPOINT_PATCH = REPO_ROOT / (
    "third_party/patches/sherpa-amphion/"
    "0017-fix-asr-commit-rule3-segments-natively.patch"
)
CHECKPOINT_NORMALIZATION_PATCH = REPO_ROOT / (
    "third_party/patches/sherpa-amphion/"
    "0018-fix-asr-preserve-checkpoint-beam-normalization.patch"
)
DIAGNOSTIC = REPO_ROOT / "asr/tools/decode_streaming.py"


def load_diagnostic_module():
    spec = importlib.util.spec_from_file_location("rule3_decode_diagnostic", DIAGNOSTIC)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {DIAGNOSTIC}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HarmonyRule3EndpointTransitionTest(unittest.TestCase):
    def test_transition_policy_matrix(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ NativeEndpointTransition as Transition,
              NativeEndpointTransitionPolicy as Policy }} from {POLICY.as_uri()!r};

            assert.equal(Policy.decide(true, true), Transition.NATIVE_CHECKPOINT);
            assert.equal(Policy.decide(false, true), Transition.HARD_RESTART);
            assert.equal(Policy.decide(true, false), Transition.HARD_RESTART);
            """
        )
        subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_only_nonempty_native_rule3_preserves_stream(self) -> None:
        source = RUNTIME.read_text(encoding="utf-8")
        self.assertIn("OnlineEndpointReason", source)
        self.assertIn("this.recognizer.getEndpointReason(this.stream)", source)
        self.assertRegex(
            source,
            re.compile(
                r"NativeEndpointTransitionPolicy\.decide\([\s\S]*?"
                r"endpointReason === OnlineEndpointReason\.RULE3 && !isFinal,[\s\S]*?"
                r"endpointResult\.text\.length > 0 \|\| endpointResult\.tokens\.length > 0\)"
            ),
        )
        self.assertIn(
            "this.commitRule3Segment(endpointTransitionReason);",
            source,
        )
        self.assertIn("this.recognizer.commitRule3Segment(this.stream)", source)
        self.assertNotIn("nativeStreamSamplesAccepted", source)

    def test_sherpa_patch_exposes_internal_endpoint_reason(self) -> None:
        patch = SHERPA_PATCH.read_text(encoding="utf-8")

        self.assertIn("export enum OnlineEndpointReason", patch)
        self.assertIn("getEndpointReason(this.handle, stream.handle)", patch)
        self.assertIn("export const getEndpointReason:", patch)
        self.assertIn("EndpointReason::kRule1", patch)
        self.assertIn("EndpointReason::kRule2", patch)
        self.assertIn("EndpointReason::kRule3", patch)

    def test_sherpa_patch_exposes_internal_rule3_checkpoint(self) -> None:
        patch = CHECKPOINT_PATCH.read_text(encoding="utf-8")

        self.assertIn("CommitRule3Segment", patch)
        self.assertIn("commitRule3Segment(stream: OnlineStream): boolean", patch)
        self.assertIn('"commit_rule3_segment"', patch)
        self.assertIn("SherpaOnnxOnlineStreamCommitRule3Segment", patch)
        self.assertIn('"get_endpoint_reason"', SHERPA_PATCH.read_text(encoding="utf-8"))
        self.assertNotIn("rule3_reset_mode", patch)
        self.assertNotIn("replay", patch.lower())

        diagnostic = DIAGNOSTIC.read_text(encoding="utf-8")
        self.assertIn("recognizer.commit_rule3_segment(stream)", diagnostic)
        self.assertNotIn("rule3_reset_mode", diagnostic)

        normalization_patch = CHECKPOINT_NORMALIZATION_PATCH.read_text(
            encoding="utf-8"
        )
        self.assertIn("length_normalization_offset", normalization_patch)
        self.assertIn(
            "ModifiedBeamPreservesLengthNormalizedRanking",
            normalization_patch,
        )

    def test_diagnostic_reports_the_first_boundary_token_divergence(self) -> None:
        diagnostic = load_diagnostic_module()
        oracle = {
            "committed_tokens": ["before", "我", "after"],
            "committed_timestamps": [59.9, 60.04, 60.2],
            "events": [],
        }
        soft = {
            "transition": "soft",
            "committed_tokens": ["before", "我", "after"],
            "committed_timestamps": [59.9, 60.04, 60.2],
            "events": [{"kind": "ENDPOINT"}],
        }
        fresh = {
            "transition": "fresh",
            "committed_tokens": ["before", "after"],
            "committed_timestamps": [59.9, 60.2],
            "events": [{"kind": "ENDPOINT"}],
        }
        checkpoint = dict(
            soft, transition="checkpoint", checkpoint_committed_count=1
        )

        self.assertTrue(
            diagnostic.compare_with_continuous(oracle, soft)["matches_continuous"]
        )
        mismatch = diagnostic.compare_with_continuous(oracle, fresh)
        self.assertFalse(mismatch["matches_continuous"])
        self.assertEqual(mismatch["first_diff_index"], 1)
        self.assertEqual(mismatch["oracle_token"], "我")
        self.assertEqual(mismatch["candidate_token"], "after")
        self.assertEqual(mismatch["decoder_frame"], 1501)
        self.assertTrue(
            diagnostic.transition_gate_passes(
                [
                    diagnostic.compare_with_continuous(oracle, soft),
                    mismatch,
                    diagnostic.compare_with_continuous(oracle, checkpoint),
                ]
            )
        )

        broken_checkpoint = dict(checkpoint, committed_tokens=["before", "after"])
        self.assertFalse(
            diagnostic.transition_gate_passes(
                [diagnostic.compare_with_continuous(oracle, broken_checkpoint)]
            )
        )

        soft_without_endpoint = dict(soft, events=[])
        unexercised = diagnostic.compare_with_continuous(
            oracle, soft_without_endpoint
        )
        self.assertEqual(unexercised["endpoint_count"], 0)
        self.assertFalse(diagnostic.transition_gate_passes([unexercised]))
        self.assertFalse(diagnostic.transition_gate_passes([]))
        checkpoint_without_commit = dict(
            checkpoint, checkpoint_committed_count=0
        )
        checkpoint_without_commit_comparison = (
            diagnostic.compare_with_continuous(
                oracle, checkpoint_without_commit
            )
        )
        self.assertFalse(
            diagnostic.transition_gate_passes(
                [checkpoint_without_commit_comparison]
            )
        )
        self.assertFalse(
            diagnostic.transition_gate_passes(
                [diagnostic.compare_with_continuous(oracle, checkpoint)], 4
            )
        )
        checkpoint_with_extra_restart = dict(
            checkpoint,
            checkpoint_committed_count=4,
            non_rule3_hard_restart_count=1,
            events=[{"kind": "ENDPOINT"}] * 5,
        )
        self.assertFalse(
            diagnostic.transition_gate_passes(
                [diagnostic.compare_with_continuous(
                    oracle, checkpoint_with_extra_restart
                )],
                4,
            )
        )

    def test_fixed_pcm_exercises_all_transition_paths(self) -> None:
        diagnostic = load_diagnostic_module()

        class FakeResult:
            def __init__(self, text, tokens, timestamps):
                self.text = text
                self.tokens = tokens
                self.timestamps = timestamps

        class FakeStream:
            def __init__(self, recognizer, generation):
                self.recognizer = recognizer
                self.generation = generation
                self.ready = False
                self.finished = False

            def accept_waveform(self, _sample_rate, samples):
                self.recognizer.total_samples += len(samples)
                self.ready = True

            def input_finished(self):
                self.finished = True
                self.ready = True

        class FakeRecognizer:
            def __init__(self):
                self.total_samples = 0
                self.stream_generation = 0
                self.endpoint_consumed = False

            def create_stream(self):
                self.stream_generation += 1
                if self.stream_generation > 1:
                    self.endpoint_consumed = True
                return FakeStream(self, self.stream_generation)

            @staticmethod
            def is_ready(stream):
                return stream.ready

            @staticmethod
            def decode_stream(stream):
                stream.ready = False

            def is_endpoint(self, stream):
                return (
                    not stream.finished
                    and not self.endpoint_consumed
                    and self.total_samples >= 20
                )

            def get_endpoint_reason(self, stream):
                return diagnostic.ENDPOINT_REASON_RULE3 if self.is_endpoint(stream) else 0

            def reset(self, _stream):
                self.endpoint_consumed = True

            def commit_rule3_segment(self, _stream):
                self.endpoint_consumed = True
                return True

            def get_result_all(self, stream):
                if not stream.finished and self.is_endpoint(stream):
                    return FakeResult("before", ["before"], [0.04])
                if not stream.finished:
                    return FakeResult("", [], [])
                if stream.generation > 1:
                    return FakeResult("after", ["after"], [0.08])
                if self.endpoint_consumed:
                    return FakeResult("我 after", ["我", "after"], [0.04, 0.08])
                return FakeResult(
                    "before 我 after",
                    ["before", "我", "after"],
                    [0.04, 0.08, 0.12],
                )

            def get_result(self, stream):
                return self.get_result_all(stream).text

        args = SimpleNamespace(warmup_ms=0, chunk_ms=100)
        samples = [0.0] * 30
        runs = {
            transition: diagnostic.streaming_decode(
                FakeRecognizer(), samples, 100, args, transition
            )
            for transition in ("continuous", "soft", "fresh", "checkpoint")
        }
        soft = diagnostic.compare_with_continuous(
            runs["continuous"], runs["soft"]
        )
        fresh = diagnostic.compare_with_continuous(
            runs["continuous"], runs["fresh"]
        )
        checkpoint = diagnostic.compare_with_continuous(
            runs["continuous"], runs["checkpoint"]
        )

        self.assertTrue(soft["matches_continuous"])
        self.assertEqual(soft["endpoint_count"], 1)
        self.assertFalse(fresh["matches_continuous"])
        self.assertEqual(fresh["endpoint_count"], 1)
        self.assertEqual(fresh["oracle_token"], "我")
        self.assertEqual(fresh["candidate_token"], "after")
        self.assertTrue(checkpoint["matches_continuous"])
        self.assertEqual(checkpoint["endpoint_count"], 1)
        self.assertEqual(checkpoint["checkpoint_committed_count"], 1)
        self.assertTrue(diagnostic.transition_gate_passes([soft, fresh, checkpoint]))

    def test_checkpoint_hard_restarts_non_rule3_endpoint(self) -> None:
        diagnostic = load_diagnostic_module()

        class FakeResult:
            text = ""
            tokens = []
            timestamps = []

        class FakeStream:
            def __init__(self, recognizer, generation):
                self.recognizer = recognizer
                self.generation = generation
                self.ready = False
                self.finished = False

            def accept_waveform(self, _sample_rate, _samples):
                self.ready = True

            def input_finished(self):
                self.finished = True
                self.ready = True

        class Rule1Recognizer:
            def __init__(self):
                self.generation = 0
                self.checkpoint_calls = 0

            def create_stream(self):
                self.generation += 1
                return FakeStream(self, self.generation)

            @staticmethod
            def is_ready(stream):
                return stream.ready

            @staticmethod
            def decode_stream(stream):
                stream.ready = False

            @staticmethod
            def is_endpoint(stream):
                return not stream.finished and stream.generation == 1

            @staticmethod
            def get_endpoint_reason(stream):
                return 1 if not stream.finished and stream.generation == 1 else 0

            @staticmethod
            def get_result_all(_stream):
                return FakeResult()

            @staticmethod
            def get_result(_stream):
                return ""

            def commit_rule3_segment(self, _stream):
                self.checkpoint_calls += 1
                return False

        recognizer = Rule1Recognizer()
        args = SimpleNamespace(warmup_ms=0, chunk_ms=100)
        run = diagnostic.streaming_decode(
            recognizer, [0.0] * 30, 100, args, "checkpoint"
        )

        self.assertEqual(recognizer.generation, 2)
        self.assertEqual(recognizer.checkpoint_calls, 0)
        self.assertEqual(run["events"][0]["endpoint_reason"], 1)
        self.assertEqual(run["checkpoint_committed_count"], 0)
        comparison = diagnostic.compare_with_continuous(run, run)
        self.assertTrue(comparison["matches_continuous"])
        self.assertFalse(diagnostic.transition_gate_passes([comparison]))

    def test_boundary_prefix_gate_uses_the_first_nonempty_terminal_after_rule3(self) -> None:
        diagnostic = load_diagnostic_module()
        run = {
            "events": [
                {"kind": "PARTIAL", "text": "ignored"},
                {"kind": "ENDPOINT", "text": "before"},
                {"kind": "ENDPOINT", "text": ""},
                {"kind": "FINAL", "text": "一二三四五六七八九"},
            ]
        }

        self.assertEqual(
            diagnostic.first_nonempty_terminal_after_endpoint(run),
            "一二三四五六七八九",
        )
        self.assertTrue(
            diagnostic.boundary_prefix_matches(run, "一二三四五六七")
        )
        self.assertFalse(diagnostic.boundary_prefix_matches(run, "五六七"))
        self.assertFalse(
            diagnostic.boundary_prefix_matches(
                {"events": [{"kind": "ENDPOINT", "text": "before"}]},
                "一二三四五六七",
            )
        )

    def test_boundary_prefix_gate_rejects_non_checkpoint_single_route(self) -> None:
        completed = subprocess.run(
            [
                "python3",
                str(DIAGNOSTIC),
                "--model-dir",
                "missing-model",
                "--wav",
                "missing.wav",
                "--endpoint-transition",
                "soft",
                "--expected-after-first-endpoint-prefix",
                "一二三四五六七",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn(
            "requires --endpoint-transition checkpoint or --compare-transitions",
            completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
