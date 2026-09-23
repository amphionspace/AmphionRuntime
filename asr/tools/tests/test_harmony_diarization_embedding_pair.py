"""Independent model work must preserve values and quiescence in either order."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/ets/com/amphion/asr/SpeakerDiarizationInference.ets'


class HarmonyDiarizationEmbeddingPairTest(unittest.TestCase):
    def test_replica_load_failure_closes_created_models_and_success_closes_once(self):
        self.run_pair("""
class SpeakerEmbeddingExtractorConfig {}
const AmphionRuntime={getOrCreateSpeakerTurnSegmenterAsync:async()=>{}};
let failAt=4,created=0,closed=0;
const SpeakerEmbeddingExtractor={createAsync:async()=>{
  created++;if(created===failAt) throw new Error('model allocation failed');
  return {close(){closed++;}};
}};
let inference=new SpeakerDiarizationInference();
await assert.rejects(inference.load({resourceManager:{}},'/primary','/secondary'),/model load failed/);
assert.equal(closed,3);inference.close();assert.equal(closed,3);
failAt=-1;created=0;closed=0;inference=new SpeakerDiarizationInference();
await inference.load({resourceManager:{}},'/primary','/secondary');
inference.close();inference.close();assert.equal(closed,4);
""")

    def test_parallel_failures_report_first_cell_in_original_serial_order(self):
        self.run_pair("""
const inference=new SpeakerDiarizationInference();
inference.extractor={};inference.localQueryExtractor={};inference.complementaryExtractor={};inference.localComplementaryExtractor={};
const early=new Error('first cell secondary failure'),later=new Error('later cell primary failure');
inference.computeEmbedding=async (samples,model)=>{
  if(model===inference.complementaryExtractor){
    await new Promise(resolve=>setTimeout(resolve,3));throw early;
  }
  if(samples[0]===3) throw later;
  return Float32Array.of(samples[0]);
};
await assert.rejects(inference.computeLocalEmbeddings([1,2,3].map(x=>Float32Array.of(x))),
  error=>error===early,'error selection follows original PCM order, not queue or completion order');
""")

    def test_local_cells_keep_original_order_with_four_independent_queues(self):
        self.run_pair("""
for (const delays of [[8,1,3],[1,8,3]]) {
  function model(tag,delay) {
    const state={live:0,maxLive:0,seen:[],createStream(){
      state.live++;state.maxLive=Math.max(state.maxLive,state.live);
      return {acceptWaveform(w){this.pcm=w.samples;},close(){state.live--;}};
    },isReady(){return true;},async computeAsync(stream){
      state.seen.push(stream.pcm[0]);
      await new Promise(resolve=>setTimeout(resolve,delay));
      return Float32Array.of(tag,stream.pcm[0]);
    }};return state;
  }
  const inference=new SpeakerDiarizationInference();
  const a=model(1,delays[0]), b=model(1,delays[1]), c=model(2,delays[2]), d=model(2,delays[0]);
  inference.extractor=a;inference.localQueryExtractor=b;inference.complementaryExtractor=c;inference.localComplementaryExtractor=d;
  const result=await inference.computeLocalEmbeddings([1,2,3,4,5].map(x=>Float32Array.of(x)));
  assert.deepEqual(result.map(x=>[...x.primary,...x.complementary]),
    [1,2,3,4,5].map(x=>[1,x,2,x]));
  assert.deepEqual(a.seen,[1,3,5]);assert.deepEqual(b.seen,[2,4]);assert.deepEqual(c.seen,[1,3,5]);assert.deepEqual(d.seen,[2,4]);
  for(const m of [a,b,c,d]) {assert.equal(m.maxLive,1);assert.equal(m.live,0);}
}
""")

    def test_local_failure_waits_for_all_native_queues(self):
        self.run_pair("""
