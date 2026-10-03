"""Production executor cancellation and native ownership regressions."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, DIARIZATION, TS_LOADER
from asr.tools.tests.community_pcm_host import native_normalizer_prelude, production_normalizer_wrapper

CLIENT = DIARIZATION / 'SpeakerDiarizationLocalClient.ets'


def run_client(checks):
    source = CLIENT.read_text()
    source = source[source.index('export class SpeakerDiarizationStorageError'):]
    harness = native_normalizer_prelude() + f"""
import assert from 'node:assert/strict';
import {{ DiarizationWindowScheduler }} from {(DIARIZATION / 'DiarizationWindowScheduler.ts').as_uri()!r};
import {{ SpeakerDiarizationRuntimeLeaseRegistry }} from {(DIARIZATION / 'SpeakerDiarizationRuntimeLease.ts').as_uri()!r};
const SAMPLE_RATE=16000, WINDOW_SAMPLES=160000, INFERENCE_TIMEOUT_MS=10000;
let nextDiarizationJobId=1;
const SpeakerDiarizationDegradedReason={{MODEL_UNAVAILABLE:2,INFERENCE_UNAVAILABLE:3,
  INFERENCE_TIMEOUT:4,STORAGE_UNAVAILABLE:5}};
function deferred() {{ let resolve, reject; const promise=new Promise((yes,no)=>{{resolve=yes;reject=no;}});
  return {{promise,resolve,reject}}; }}
const tick=async()=>{{ for(let i=0;i<40;i++) await Promise.resolve(); }};
const timers=new Map(); let timerId=0;
globalThis.setTimeout=fn=>{{ const id=++timerId; timers.set(id,fn); return id; }};
globalThis.clearTimeout=id=>timers.delete(id);
const expire=()=>{{ const pending=[...timers.values()]; timers.clear(); pending.forEach(fn=>fn()); }};
let loadGate;
const instances=[];
class CommunityDiarizationInference {{
  {production_normalizer_wrapper()}
  static DEFAULT_THREADS=4;
  processes=[]; clusters=[]; cancelled=false; closed=false;
  constructor() {{ instances.push(this); }}
  async load() {{ if(loadGate) await loadGate.promise; }}
  process() {{ const pending=deferred(); this.processes.push(pending); return pending.promise; }}
  cluster() {{ const pending=deferred(); this.clusters.push(pending); return pending.promise; }}
  cancel() {{ this.cancelled=true; }}
  close() {{ this.closed=true; }}
  finishCancellation() {{
    if(!this.cancelled) return;
    for(const pending of [...this.processes,...this.clusters]) pending.reject(new Error('native cancelled'));
  }}
}}
class DiarizationPcmSpool {{
  end=0;
  append(audio) {{ this.end+=audio.byteLength; }}
  read(offset,count) {{ assert.ok(offset+count<=this.end); return new ArrayBuffer(count); }}
  endOffset() {{ return this.end; }} discardBefore() {{}} close() {{}} remove() {{}}
}}
class DiarizationEvidenceSpool {{ close() {{}} remove() {{}} }}
const fs={{accessSync:()=>true,rmdirSync(){{}}}};
{source}
function setup() {{
  const events=[],lease=SpeakerDiarizationRuntimeLeaseRegistry.acquire();
  const client=new SpeakerDiarizationLocalClient({{}},'',{{
    onWindow:window=>events.push(['window',window]),
    onDrained:()=>events.push(['drained']),
    onDegraded:(reason,message)=>events.push(['degraded',reason,message])
  }});
  return {{client,native:instances.at(-1),events,lease}};
}}
{checks}
"""
    with tempfile.TemporaryDirectory() as directory:
        script = Path(directory) / 'cancel.mts'
        script.write_text(harness)
        subprocess.run(['node', '--experimental-strip-types', '--experimental-loader',
                        TS_LOADER.as_uri(), str(script)], cwd=ROOT, check=True, timeout=20)


class HarmonyDiarizationCancellationTest(unittest.TestCase):
    def test_pcm_normalization_failure_degrades_without_native_work_or_storage_error(self):
        run_client("""
const {client,native,events,lease}=setup();
client.spool.read=()=>new ArrayBuffer(160001*2);
client.append(new ArrayBuffer(10*32000)); await tick();
assert.equal(native.processes.length,0,'invalid PCM must fail before process is queued');
assert.equal(client.activeJob,undefined);
assert.equal(events.length,1);
assert.equal(events[0][0],'degraded');
assert.equal(events[0][1],SpeakerDiarizationDegradedReason.INFERENCE_UNAVAILABLE);
assert.match(events[0][2],/sample limit/);
client.cancel(()=>lease.release()); await tick();
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
""")

    def test_timeout_itself_stops_work_and_drains_without_cleanup(self):
        run_client("""
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(12*32000)); client.finish(); await tick();
expire(); await tick();
native.finishCancellation(); await tick();
assert.deepEqual(events.map(e=>e[0]),['degraded','drained'],
  'timeout must stop work without relying on a later cancel/cleanup call');
