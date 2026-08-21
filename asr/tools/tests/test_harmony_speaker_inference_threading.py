import re
import subprocess
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
RUNTIME = REPO_ROOT / "asr/harmony/sdk/src/main/ets/com/amphion/asr/Runtime.ets"
SPEAKER_ID = (
    REPO_ROOT
    / "third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/ets/"
    "components/SpeakerIdentification.ets"
)
SPEAKER_NATIVE = (
    REPO_ROOT
    / "third_party/sherpa-onnx/harmony-os/SherpaOnnxHar/sherpa_onnx/src/main/cpp/"
    "speaker-identification.cc"
)
TURN_NATIVE = REPO_ROOT / "asr/harmony/sdk/src/main/cpp/speaker_turn_segmenter.cpp"
LANE = (
    REPO_ROOT
    / "asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerInferenceLane.ts"
)
TS_LOADER = REPO_ROOT / "asr/tools/tests/ts_extension_loader.mjs"


def method_body(source: str, name: str) -> str:
    match = re.search(
        rf"\b(?:private|public|protected)\s+(?:async\s+)?{name}\s*\([^)]*\)[^{{]*\{{",
        source,
    )
    if match is None:
        raise AssertionError(f"method {name} not found")
    start = match.end()
    depth = 1
    index = start
    while index < len(source) and depth:
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
        index += 1
    if depth != 0:
        raise AssertionError(f"method {name} has unbalanced braces")
    return source[start : index - 1]


class HarmonySpeakerInferenceThreadingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RUNTIME.read_text(encoding="utf-8")

    def test_native_speaker_inference_has_async_leased_workers(self) -> None:
        speaker_api = SPEAKER_ID.read_text(encoding="utf-8")
        speaker_native = SPEAKER_NATIVE.read_text(encoding="utf-8")
        turn_native = TURN_NATIVE.read_text(encoding="utf-8")
        self.assertIn("computeAsync(stream: OnlineStream)", speaker_api)
        self.assertIn("SpeakerEmbeddingExtractorComputeAsyncWorker", speaker_native)
        self.assertIn("extractor_handle->Lease()", speaker_native)
        self.assertIn("stream_handle->Lease()", speaker_native)
        self.assertIn("ProcessAsync", turn_native)
        self.assertIn("context->model = g_model", turn_native)

    def test_slow_inference_lane_is_fifo_and_vad_clock_is_independent(self) -> None:
        script = textwrap.dedent(
            f"""
            import assert from 'node:assert/strict';
            import {{ SpeakerInferenceLane }} from {LANE.as_uri()!r};

            const lane = new SpeakerInferenceLane();
            const generation = lane.generation();
            const applied = [];
            let audioClockMs = 0;
            let endpointAudioMs = -1;
            for (let i = 0; i < 8; i++) {{
              audioClockMs += 500;
              if (audioClockMs >= 3600 && endpointAudioMs < 0) endpointAudioMs = audioClockMs;
              if (audioClockMs >= 1500) {{
                const deadline = audioClockMs;
                lane.submit(generation, async () => {{
                  await new Promise(resolve => setTimeout(resolve, 20));
                  return deadline;
                }}, value => applied.push(value));
              }}
            }}
            assert.equal(endpointAudioMs, 4000);
            assert.equal(applied.length, 0, 'PCM/VAD loop waited for slow inference');
            await lane.drain(generation);
            assert.deepEqual(applied, [1500, 2000, 2500, 3000, 3500, 4000]);

            lane.submit(generation, async () => 4500, value => applied.push(value));
            lane.invalidate();
            await lane.drain();
            assert.deepEqual(applied, [1500, 2000, 2500, 3000, 3500, 4000]);
            """
        )
        subprocess.run(
            [
                "node",
                "--experimental-strip-types",
                "--experimental-loader",
                TS_LOADER.as_uri(),
                "--input-type=module",
                "-e",
                script,
            ],
            check=True,
            cwd=REPO_ROOT,
        )

    def test_async_public_final_does_not_synchronously_enter_speaker_onnx(self) -> None:
        drain = method_body(self.runtime, "processDecodedResultAsync")
        prepare = method_body(self.runtime, "prepareVadEndpointSpeakerScoreAsync")
        score = method_body(self.runtime, "scoreSamplesAsync")
        self.assertIn("await this.speakerInferenceLane.drain", drain)
        self.assertIn("await this.prepareVadEndpointSpeakerScoreAsync", drain)
        self.assertIn("await this.scoreSamplesAsync", prepare)
        self.assertIn("await extractor.computeAsync", score)
        self.assertNotIn(".compute(", score)

    def test_trailing_silence_vad_does_not_wait_for_speaker_or_decode(self) -> None:
        body = method_body(self.runtime, "feedChunkAndDecodeAsync")
        vad = body.find("advanceVadGate")
        speaker = body.find("enqueueSpeakerVadInference")
        decode = body.find("await this.feedRecognizerAsync")
        self.assertGreaterEqual(vad, 0, "async audio path must advance VAD explicitly")
        self.assertGreaterEqual(speaker, 0, "speaker inference must use its serial lane")
        self.assertGreaterEqual(decode, 0, "async decode call missing")
        self.assertLess(vad, speaker, "trailing-silence VAD waits for speaker inference")
        self.assertLess(vad, decode, "trailing-silence VAD waits for ASR decode")
        self.assertNotIn("await this.enqueueSpeakerVadInference", body)

    def test_async_runtime_path_never_calls_sync_speaker_inference(self) -> None:
        enqueue = method_body(self.runtime, "enqueueSpeakerVadInference")
        resolver = method_body(self.runtime, "resolveSpeakerTurnSplitAsync")
        self.assertNotIn("scoreSamples(", enqueue)
        self.assertNotIn("processSpeakerTurnSegmentation(", resolver)
        self.assertIn("processSpeakerTurnSegmentationAsync(", resolver)

    def test_async_endpoint_and_finish_never_enter_sync_clean_decode(self) -> None:
        feed = method_body(self.runtime, "feedChunkAndDecodeAsync")
        finish = method_body(self.runtime, "stopNowAsync")
        endpoint = method_body(self.runtime, "triggerSpeakerVadEndpointAsync")
        vad_endpoint = method_body(self.runtime, "finalizeAnnouncedVadEndpointAsync")
        commit = method_body(self.runtime, "commitCleanSpeakerTurnAsync")
        replay = method_body(self.runtime, "replaySpeakerSuffixAsync")

        self.assertIn("await this.triggerSpeakerVadEndpointAsync()", feed)
        self.assertIn("await this.finalizeAnnouncedVadEndpointAsync()", feed)
        self.assertIn("await this.commitSpeakerTurnAtFinishAsync()", finish)
        self.assertIn("await this.commitCleanSpeakerTurnAsync", endpoint)
        self.assertIn("await this.commitCleanSpeakerTurnAsync", vad_endpoint)
        self.assertIn("await this.recognizer.decodeAsync(prefixStream)", commit)
        self.assertNotIn("this.recognizer.decode(prefixStream)", commit)
        self.assertIn("await this.replaySpeakerSuffixAsync(split)", commit)
        self.assertIn("await this.drainAsync(true, false, true)", commit)
        self.assertIn("await this.feedChunkAndDecodeAsync", replay)


if __name__ == "__main__":
    unittest.main()