const a=extractor(),b=extractor(),c=extractor(),d=extractor(),inference=new SpeakerDiarizationInference();
inference.extractor=a.model;inference.localQueryExtractor=b.model;inference.complementaryExtractor=c.model;inference.localComplementaryExtractor=d.model;
let settled=false;const failure=new Error('local primary failed');
const work=inference.computeLocalEmbeddings([pcm,pcm,pcm]).then(
  ()=>assert.fail('cannot publish partial local evidence'),error=>{settled=true;return error;});
a.reject(failure);await flush();assert.equal(settled,false);
c.resolve(Float32Array.of(2));await flush();assert.equal(settled,false);
b.resolve(Float32Array.of(1));await flush();assert.equal(settled,false);
d.resolve(Float32Array.of(2));assert.equal(await work,failure);
assert.equal(a.model.live+b.model.live+c.model.live+d.model.live,0);
""")

    def test_identical_channel_and_run_reuse_only_within_one_window(self):
        self.run_pair("""
let segments=[];
async function processSpeakerTurnSegmentationAsync(){ return segments; }
const windowPcm=Float32Array.from({length:160000},(_,i)=>Math.sin(i*.003)*.3);
async function run(ranges, reuse, repetitions=1) {
  segments=ranges.map(([startSample,endSample])=>({startSample,endSample,speaker:0,speakerMask:1}));
  const calls=[];
  const inference=new SpeakerDiarizationInference();
  inference.extractor={};inference.complementaryExtractor={};
  if(!reuse) inference.sameSamples=()=>false;
  inference.computeEmbedding=async (samples,model=inference.extractor)=>{
    calls.push([model===inference.extractor?'a':'b',samples.length]);
    return Float32Array.of(samples.length,samples[0],samples.at(-1));
  };
  let result;
  for(let i=0;i<repetitions;i++) result=await inference.process(windowPcm,96000,136000,0);
  result.inferenceMs=0;return {result,calls};
}
const contiguous=[[0,160000]];
const baseline=await run(contiguous,false), current=await run(contiguous,true);
assert.deepEqual(current.result,baseline.result,'identical evidence must preserve all public fields');
assert.equal(current.calls.filter(x=>x[0]==='a'&&x[1]===96000).length,1,
  'same channel/run PCM must not repeat primary inference');
assert.equal(current.calls.filter(x=>x[0]==='b'&&x[1]===96000).length,1);
const repeated=await run(contiguous,true,2);
assert.equal(repeated.calls.filter(x=>x[0]==='a'&&x[1]===96000).length,2,
  'results cannot cross a window boundary');
const separated=[[0,48000],[64000,160000]];
const gaps=await run(separated,true), gapsReference=await run(separated,false);
assert.deepEqual(gaps.result,gapsReference.result);
assert.equal(gaps.calls.filter(x=>x[0]==='a'&&x[1]===96000).length,2,
  'equal length with different PCM must remain independent');
""")

    def run_pair(self, body):
        source = SOURCE.read_text()
        setup = """
import assert from 'node:assert/strict';
const flush = async () => { for (let i=0; i<12; i++) await Promise.resolve(); };
function extractor() {
  let resolve, reject;
  const promise = new Promise((yes,no) => { resolve=yes; reject=no; });
  const model = { live:0, samples:undefined,
    createStream() { model.live++; return {
      acceptWaveform(wave) { model.samples=wave.samples; }, close() { model.live--; }
    }; }, isReady() { return true; }, computeAsync() { return promise; }
  };
  return {model,resolve,reject};
}
const pcm=Float32Array.of(.1,-.2,.3);
"""
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'pair.mts'
            script.write_text(source[source.index('const SAMPLE_RATE:'):] + setup + body)
            subprocess.run(['node', '--experimental-strip-types', str(script)], check=True)

    def test_both_completion_orders_preserve_model_values_and_pcm(self):
        self.run_pair("""
