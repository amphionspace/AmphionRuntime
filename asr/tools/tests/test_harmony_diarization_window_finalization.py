"""Window publication is an irreversible speaker assignment boundary."""
import unittest
from asr.tools.tests.test_harmony_speaker_diarization_session import run_node, TIMELINE, DIARIZATION
from asr.tools.tests.test_harmony_community_diarization import run_community_session as run_session


class DiarizationWindowFinalizationTest(unittest.TestCase):
    def test_alignment_diagnostic_replays_original_tokens_without_changing_public_output(self):
        run_session("""
          async function replay(diagnostic) {
            const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
              onWindowResult(){},onFinished(){}},diagnostic);
            s.totalSamples=32000;
            const result={rawText:'张三你好',tokens:['张','三','你','好'],
              timestamps:[.1,.3,.8,1.2],isLast:false,audioEndSample:28000};
            const payload={result:'张三，你好。',beginTime:100,endTime:1700,isLast:false};
            s.observeAsrFinal(payload,result);
            return {payload,result,output:await s.commitWindow(2000,Infinity,true,0)};
          }
          const events=[],baseline=await replay(undefined);
          assert.deepEqual(await replay((event,fields)=>events.push({event,fields})),baseline);
          const f=events.find(e=>e.event==='DIARIZATION_ASR_ALIGNMENT').fields;
          assert.equal(f.utteranceId,baseline.payload.utteranceId);
          assert.equal(f.rawText,'张三你好');assert.equal(f.text,'张三，你好。');
          assert.deepEqual(f.tokens,['张','三','你','好']);
          assert.deepEqual(f.tokenTimesMs,[100,300,800,1200]);
          assert.equal(f.audioEndSample,28000);
          assert.deepEqual(await replay((event,fields)=>{
            if(event==='DIARIZATION_ASR_ALIGNMENT'){
              fields.tokens[0]='changed';fields.tokenTimesMs[0]=99999;
              throw new Error('sink failed');
            }
          }),baseline,'diagnostic mutation and failure cannot corrupt alignment or callbacks');
        """)

    def test_pending_sentence_window_freezes_without_cutting_the_next_sentence(self):
        run_session("""
          const published=[];
          const s=new SpeakerDiarizationSession({},'',4,{onSpeakerDiarizationUpdate(){},
            onWindowResult:r=>published.push(r),onFinished:r=>published.push(r)});
          s.totalSamples=180000*16;
          function sentence(begin,end,text,last=false) {
            const result={rawText:text,tokens:[text],timestamps:[begin/1000],isLast:last,audioEndSample:end*16};
            s.observeAsrFinal({result:text,beginTime:begin,endTime:end,isLast:last},result);
            if(!last)s.asrFinalDelivered(result);
          }
          s.client.cluster=async (segments)=>{
            const count=segments.length/(589*3),hard=Array(count*3).fill(-2);
            for(let i=0;i<count;i++)hard[i*3]=i<87?0:1;
            return {speakerCount:2,hard,turns:[[0,96320,0],[96320,180000,1]]};
          };
          sentence(0,30240,'甲句');sentence(30240,96320,'乙句');
          for(let i=0;i<113;i++)s.onWindow(window(i));
          s.asrAudioProcessed(120000*16);
          await new Promise(r=>setImmediate(r));
          assert.equal(published.length,0,'ASR progress alone cannot bypass acoustic lookahead');
          s.onWindow(window(113));
          await new Promise(r=>setImmediate(r));
          assert.equal(published.length,1);
          assert.equal(published[0].windowEndTime,96320);
          assert.equal(published[0].utterances.map(u=>u.text).join(''),'甲句乙句');
          const frozen=JSON.stringify(published[0]);
          for(let i=114;i<171;i++)s.onWindow(window(i));
          s.finishRequested=true;s.processDrained=true;
          sentence(96320,180000,'丙句',true);
          await new Promise(r=>setImmediate(r));
          assert.equal(published.length,2);
          assert.equal(JSON.stringify(published[0]),frozen);
          assert.equal(published[1].windowBeginTime,96320);
          assert.equal(published[1].isSessionFinal,true);
          assert.equal(published[1].utterances.map(u=>u.text).join(''),'丙句');
          assert.notEqual(published[0].speakerTurns[0].speakerIndex,published[1].speakerTurns[0].speakerIndex);
        """)

    def test_completed_sentences_publish_at_audio_deadline_during_a_long_next_sentence(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ DiarizationCommitClock }} from {(DIARIZATION/'DiarizationCommitClock.ts').as_uri()!r};
          const clock=new DiarizationCommitClock();
          clock.observeEndpoint(30240);
          clock.observeEndpoint(96320);
          clock.observeProcessedAudio?.(119980);
          assert.equal(clock.takeReady(Infinity),undefined,'do not commit before the audio deadline');
          clock.observeProcessedAudio?.(120000);
          assert.equal(clock.takeReady(122499),undefined,'retain the fixed acoustic lookahead');
          assert.deepEqual(clock.takeReady(122500),{{beginTime:0,endTime:96320,evidenceEndTime:122500}},
            'a long next sentence must not hide already completed sentences');
          assert.equal(clock.takeReady(Infinity),undefined,'publish each boundary once');
        """)

    def test_commit_clock_waits_for_fixed_evidence_cutoff_and_advances_five_hours(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ DiarizationCommitClock }} from {(DIARIZATION/'DiarizationCommitClock.ts').as_uri()!r};
          const clock = new DiarizationCommitClock();
          clock.observeProcessedAudio(119000);
          assert.equal(clock.takeReady(Infinity),undefined);
          clock.observeEndpoint(123000);
          clock.observeProcessedAudio(123000);
          assert.equal(clock.takeReady(124999),undefined);
          assert.deepEqual(clock.takeReady(125000),{{beginTime:0,endTime:123000,evidenceEndTime:125000}});
          assert.equal(clock.takeReady(Infinity),undefined);
          for(let end=243000;end<=18003000;end+=120000) {{
            clock.observeEndpoint(end);
            clock.observeProcessedAudio(end);
            assert.equal(clock.takeReady(end),undefined);
            const batch=clock.takeReady(end+2500);
            assert.equal(batch.beginTime,end-120000);
            assert.equal(batch.endTime,end);
          }}
        """)

    def test_commit_boundary_is_independent_of_asr_batching_and_model_delay(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ DiarizationCommitClock }} from {(DIARIZATION/'DiarizationCommitClock.ts').as_uri()!r};
          const expected=[{{beginTime:0,endTime:96320,evidenceEndTime:122500}},
            {{beginTime:96320,endTime:180000,evidenceEndTime:220000}}];
          function replay(batched,earlyModel) {{
            const clock=new DiarizationCommitClock(), outputs=[];
            function drain(progress) {{let result;while((result=clock.takeReady(progress))!==undefined) outputs.push(result);}}
            const events=[['endpoint',30240],['endpoint',96320],['progress',120000],
              ['endpoint',150000],['endpoint',180000],['progress',216320]];
            for(const [kind,time] of events) {{
              if(kind==='endpoint') clock.observeEndpoint(time);
              if(!batched || time===216320) clock.observeProcessedAudio(time);
              if(earlyModel) drain(Infinity);
            }}
            drain(Infinity);return outputs;
          }}
          for(const batching of [false,true]) for(const earlyModel of [false,true]) {{
            assert.deepEqual(replay(batching,earlyModel),expected);
          }}
          const noEndpoint=new DiarizationCommitClock();
          noEndpoint.observeProcessedAudio(300000);
          assert.equal(noEndpoint.takeReady(Infinity),undefined,'progress cannot invent a completed sentence');
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
