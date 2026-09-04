"""Window publication is an irreversible speaker assignment boundary."""
import unittest
from asr.tools.tests.test_harmony_speaker_diarization_session import run_node, TIMELINE, DIARIZATION


class DiarizationWindowFinalizationTest(unittest.TestCase):
    def test_commit_clock_waits_for_fixed_evidence_cutoff_and_advances_five_hours(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ DiarizationCommitClock }} from {(DIARIZATION/'DiarizationCommitClock.ts').as_uri()!r};
          const clock = new DiarizationCommitClock();
          clock.observeEndpoint(119000);
          assert.equal(clock.takeReady(Infinity),undefined);
          clock.observeEndpoint(123000);
          assert.equal(clock.takeReady(124999),undefined);
          assert.deepEqual(clock.takeReady(125000),{{beginTime:0,endTime:123000,evidenceEndTime:125000}});
          assert.equal(clock.takeReady(Infinity),undefined);
          for(let end=243000;end<=18003000;end+=120000) {{
            clock.observeEndpoint(end);
            assert.equal(clock.takeReady(end),undefined);
            const batch=clock.takeReady(end+2500);
            assert.equal(batch.beginTime,end-120000);
            assert.equal(batch.endTime,end);
          }}
        """)

    def test_distinct_committed_anchors_never_merge(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationGlobalClusterer }} from {(DIARIZATION/'SpeakerDiarizationGlobalClusterer.ts').as_uri()!r};
          const input=[{{embedding:[1,0],durationMs:2000,onlineSpeakerId:'UNKNOWN',anchorId:'S1'}},
            {{embedding:[.99,.01],durationMs:2000,onlineSpeakerId:'UNKNOWN',anchorId:'S2'}}];
          assert.equal(new SpeakerDiarizationGlobalClusterer().cluster(input).clusterCount,2);
        """)

    def test_published_utterance_cannot_be_revised_or_reissued(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state = new SpeakerDiarizationTranscriptState();
          const id = state.addUtterance({{rawText:'甲',text:'甲',tokens:['甲'],
            tokenTimesMs:[100],beginTime:0,endTime:1000}});
          state.applySpeakerTurns([{{beginTime:0,endTime:1000,speakerId:'S1',
            secondarySpeakerIds:[],evidenceKey:'old'}}]);
          const published = state.commitThrough?.(1000) ?? state.finalUtterances();
          assert.equal(published[0].speakerId, 'S1');
          const updates = state.applyEvidenceRemap({{old:'S2'}});
          assert.deepEqual(updates, [], 'a published utterance must never receive another update');
          assert.deepEqual(state.finalUtterances(), [], 'published text must leave the pending transcript');
          const next = state.addUtterance({{rawText:'乙',text:'乙',tokens:[],tokenTimesMs:[],
            beginTime:1100,endTime:1500}});
          assert.notEqual(next,id,'eviction must not reuse utterance IDs');
          assert.equal(published[0].speakerId,'S1');
        """)

    def test_unknown_is_frozen_and_cross_boundary_text_is_preserved(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state = new SpeakerDiarizationTranscriptState();
          state.addUtterance({{rawText:'二十三',text:'23',tokens:['二','十','三'],
            tokenTimesMs:[100,200,300],beginTime:0,endTime:400}});
          state.addUtterance({{rawText:'跨窗',text:'跨窗',tokens:[],tokenTimesMs:[],beginTime:500,endTime:1500}});
          const first = state.commitThrough(1000);
          assert.equal(first.length,1);
          assert.equal(first[0].text,'23');
          assert.equal(first[0].speakerId,'UNKNOWN');
          const second = state.commitThrough(2000);
          assert.equal(second.length,1);
          assert.equal(first[0].text+second[0].text,'23跨窗');
          assert.equal(second[0].sourceUtteranceId,'u2');
        """)