for (const secondaryFirst of [true,false]) {
  const a=extractor(), b=extractor(), inference=new SpeakerDiarizationInference();
  inference.extractor=a.model; inference.complementaryExtractor=b.model;
  let published=false;
  const work=inference.computeEmbeddingPair(pcm).then(value=>{published=true;return value;});
  const primary=Float32Array.of(1,2), secondary=Float32Array.of(3,4);
  (secondaryFirst?b:a).resolve(secondaryFirst?secondary:primary);
  await flush(); assert.equal(published,false);
  (secondaryFirst?a:b).resolve(secondaryFirst?primary:secondary);
  assert.deepEqual(await work,{primary,complementary:secondary});
  assert.deepEqual(a.model.samples,pcm); assert.deepEqual(b.model.samples,pcm);
  assert.equal(a.model.live+b.model.live,0);
}
""")

    def test_error_waits_for_other_model_and_preserves_primary_failure(self):
        self.run_pair("""
for (const primaryFailsFirst of [true,false]) {
  const a=extractor(), b=extractor(), inference=new SpeakerDiarizationInference();
  inference.extractor=a.model; inference.complementaryExtractor=b.model;
  let settled=false;
  const work=inference.computeEmbeddingPair(pcm).then(
    ()=>assert.fail('failed model must not publish a pair'),error=>{settled=true;return error;});
  const primaryError=new Error('primary failure'), secondaryError=new Error('secondary failure');
  (primaryFailsFirst?a:b).reject(primaryFailsFirst?primaryError:secondaryError);
  await flush(); assert.equal(settled,false,'native work still owns the other stream');
  (primaryFailsFirst?b:a).reject(primaryFailsFirst?secondaryError:primaryError);
  assert.equal(await work,primaryError);
  assert.equal(a.model.live+b.model.live,0);
}
""")

    def test_absent_complementary_model_keeps_primary_only_behavior(self):
        self.run_pair("""
const a=extractor(), inference=new SpeakerDiarizationInference();inference.extractor=a.model;
const work=inference.computeEmbeddingPair(pcm), primary=Float32Array.of(1,2);
a.resolve(primary);assert.deepEqual(await work,{primary});assert.equal(a.model.live,0);
""")

    def test_window_matches_serial_values_under_opposite_model_delays(self):
        self.run_pair("""
async function processSpeakerTurnSegmentationAsync() {
  return [{startSample:0,endSample:160000,speaker:0,speakerMask:1}];
}
function deterministicModel(tag,delay) {
  return {createStream() { return {
      acceptWaveform(wave) { this.pcm=wave.samples; }, close() {}
    }; }, isReady() { return true; }, async computeAsync(stream) {
      await new Promise(resolve=>setTimeout(resolve,delay));
      return Float32Array.of(tag,stream.pcm.length,stream.pcm[0],stream.pcm.at(-1));
    }
  };
}
async function window(serial,delays) {
  const inference=new SpeakerDiarizationInference();
  inference.extractor=deterministicModel(1,delays[0]);
  inference.complementaryExtractor=deterministicModel(2,delays[1]);
  inference.localQueryExtractor=deterministicModel(1,delays[1]);
  inference.localComplementaryExtractor=deterministicModel(2,delays[0]);
  inference.speakerLevelReference=1;
  if(serial) inference.computeEmbeddingPair=async samples=>({
    primary:await inference.computeEmbedding(samples),
    complementary:await inference.computeEmbedding(samples,inference.complementaryExtractor)
  });
  if(serial) inference.computeLocalEmbeddings=async samples=>{
    const pairs=[];
    for(const pcm of samples) pairs.push(await inference.computeEmbeddingPair(pcm));
    return pairs;
  };
  const samples=Float32Array.from({length:160000},(_,i)=>Math.sin(i)*.01);
  const result=await inference.process(samples,96000,136000,320000);
  assert.ok(result.segments[0].localQueries.length>0,'exercise quiet local evidence');
  result.inferenceMs=0;return result;
}
const reference=await window(true,[0,0]);
for(const delays of [[0,2],[2,0]]) assert.deepEqual(await window(false,delays),reference);
""")
