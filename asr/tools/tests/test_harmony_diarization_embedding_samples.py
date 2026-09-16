"""Exercise production inference sample selection without native model loading."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationEmbeddingSamplesTest(unittest.TestCase):
    def test_retains_later_speech_and_excludes_overlap_and_other_speakers(self):
        source = SOURCE.read_text()
        source = source[source.index('const SAMPLE_RATE:'):]
        driver = """
        import assert from 'node:assert/strict';
        const samples = Float32Array.from({length: 160000}, (_, i) => i / 160000);
        const segments = [
          {startSample: 0, endSample: 48000, speaker: 0, speakerMask: 1},
          {startSample: 48000, endSample: 64000, speaker: 0, speakerMask: 3},
          {startSample: 64000, endSample: 96000, speaker: 1, speakerMask: 2},
          {startSample: 96000, endSample: 144000, speaker: 0, speakerMask: 1},
        ];
        async function processSpeakerTurnSegmentationAsync() { return segments; }
        const consumed = [];
        const inference = new SpeakerDiarizationInference();
        inference.extractor = {
          createStream() { return {acceptWaveform(wave) { this.samples = wave.samples; }, close() {}}; },
          isReady() { return true; },
          async computeAsync(stream) { consumed.push(stream.samples); return new Float32Array([1, 0]); },
        };
        const result = await inference.process(samples);
        assert.deepEqual(result.embeddings.map(e => [e.localSpeaker, e.speechSamples]), [[0, 96000], [1, 32000]]);
        assert.deepEqual(consumed[0], Float32Array.from([...samples.slice(0, 48000), ...samples.slice(96000, 144000)]));
        assert.deepEqual(consumed[1], samples.slice(64000, 96000));
        // The endpoint's later clean speech must contribute to its speaker identity.
        assert.equal(consumed[0].at(-1), samples[143999]);
        assert.deepEqual(result.segments.map(s => ({...s})), segments);
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'embedding-samples.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)