assert.equal(events[0][1],SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(native.processes.length,1);
assert.equal(native.closed,false,'draining alone does not release session ownership');
client.cleanup(()=>lease.release());
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
""")

    def test_timeout_stops_native_work_and_releases_only_after_it_exits(self):
        run_client("""
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(12*32000)); client.finish(); await tick();
assert.equal(native.processes.length,1);
expire(); await tick();
assert.equal(events.filter(e=>e[0]==='degraded').length,1);
assert.equal(events[0][1],SpeakerDiarizationDegradedReason.INFERENCE_TIMEOUT);
assert.equal(events.filter(e=>e[0]==='drained').length,0);
let released=false;
client.cleanup(()=>{released=true;lease.release();});
assert.equal(native.closed,false,'timeout cannot destroy an active model');
assert.equal(released,false);
native.finishCancellation(); await tick();
assert.equal(released,true,'timeout must stop native work so teardown can finish');
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
assert.equal(native.processes.length,1,'queued windows cannot run after timeout');
assert.equal(events.filter(e=>e[0]==='window').length,0);
""")

    def test_cancel_while_loading_never_starts_process_or_cluster(self):
        run_client("""
loadGate=deferred();
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(10*32000));
const cluster=client.cluster(new Float32Array(0),new Float32Array(0),4,new Float64Array(0),0)
  .then(()=>assert.fail('cancelled cluster must reject'),()=>{});
client.cancel(()=>lease.release()); await tick();
assert.equal(native.closed,false);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),true);
loadGate.resolve(); await tick(); await cluster;
assert.equal(native.processes.length,0,'cancelled session must not start work after load');
assert.equal(native.clusters.length,0);
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
assert.deepEqual(events,[]);
""")

    def test_timeout_while_loading_cannot_start_late_inference(self):
        run_client("""
loadGate=deferred();
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(10*32000)); client.finish(); await tick();
expire(); await tick();
assert.equal(events.filter(e=>e[0]==='degraded').length,1);
loadGate.resolve(); await tick();
assert.equal(native.processes.length,0,'late load cannot resurrect a timed-out job');
assert.equal(events.filter(e=>e[0]==='drained').length,1);
client.cleanup(()=>lease.release()); await tick();
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
""")

    def test_cancel_retains_lease_until_process_and_cluster_both_exit(self):
        run_client("""
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(10*32000)); await tick();
const cluster=client.cluster(new Float32Array(0),new Float32Array(0),4,new Float64Array(0),0).catch(()=>{});
await tick();
assert.equal(native.processes.length,1); assert.equal(native.clusters.length,1);
client.cancel(()=>lease.release());
assert.equal(native.cancelled,true,'cancel must reach both in-flight operations');
native.processes[0].resolve({segments:new Float32Array(0),embeddings:new Float32Array(0)});
await tick();
assert.equal(native.closed,false,'clustering still owns the model');
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),true);
native.finishCancellation(); await cluster; await tick();
assert.equal(native.closed,true);
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
assert.deepEqual(events,[],'cancel suppresses late success and timeout');
""")

    def test_already_quiescent_cleanup_notifies_every_waiter_once(self):
        run_client("""
const {client,native,events,lease}=setup(); await tick();
let first=0, second=0, third=0;
client.cancel(()=>{first++;lease.release();});
assert.equal(native.closed,true); assert.equal(first,1);
client.cleanup(()=>second++); client.cancel(()=>third++);
assert.deepEqual([first,second,third],[1,1,1],'closed client must acknowledge new waiters');
assert.equal(SpeakerDiarizationRuntimeLeaseRegistry.hasActiveLeases(),false);
assert.deepEqual(events,[]);
""")

    def test_degraded_client_rejects_further_cluster_work(self):
        run_client("""
const {client,native,events,lease}=setup();
client.append(new ArrayBuffer(10*32000)); await tick();
expire(); await tick();
const rejected=client.cluster(new Float32Array(0),new Float32Array(0),4,new Float64Array(0),0)
  .then(()=>false,()=>true);
await tick();
assert.equal(native.clusters.length,0,'degraded client must reject new compute');
assert.equal(await rejected,true);
client.cleanup(()=>lease.release()); native.finishCancellation(); await tick();
assert.equal(native.closed,true);
""")


if __name__ == '__main__':
    unittest.main()
