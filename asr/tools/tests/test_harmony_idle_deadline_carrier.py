"""Exercise the real idle carrier across timeout decisions and delayed completion."""
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CARRIER = ROOT / "delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/util/DeviceStressTest.ets"


class HarmonyIdleDeadlineCarrierTest(unittest.TestCase):
    def run_case(self, deadline_frames, completion_delay, expected):
        source = CARRIER.read_text()
        method = "async function runVoiceprintVadBeginIdleCycle(" + source.split(
            "async function runVoiceprintVadBeginIdleCycle(", 1
        )[1].split("\nasync function runSpeakerVadOnStartCycle", 1)[0]
        script = f"""
import assert from 'node:assert/strict';
const FRAME_BYTES=640, FRAME_DURATION_MS=20, IDLE_FRAME_PACE_MS=30;
const START_TIMEOUT_MS=10000, COMPLETE_TIMEOUT_MS=30000;
let now=0, writes=0, completeAt=Infinity, listener;
Date.now=()=>now;
class SessionEvents {{
  starts=0; finals=0; lastFinals=0; finalChars=0; speechBegins=0; completes=0; errors=0;
}}
class StressListener {{ constructor(events) {{ this.events=events; }} }}
const sleep=async ms=>{{
  now+=ms;
  if(now>=completeAt) {{
    Object.assign(listener.events,{{finals:1,lastFinals:1,completes:1}});
  }}
}};
const waitFor=async (pred, timeout)=>{{
  const until=now+timeout;
  while(!pred() && now<until) await sleep(10);
  return pred();
}};
const startParams=()=>({{extraParams:{{}}}});
const finishCycle=(_index,_id,events,_startedAt,ok,detail)=>({{ok,detail,...events}});
const engine={{
  setListener(value){{listener=value;}},
  startListening(){{listener.events.starts=1;}},
  writeAudio(){{
    writes++;
    if(writes==={deadline_frames}) completeAt=now+{completion_delay};
  }},
  isBusy(){{return listener.events.completes===0;}},
}};
{method}
for (const index of [0,1]) {{
  now=0; writes=0; completeAt=Infinity;
  const result=await runVoiceprintVadBeginIdleCycle(engine,{{id:'fixture'}},index,'registered');
  assert.equal(result.ok,{str(expected).lower()},JSON.stringify(result));
  if(result.ok) assert.equal(writes,50,'deadline must not require additional PCM');
}}
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "idle.mts"
            path.write_text(script)
            subprocess.run(["node", "--experimental-strip-types", str(path)], check=True)

    def test_completion_delay_does_not_change_audio_deadline(self):
        for delay in (450, 700):
            with self.subTest(delay=delay):
                self.run_case(50, delay, True)

    def test_timeout_before_deadline_is_rejected(self):
        self.run_case(49, 500, False)

    def test_timeout_requiring_extra_audio_is_rejected(self):
        self.run_case(51, 500, False)


if __name__ == "__main__":
    unittest.main()
