"""Whole ASR sentences must not imply a single speaker when evidence disagrees."""
import unittest

from asr.tools.tests.test_harmony_diarization_identity_stability import run_session
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, TIMELINE, run_node


class HarmonyDiarizationSentenceOutputTest(unittest.TestCase):
    def test_whole_sentence_preserves_short_changes_overlap_and_unknown(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId,extra={{}})=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.8,...extra}});
          function sample(turns,endTime=1000,times=[100,700]) {{
            const s=new SpeakerDiarizationTranscriptState();
            s.addUtterance({{rawText:'张三',text:'张三。',tokens:['张','三'],
              tokenTimesMs:times,beginTime:0,endTime}});
            s.applySpeakerTurns(turns); return s;
          }}
          for(const turns of [
            [turn(0,600,'S1'),turn(600,1000,'S2')],
            [turn(0,250,'S1'),turn(250,270,'S2'),turn(270,1000,'S1')],
            [turn(0,1000,'S1',{{overlap:true,secondarySpeakerIds:['S2']}})],
            [turn(0,1000,'S1',{{overlap:true,secondarySpeakerIds:['UNKNOWN']}})],
            [turn(0,1000,'UNKNOWN')]
          ]) {{
            const s=sample(turns), before=s.allTurns(), result=s.sentenceUtterances();
            assert.equal(result.length,1); assert.equal(result[0].text,'张三。');
            assert.equal(result[0].rawText,'张三'); assert.equal(result[0].speakerId,'UNKNOWN');
            assert.equal(result[0].confidence,0); assert.equal(result[0].speakerInferred,false);
            assert.equal(s.currentAssignment('u1').speakerId,'UNKNOWN','provisional assignment cannot use majority');
            assert.deepEqual(s.allTurns(),before);
          }}
          const bounded=sample([turn(0,500,'S1'),turn(500,1000,'UNKNOWN')]);
          const fixed=bounded.sentenceUtterances()[0];
          assert.equal(fixed.speakerId,'S1'); assert.equal(fixed.speakerInferred,true);
          assert.equal(fixed.confidence,0);
          const long=sample([turn(0,200,'S1'),turn(200,1700,'UNKNOWN'),
            turn(1700,3200,'UNKNOWN'),turn(3200,4000,'S1')],4000,[100,3500]);
          assert.equal(long.sentenceUtterances()[0].speakerId,'UNKNOWN',
            'adjacent UNKNOWN cells cannot bypass the 2500 ms bound between tokens');
        """)

    def test_public_window_keeps_complete_sentences_and_commits_once(self):
        run_session("""
          const s=session();
          for(const [rawText,beginTime,endTime] of [['你好',0,1000],['张三',1000,2000],['嗯',2000,2300]])
            s.transcript.addUtterance({rawText,text:rawText+'。',tokens:[],tokenTimesMs:[],beginTime,endTime});
          const turns=[{beginTime:0,endTime:500,speakerId:'S1',secondarySpeakerIds:[]},
            {beginTime:500,endTime:1000,speakerId:'S2',secondarySpeakerIds:[]},
            {beginTime:1000,endTime:2000,speakerId:'S1',secondarySpeakerIds:[]},
            {beginTime:2000,endTime:2300,speakerId:'S2',secondarySpeakerIds:[]}];
          s.transcript.applySpeakerTurns(turns);s.totalSamples=2300*16;
          const payload={utteranceId:'u1'};s.decoratePayload(payload);
          assert.equal(payload.speakerIndex,-1);assert.deepEqual(payload.secondarySpeakerIndexes,[0,1]);
          const result=s.buildResult(0,undefined,2300,0);
          assert.deepEqual(result.utterances.map(x=>[x.text,x.speakerIndex]),
            [['你好。',-1],['张三。',0],['嗯。',1]]);
          assert.deepEqual(result.utterances[0].secondarySpeakerIndexes,[0,1]);
          const frozen=s.transcript.commitThrough(2300);
          s.transcript.applySpeakerRemap({S1:'S2'});
          assert.deepEqual(s.buildResult(0,undefined,2300,0).utterances,[]);
          assert.deepEqual(frozen.map(x=>x.speakerId),['UNKNOWN','S1','S2']);
          assert.deepEqual(result.speakerTurns.map(x=>x.speakerIndex),[0,1,0,1]);
        """)

    def test_caller_label_does_not_turn_participants_into_a_sentence_owner(self):
        demo = ROOT / 'delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets'
        source = demo.read_text()
        methods = source[source.index('  private speakerLabel('):source.index('  private refreshSpeakerDisplayIndexes(')]
        for annotation in ['private ', ': number', ': string', ': FinalSegment', '<number>']:
            methods = methods.replace(annotation, '')
        run_node('class Labels {\n' + methods + '}\n' + """
          import assert from 'node:assert/strict';
          const label=new Labels();
          const segment=(ids,overlap=false,speakerIndex=-1)=>({displaySpeakerIndex:speakerIndex,
            speakerParts:[{speakerIndex,secondarySpeakerIndexes:ids,overlap,speakerInferred:false}]});
          assert.equal(label.segmentSpeakerLabel(segment([0,1])),'多人／不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0])),'不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0],true)),'不确定 · 含重叠发言');
          assert.equal(label.segmentSpeakerLabel(segment([],false,0)),'说话人 1');
        """)


if __name__ == '__main__':
    unittest.main()
