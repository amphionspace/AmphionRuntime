"""Exercise production inference sample selection without native model loading."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationEmbeddingSamplesTest(unittest.TestCase):
    def test_complementary_model_uses_identical_context_and_run_pcm_and_closes(self):
        source = SOURCE.read_text()
        source = source[source.index('const SAMPLE_RATE:'):]
        driver = """
        import assert from 'node:assert/strict';
        const samples=Float32Array.from({length:160000},(_,i)=>i/160000);
        const segments=[{startSample:0,endSample:48000,speaker:0,speakerMask:1},
          {startSample:64000,endSample:104000,speaker:0,speakerMask:1},
          {startSample:112000,endSample:144000,speaker:0,speakerMask:3}];
        async function processSpeakerTurnSegmentationAsync(){return segments;}
        const primary=[],complementary=[];let closed=0,streams=0;
        function extractor(consumed,vector){return {
          createStream(){streams++;return {acceptWaveform(w){this.samples=w.samples;},close(){streams--;}};},
          isReady(){return true;},
          async computeAsync(stream){consumed.push(stream.samples);return new Float32Array(vector);},
          close(){closed++;}
        };}
        const inference=new SpeakerDiarizationInference();
        inference.extractor=extractor(primary,[1,0]);
        inference.complementaryExtractor=extractor(complementary,[0,1]);
        const result=await inference.process(samples,80000,144000);
        assert.equal(primary.length,3,'primary context, owned query and run query');
        assert.equal(complementary.length,2,'complementary context and run query only');
        assert.deepEqual(complementary[0],primary[0]);
        assert.deepEqual(complementary[1],primary[2]);
        assert.deepEqual(complementary[1],samples.slice(64000,104000));
        assert.deepEqual(result.embeddings[0].complementaryEmbedding,[0,1]);
        assert.deepEqual(result.segments[1].complementaryEmbedding,[0,1]);
        assert.equal(result.segments[0].complementaryEmbedding,undefined);
        assert.equal(result.segments[2].complementaryEmbedding,undefined,'overlap cannot acquire a single-person query');
        assert.equal(streams,0);
        inference.close();inference.close();assert.equal(closed,2);
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'complementary-samples.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)

    def test_owned_fragments_query_their_complete_speech_run_without_mixing_other_runs(self):
        source = SOURCE.read_text()
        source = source[source.index('const SAMPLE_RATE:'):]
        driver = """
        import assert from 'node:assert/strict';
        const samples = Float32Array.from({length: 160000}, (_, i) => i / 160000);
        const segments = [
          {startSample:0,endSample:48000,speaker:0,speakerMask:1},
          {startSample:64000,endSample:104000,speaker:0,speakerMask:1},
          {startSample:112000,endSample:128000,speaker:0,speakerMask:3},
          {startSample:132000,endSample:140000,speaker:1,speakerMask:2},
        ];
        async function processSpeakerTurnSegmentationAsync() { return segments; }
        const inference = new SpeakerDiarizationInference();
        const consumed=[];
        inference.extractor={};
        inference.computeEmbedding=async pcm=>{
          consumed.push(pcm);return Float32Array.from([pcm[0],pcm.at(-1)]);
        };
        const result=await inference.process(samples,96000,144000);
        assert.equal(result.segments[0].queryEmbedding,undefined,'historical-only run is not queried');
        assert.deepEqual(result.segments[1].queryEmbedding,[samples[64000],samples[103999]],
          'a 500ms owned fragment can use its enclosing 2.5s run, without earlier speaker PCM');
        assert.equal(result.segments[2].queryEmbedding,undefined,'overlap cannot become single-person evidence');
        assert.equal(result.segments[3].queryEmbedding,undefined,'insufficient actual speech remains unqueried');
        assert.deepEqual(consumed.at(-1),samples.slice(64000,104000));
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'run-query-samples.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)

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
        // Loudness admission must measure precisely the PCM used for this
        // speaker's profile, excluding the other channel and overlapping speech.
        for (let i = 0; i < 2; i++) {
          const expected = Math.sqrt(consumed[i].reduce((sum, x) => sum + x*x, 0) / consumed[i].length);
          assert.ok(Math.abs(result.embeddings[i].speechRms - expected) < 1e-8);
        }
        // The endpoint's later clean speech must contribute to its speaker identity.
        assert.equal(consumed[0].at(-1), samples[143999]);
        assert.deepEqual(result.segments.map(s => ({startSample:s.startSample,endSample:s.endSample,
          speaker:s.speaker,speakerMask:s.speakerMask})), segments);
        assert.ok(result.segments.every(s=>s.queryEmbedding===undefined));
        """
        with tempfile.TemporaryDirectory() as directory:
            harness = Path(directory) / 'embedding-samples.mts'
            harness.write_text(source + driver)
            subprocess.run(['node', '--experimental-strip-types', str(harness)], check=True, cwd=ROOT)
