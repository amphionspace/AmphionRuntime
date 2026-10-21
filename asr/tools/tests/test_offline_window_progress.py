"""Offline test-carrier progress must never use another session or skip windows."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / 'delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/OfflineWindowProgress.ts'


class OfflineProgressTest(unittest.TestCase):
    def test_slow_drain_is_not_stall_but_duplicates_cannot_hide_stall(self):
        script="""
import assert from 'node:assert/strict';
import {OfflineWindowProgress as P} from MODULE;
const p=new P('s');
const win=(s,n)=>JSON.stringify({sessionId:s,event:'DIARIZATION_LOCAL_WINDOW',fields:{historyChunks:n,windowStartSample:(n-1)*32000}});
assert.equal(p.stalled(0),false);
for(let n=1;n<=10;n++){p.observe(win('s',n));assert.equal(p.stalled(n*8000),false);}
assert.equal(p.stalled(139999),false);
p.observe(win('other',11));p.observe(win('s',10));
assert.equal(p.stalled(140000),true);
""".replace('MODULE',repr(MODULE.as_uri()))
        r=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_asr_must_drain_even_when_all_role_windows_are_done(self):
        script = """
import assert from 'node:assert/strict';
import {OfflineWindowProgress as P} from MODULE;
const p=new P('current');
const asr=(sessionId,n)=>JSON.stringify({sessionId,event:'DIARIZATION_ASR_PROCESSED',fields:{audioEndSample:n}});
for(let n=1;n<=11;n++)p.observe(JSON.stringify({sessionId:'current',event:'DIARIZATION_LOCAL_WINDOW',fields:{historyChunks:n,windowStartSample:(n-1)*32000}}));
assert.equal(p.canFeed(2000),false);
assert.equal(p.canFinish(2000),false);
p.observe(asr('old',640000));assert.equal(p.canFinish(2000),false);
p.observe(asr('current',320000));assert.equal(p.canFeed(2000),false);
p.observe(asr('current',640000));assert.equal(p.canFinish(2000),true);
p.observe(asr('current',320));assert.equal(p.canFinish(2000),true);
assert.throws(()=>p.observe(asr('current',NaN)));
""".replace('MODULE',repr(MODULE.as_uri()))
        result=subprocess.run(['node','--experimental-strip-types','--input-type=module','-e',script],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_session_order_and_delayed_progress(self):
        script = """
import assert from 'node:assert/strict';
import {OfflineWindowProgress as P} from MODULE;
const event=(s,n,start=(n-1)*32000)=>JSON.stringify({sessionId:s,
  event:'DIARIZATION_LOCAL_WINDOW',fields:{historyChunks:n,windowStartSample:start}});
for(const delay of [1,3,8]) {
  const p=new P('current');
  assert.equal(p.expectedFullWindows(999),0);
  assert.equal(p.expectedFullWindows(1000),1);
  assert.equal(p.expectedFullWindows(1001),1);
  assert.equal(p.expectedFullWindows(1100),2);
  p.observe(event('old',1)); assert.equal(p.completed,0);
  assert.throws(()=>p.observe(event('current',2)));
  assert.throws(()=>p.observe(event('current',1,1)));
  let fed=0;
  while(fed<7000) {
    p.observe(JSON.stringify({sessionId:'current',event:'DIARIZATION_ASR_PROCESSED',fields:{audioEndSample:fed*320}}));
    if(p.canFeed(fed)) fed+=100;
    else {
      const expected=p.expectedFullWindows(fed);
      assert.equal(expected-p.completed,8);
      for(let i=0;i<delay;i++) {
        const n=p.completed+1;p.observe(event('current',n));p.observe(event('current',n));
      }
    }
    assert(p.expectedFullWindows(fed)-p.completed<=8);
  }
  while(p.completed<p.expectedFullWindows(fed))p.observe(event('current',p.completed+1));
  assert.equal(p.completed,61);
}
""".replace('MODULE', repr(MODULE.as_uri()))
        result = subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
