"""Whole ASR sentences must not imply a single speaker when evidence disagrees."""
import unittest

from asr.tools.tests.test_harmony_community_diarization import run_community_session as run_session
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, TIMELINE, run_node


class HarmonyDiarizationSentenceOutputTest(unittest.TestCase):
    def test_original_u6_punctuation_cannot_change_bounded_tail_inference(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='可以听见我说话吗你好';
          const tokens=['▁ƌİŕ','▁Ƌšŋ','▁ƌıŒ','▁ƏōĢ','▁ƍĩĴ','▁ƏŕŚ','▁Əŕł','▁ƌıĺ','▁ƋţŅ','▁ƌŋţ'];
          const times=[19700,19740,19820,19900,20020,20140,20300,20460,20660,20860];
          for(const text of ['可以听见我说话吗？你好。','可以听见我说话吗你好。']) {{
            const s=new State();s.addUtterance({{rawText:raw,text,tokens,tokenTimesMs:times,
              beginTime:19700,endTime:20860}});
            s.applySpeakerTurns([{{beginTime:19600,endTime:20652.21875,speakerId:'S1',
              secondarySpeakerIds:[],confidence:.9}}]);
            const acoustic=JSON.stringify(s.allTurns());
            const out=s.sentenceUtterances();
            assert.equal(out.map(x=>x.text).join(''),text);
            assert.ok(out.every(x=>x.speakerId==='S1'),'same raw utterance permits bounded tail inference across punctuation');
            assert.ok(out.some(x=>x.speakerInferred),'missing acoustic coverage is inference, never direct attribution');
            assert.ok(out.filter(x=>x.speakerInferred).every(x=>x.confidence===0));
            assert.equal(JSON.stringify(s.allTurns()),acoustic);
            const frozen=s.commitThrough(20860);s.applySpeakerRemap({{S1:'S2'}});
            assert.deepEqual(frozen,out);assert.deepEqual(s.sentenceUtterances(),[]);
          }}
        """)

    def test_punctuation_replacing_english_space_preserves_speaker_boundaries(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='HELLO WORLD YES THANK YOU', text='HELLO WORLD。YES。THANK YOU。';
          const turn=(beginTime,endTime,speakerId,extra={{}})=>({{beginTime,endTime,speakerId,secondarySpeakerIds:[],...extra}});
          const sample=(turns,display=text)=>{{const s=new State();s.addUtterance({{rawText:raw,text:display,tokens:['▁HELLO','▁WORLD','▁YES','▁THANK','▁YOU'],tokenTimesMs:[0,100,200,300,400],beginTime:0,endTime:500}});s.applySpeakerTurns(turns);return s;}};
          const turns=[turn(0,200,'S1'),turn(200,300,'S2'),turn(300,500,'S1')];
          const s=sample(turns),before=s.allTurns(),out=s.sentenceUtterances();
          assert.deepEqual(out.map(x=>[x.text,x.speakerId]),[['HELLO WORLD。','S1'],['YES。','S2'],['THANK YOU。','S1']]);
          assert.equal(out.map(x=>x.rawText).join(''),raw);assert.equal(out.map(x=>x.text).join(''),text);assert.deepEqual(s.allTurns(),before);
          assert.equal(new Set(out.map(x=>x.utteranceId)).size,3);assert(out.every(x=>!x.speakerInferred));
          const overlap=sample([turns[0],turns[1],turn(300,400,'S1'),turn(400,450,'S1',{{overlap:true,secondarySpeakerIds:['UNKNOWN']}}),turn(450,500,'S1')]).sentenceUtterances();
          assert.deepEqual(overlap.map(x=>[x.text,x.speakerId]),[['HELLO WORLD。','S1'],['YES。','S2'],['THANK YOU。','UNKNOWN']]);assert(overlap[2].overlap);
          const lexical=sample(turns,'HELLOWORLD。YES。THANK YOU。').sentenceUtterances();assert.equal(lexical.length,1);assert.equal(lexical[0].speakerId,'UNKNOWN','deleting an inter-word space without replacement punctuation remains unaligned');
          const trailing=new State();trailing.addUtterance({{rawText:'HELLO ',text:'HELLO。',tokens:[...'HELLO '],tokenTimesMs:[0,0,0,0,0,100],beginTime:0,endTime:200}});trailing.applySpeakerTurns([turn(0,200,'S1')]);assert.equal(trailing.sentenceUtterances().length,1);assert.equal(trailing.sentenceUtterances()[0].text,'HELLO。');
          const frozen=s.commitThrough(500);s.applySpeakerRemap({{S1:'S3'}});assert.deepEqual(frozen,out);assert.equal(s.sentenceUtterances().length,0);
        """)

    def test_presentation_changes_leave_original_assignment_and_uncertainty_unchanged(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId,extra={{}})=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9,...extra}});
          const cases=[
            [turn(0,200,'S1'),turn(200,400,'S2'),turn(400,800,'S1')],
            [turn(0,200,'S1'),turn(200,400,'UNKNOWN'),turn(400,800,'S2')],
            [turn(0,200,'S1'),turn(200,800,'UNKNOWN')],
            [turn(0,200,'S1',{{overlap:true,secondarySpeakerIds:['UNKNOWN']}}),turn(200,800,'UNKNOWN')],
            [turn(0,200,'S1',{{overlap:true,secondarySpeakerIds:['S2']}}),turn(200,800,'UNKNOWN')],
            [turn(0,200,'S1'),turn(210,230,'S2'),turn(230,800,'UNKNOWN')],
            [turn(0,800,'UNKNOWN')]
          ];
          for(const turns of cases) {{
            let reference;
            for(const text of ['甲乙丙丁','甲？乙。丙，丁。','甲乙！丙丁。']) {{
              const s=new State();s.addUtterance({{rawText:'甲乙丙丁',text,tokens:[...'甲乙丙丁'],
                tokenTimesMs:[0,200,400,600],beginTime:0,endTime:800}});s.applySpeakerTurns(turns);
              const source=s.sourceAssignments(s.utterances[0]);
              if(reference)assert.deepEqual(source,reference);else reference=source;
              const before=JSON.stringify(s.allTurns()),out=s.sentenceUtterances();
              assert.equal(out.map(x=>x.text).join(''),text);
              assert.equal(out.map(x=>x.rawText).join(''),'甲乙丙丁');
              assert.equal(JSON.stringify(s.allTurns()),before);
              if(source.some(x=>x.speakerInferred))assert.ok(out.some(x=>x.speakerInferred),
                'display aggregation must retain inference even when its summary is UNKNOWN');
            }}
          }}
          for(const gap of [2500,2501]) {{
            const s=new State();s.addUtterance({{rawText:'甲乙',text:'甲。乙。',tokens:['甲','乙'],
              tokenTimesMs:[100,500],beginTime:0,endTime:500+gap}});
            s.applySpeakerTurns([turn(0,499,'S1')]);
            const source=s.sourceAssignments(s.utterances[0]);
            assert.equal(source.at(-1).speakerId,gap===2500?'S1':'UNKNOWN');
            assert.equal(!!source.at(-1).speakerInferred,gap===2500);
          }}
        """)

    def test_punctuated_endpoint_keeps_supported_sentence_owners(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const text='先讨论方案。张三说明结论。嗯。', raw='先讨论方案张三说明结论嗯';
          const turn=(beginTime,endTime,speakerId)=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}});
          function sample(turns) {{
            const s=new State();
            s.addUtterance({{rawText:raw,text,tokens:[...raw],
              tokenTimesMs:[...raw].map((_,i)=>i*100),beginTime:0,endTime:1200}});
            s.applySpeakerTurns(turns);return s;
          }}
          const s=sample([turn(0,500,'S1'),turn(500,1100,'S2'),turn(1100,1200,'S1')]);
          const before=s.allTurns(), result=s.sentenceUtterances();
          assert.deepEqual(result.map(x=>[x.text,x.speakerId]),
            [['先讨论方案。','S1'],['张三说明结论。','S2'],['嗯。','S1']]);
          assert.equal(result.map(x=>x.rawText).join(''),raw);
          assert.equal(result.map(x=>x.text).join(''),text);
          assert.ok(result.every(x=>x.sourceUtteranceId==='u1'&&!x.speakerInferred));
          assert.equal(new Set(result.map(x=>x.utteranceId)).size,3);
          assert.deepEqual(s.allTurns(),before);
          assert.equal(sample([turn(0,1200,'S1')]).sentenceUtterances().length,1);
          const mixed=sample([turn(0,600,'S1'),turn(600,1100,'S2'),turn(1100,1200,'S1')]);
          assert.ok(mixed.sentenceUtterances().some(x=>x.text==='张三说明结论。'&&x.speakerId==='UNKNOWN'));
          const frozen=s.commitThrough(1200);s.applySpeakerRemap({{S1:'S3'}});
          assert.deepEqual(frozen,result);assert.deepEqual(s.sentenceUtterances(),[]);
        """)

    def test_punctuation_cannot_shorten_unknown_or_propagate_inference(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId)=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}});
          const s=new State();
          s.addUtterance({{rawText:'甲乙丙丁戊己庚',text:'甲乙，丙丁，戊己，庚。',
            tokens:[...'甲乙丙丁戊己庚'],tokenTimesMs:[0,500,2000,3000,4000,6000,6500],
            beginTime:0,endTime:7000}});
          s.applySpeakerTurns([turn(0,500,'S1'),turn(500,6000,'UNKNOWN'),turn(6000,7000,'S1')]);
          const result=s.sentenceUtterances();
          assert.ok(result.filter(x=>x.beginTime<6000).every(x=>x.speakerId==='UNKNOWN'),
            'punctuation must not turn a 5500 ms UNKNOWN into separate eligible gaps');
          const known=result.find(x=>x.text==='庚。');
          assert.equal(known.speakerId,'S1');assert.equal(known.speakerInferred,false);
          const separate=new State();
          separate.addUtterance({{rawText:'甲乙',text:'甲。乙。',tokens:['甲','乙'],
            tokenTimesMs:[0,500],beginTime:0,endTime:1000}});
          separate.applySpeakerTurns([turn(0,500,'S1'),turn(500,1000,'UNKNOWN')]);
          assert.deepEqual(separate.sentenceUtterances().map(x=>x.speakerId),['S1']);
          assert.equal(separate.sentenceUtterances()[0].speakerInferred,true,
            'presentation punctuation is not a native utterance boundary');
        """)

    def test_lexical_rewrite_without_provenance_cannot_guess_clause_owners(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='先讨论方案这这个我理解然后继续嗯', text='先讨论方案。这J个我理解。然后继续。嗯。';
          const s=new State();
          s.addUtterance({{rawText:raw,text,tokens:[...raw],tokenTimesMs:[...raw].map((_,i)=>i*100),
            beginTime:0,endTime:raw.length*100}});
          s.applySpeakerTurns([[0,500,'S1'],[500,1100,'S2'],[1100,1500,'S1'],[1500,1600,'S2']]
            .map(([beginTime,endTime,speakerId])=>({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}})));
          const before=s.allTurns(), result=s.sentenceUtterances();
          assert.deepEqual(result.map(x=>[x.text,x.speakerId]),
            [[text,'UNKNOWN']]);
          assert.equal(result.map(x=>x.text).join(''),text);
          assert.equal(result.map(x=>x.rawText).join(''),raw);
          assert.deepEqual(s.allTurns(),before);
          assert.ok(result.every(x=>x.sourceUtteranceId==='u1'));
        """)

    def test_repeated_deleted_text_cannot_supply_an_ambiguous_punctuation_cut(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          for (const [raw,text] of [['甲乙甲乙丙丁','甲乙。丙丁。'],['甲乙丙丁','甲乙。甲乙。丙丁。'],
            ['一百一百元然后继续','100元。然后继续。']]) {{
            const s=new State();
            s.addUtterance({{rawText:raw,text,tokens:[...raw],tokenTimesMs:[...raw].map((_,i)=>i*100),
              beginTime:0,endTime:raw.length*100}});
            s.applySpeakerTurns([{{beginTime:0,endTime:200,speakerId:'S1',secondarySpeakerIds:[]}},
              {{beginTime:200,endTime:raw.length*100,speakerId:'S2',secondarySpeakerIds:[]}}]);
            const result=s.sentenceUtterances();
            assert.equal(result.map(x=>x.text).join(''),text);
            assert.equal(result.map(x=>x.rawText).join(''),raw);
            assert.equal(result[0].speakerId,'UNKNOWN');
            if(raw==='甲乙甲乙丙丁') assert.equal(result.length,1,'either repeated occurrence may have been deleted');
          }}
        """)

    def test_itn_merges_expansions_and_replacements_do_not_reassign_source_tokens(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          for(const [raw,rewritten] of [['一百元然后继续','100元。然后继续。'],
            ['百分之三','3%。'],['三','THREE。'],['甲乙甲乙丙丁','甲乙。丙丁。'],
            ['甲乙丙丁','甲乙。甲乙。丙丁。'],['𠮷野一百元','𠮷野100元。']]) {{
            let original;
            for(const text of [raw,rewritten]) {{
              const s=new State();s.addUtterance({{rawText:raw,text,tokens:[...raw],
                tokenTimesMs:[...raw].map((_,i)=>100*i),beginTime:0,endTime:[...raw].length*100}});
              s.applySpeakerTurns([{{beginTime:0,endTime:1000,speakerId:'S1',secondarySpeakerIds:[],confidence:.9}}]);
              const source=s.sourceAssignments(s.utterances[0]);
              if(original)assert.deepEqual(source,original,'ITN cannot change source evidence');else original=source;
              const out=s.sentenceUtterances();assert.equal(out.map(x=>x.text).join(''),text);
              assert.equal(out.map(x=>x.rawText).join(''),raw);
              if(text===rewritten){{assert.equal(out.length,1);assert.equal(out[0].speakerId,'UNKNOWN');
                assert.equal(out[0].confidence,0);assert.equal(out[0].speakerInferred,false);}}
            }}
          }}
        """)

    def test_unaligned_rewrite_preserves_uncertain_clause_and_raw_text(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const s=new State();
          s.addUtterance({{rawText:'一百元然后继续',text:'100元。然后继续。',tokens:[...'一百元然后继续'],
            tokenTimesMs:[0,100,200,300,400,500,600],beginTime:0,endTime:700}});
          s.applySpeakerTurns([{{beginTime:0,endTime:300,speakerId:'S1',secondarySpeakerIds:[]}},
            {{beginTime:300,endTime:700,speakerId:'S2',secondarySpeakerIds:[]}}]);
          const result=s.sentenceUtterances();
          assert.deepEqual(result.map(x=>[x.text,x.speakerId]),[['100元。然后继续。','UNKNOWN']]);
          assert.equal(result.map(x=>x.rawText).join(''),'一百元然后继续');
          assert.equal(result.map(x=>x.text).join(''),'100元。然后继续。');
        """)

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

    def test_public_result_and_real_caller_keep_inferred_flag_and_acoustic_turns(self):
        demo = (ROOT / 'delivery/harmony-dingqiao/samples/dingqiao-demo/entry/src/main/ets/pages/Index.ets').read_text()
        segment = demo[demo.index('class FinalSegment {'):demo.index('@Entry')]
        labels = demo[demo.index('  private speakerLabel('):demo.index('  private selectCustomerScenario(')]
        handler = demo[demo.index('  handleSpeakerDiarizationResult('):demo.index('  private async finishAutoEndedCapture(')]
        run_session(segment + '\nclass Caller { finalSegments=[];lastDiarizationWindowIndex=-1;diarizationDegraded=false;\n'
            + labels + handler + '\n}\n' + """
          const s=session(),raw='可以听见我说话吗你好',text='可以听见我说话吗？你好。';
          const payload={result:text,beginTime:19700,endTime:20860,isLast:false};
          s.observeAsrFinal(payload,{rawText:raw,tokens:[...raw],
            timestamps:[19.7,19.74,19.82,19.9,20.02,20.14,20.3,20.46,20.66,20.86],
            audioEndSample:347520,isLast:false});
          s.transcript.applySpeakerTurns([{beginTime:19600,endTime:20652.21875,speakerId:'S1',
            secondarySpeakerIds:[],confidence:.9}]);
          s.totalSamples=347520;s.finalSpeakerCount=1;
          const out=s.buildResult(0,undefined,21720,0);out.windowIndex=0;out.isSessionFinal=true;
          assert.equal(payload.result,text,'public ASR original is not rewritten to hide uncertainty');
          assert.equal(out.utterances.length,1);const part=out.utterances[0];
          assert.equal(part.rawText,raw);assert.equal(part.text,text);assert.equal(part.speakerIndex,0);
          assert.equal(part.speakerInferred,true);assert.equal(part.confidence,0);
          assert.equal(out.speakerTurns[0].endTime,20652.21875);
          const caller=new Caller();caller.handleSpeakerDiarizationResult('s1',out);
          assert.equal(caller.finalSegments.length,1);
          assert.equal(caller.finalSegments[0].speakerParts[0].speakerInferred,true);
          assert.equal(caller.segmentSpeakerLabel(caller.finalSegments[0]),'说话人 1 · 含推断补全');
          const frozen=JSON.stringify(caller.finalSegments);caller.handleSpeakerDiarizationResult('s1',out);
          assert.equal(JSON.stringify(caller.finalSegments),frozen,'committed window delivered once');
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
          const segment=(ids,overlap=false,speakerIndex=-1)=>({speakerIndex,displaySpeakerIndex:speakerIndex,
            speakerAssignmentFinal:true,revision:0,secondarySpeakerIndexes:[],
            speakerParts:[{speakerIndex,secondarySpeakerIndexes:ids,overlap,speakerInferred:false}]});
          assert.equal(label.segmentSpeakerLabel(segment([0,1])),'多人／不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0])),'不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0],true)),'不确定 · 含重叠发言');
          assert.equal(label.segmentSpeakerLabel(segment([],false,0)),'说话人 1');
        """)


if __name__ == '__main__':
    unittest.main()
