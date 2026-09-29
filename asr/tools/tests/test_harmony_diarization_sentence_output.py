"""Whole ASR sentences must not imply a single speaker when evidence disagrees."""
import unittest

from asr.tools.tests.test_harmony_community_diarization import run_community_session as run_session
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, TIMELINE, run_node


class HarmonyDiarizationSentenceOutputTest(unittest.TestCase):
    def test_text_spans_keep_known_words_independent_of_sentence_summary(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='先说这件事我来回答';
          const turns=[[0,1458,'S1'],[1458,1475,'S4'],[2420,2437,'S4'],[2437,3230,'S2']]
            .map(([beginTime,endTime,speakerId])=>({{beginTime,endTime,speakerId,
              secondarySpeakerIds:[],confidence:.8,overlap:false}}));
          let reference;
          for(const text of [raw+'。','先说这件事。我来回答。']) {{
            const s=new State();s.addUtterance({{rawText:raw,text,tokens:[...raw],
              tokenTimesMs:[100,220,300,500,700,2780,3020,3340,3500],beginTime:100,endTime:3500}});
            s.applySpeakerTurns(turns);const before=s.allTurns(),out=s.sentenceUtterances();
            const owners=out.flatMap(u=>(u.speakerTextSpans??[{{sourceBegin:0,sourceEnd:u.rawText.length,
              speakerId:u.speakerId}}]).flatMap(p=>Array(p.sourceEnd-p.sourceBegin).fill(p.speakerId)));
            assert.deepEqual(owners,['S1','S1','S1','S1','S1','S2','S2','S2','S2'],
              'an uncertain sentence summary must not erase its independently aligned text owners');
            const spans=out.flatMap(u=>u.speakerTextSpans);
            assert(spans.some(p=>p.speakerInferred));
            assert(spans.filter(p=>p.speakerInferred).every(p=>p.confidence===0));
            if(reference)assert.deepEqual(owners,reference);else reference=owners;
            for(const u of out)assert.equal(u.speakerTextSpans.map(p=>u.text.slice(p.textBegin,p.textEnd)).join(''),u.text);
            assert.equal(out.map(u=>u.text).join(''),text);assert.deepEqual(s.allTurns(),before);
            const frozen=s.commitThrough(3500);s.applySpeakerRemap({{S1:'S3',S2:'S3'}});
            assert.deepEqual(frozen,out);assert.deepEqual(s.sentenceUtterances(),[]);
          }}
        """)

    def test_itn_source_records_preserve_original_owner_and_inference(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='到了一百二十秒再说你好', text='到了120s，再说你好。';
          // Native grammar records provide these source ranges. The numeric
          // rewrite is one indivisible record, never evenly distributed tokens.
          const normalization={{text:'到了120s再说你好',spans:[
            [0,1,0,1],[1,2,1,2],[2,7,2,6],[7,8,6,7],[8,9,7,8],
            [9,10,8,9],[10,11,9,10]].map(([sourceBegin,sourceEnd,textBegin,textEnd])=>
              ({{sourceBegin,sourceEnd,textBegin,textEnd}}))}};
          const s=new State();s.addUtterance({{rawText:raw,text,tokens:[...raw],
            tokenTimesMs:[...raw].map((_,i)=>100*i),beginTime:0,endTime:1100,
            textNormalization:normalization}});
          s.applySpeakerTurns([{{beginTime:0,endTime:900,speakerId:'S1',secondarySpeakerIds:[],confidence:.9}}]);
          const before=s.allTurns(),out=s.sentenceUtterances();
          assert.equal(out.map(x=>x.text).join(''),text);
          assert.equal(out.map(x=>x.rawText).join(''),raw);
          assert.ok(out.every(x=>x.speakerId==='S1'),'exact ITN source records retain the raw-token owner');
          assert.ok(out.some(x=>x.speakerInferred),'bounded raw tail inference must survive ITN and punctuation');
          assert.ok(out.filter(x=>x.speakerInferred).every(x=>x.confidence===0));
          assert.deepEqual(s.allTurns(),before);
        """)

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

    def test_itn_record_cannot_hide_a_short_speaker_change_overlap_or_unknown(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const turn=(beginTime,endTime,speakerId,extra={{}})=>
            ({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9,...extra}});
          const sample=(turns,spans=[{{sourceBegin:0,sourceEnd:4,textBegin:0,textEnd:2}}])=>{{
            const s=new State();s.addUtterance({{rawText:'百分之三',text:'3%。',tokens:[...'百分之三'],
              tokenTimesMs:[0,100,200,300],beginTime:0,endTime:400,
              textNormalization:{{text:'3%',spans}}}});s.applySpeakerTurns(turns);return s;
          }};
          for(const turns of [
            [turn(0,200,'S1'),turn(200,400,'S2')],
            [turn(0,150,'S1'),turn(150,175,'S2'),turn(175,400,'S1')],
            [turn(0,400,'UNKNOWN')],
            [turn(0,400,'S1',{{overlap:true,secondarySpeakerIds:['S2']}})],
            [turn(0,400,'S1',{{overlap:true,secondarySpeakerIds:['UNKNOWN']}})]
          ]){{
            const s=sample(turns),before=s.allTurns(),out=s.sentenceUtterances();
            assert.equal(out.length,1);assert.equal(out[0].text,'3%。');
            assert.equal(out[0].rawText,'百分之三');assert.equal(out[0].speakerId,'UNKNOWN');
            assert.equal(out[0].confidence,0);assert.deepEqual(s.allTurns(),before);
            assert.equal(out[0].overlap,turns.some(t=>t.overlap));
            assert.equal(out[0].speakerTextSpans.length,1);
            const span=out[0].speakerTextSpans[0];
            assert.equal(span.overlap,turns.some(t=>t.overlap));
            if(new Set(turns.map(t=>t.speakerId)).size>1)
              assert.equal(span.speakerId,'UNKNOWN','a converted record cannot erase a 25 ms contrary turn');
            const frozen=s.commitThrough(400);s.applySpeakerTurns([turn(0,400,'S3')]);
            assert.deepEqual(frozen,out);assert.deepEqual(s.sentenceUtterances(),[]);
          }}
          for(const spans of [[],[{{sourceBegin:0,sourceEnd:3,textBegin:0,textEnd:2}}],
            [{{sourceBegin:0,sourceEnd:4,textBegin:1,textEnd:2}}]]) {{
            const out=sample([turn(0,400,'S1')],spans).sentenceUtterances()[0];
            assert.equal(out.speakerId,'UNKNOWN');assert.deepEqual(out.speakerTextSpans,[]);
          }}
          const unicode=new State();unicode.addUtterance({{rawText:'𠮷三',text:'𠮷3。',tokens:['𠮷','三'],
            tokenTimesMs:[0,100],beginTime:0,endTime:200,textNormalization:{{text:'𠮷3',spans:[
              {{sourceBegin:0,sourceEnd:2,textBegin:0,textEnd:2}},{{sourceBegin:2,sourceEnd:3,textBegin:2,textEnd:3}}]}}}});
          unicode.applySpeakerTurns([turn(0,200,'S1')]);assert.equal(unicode.sentenceUtterances()[0].speakerId,'S1');
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
            let publicReference;
            for(const text of ['甲乙丙丁','甲？乙。丙，丁。','甲乙！丙丁。']) {{
              const s=new State();s.addUtterance({{rawText:'甲乙丙丁',text,tokens:[...'甲乙丙丁'],
                tokenTimesMs:[0,200,400,600],beginTime:0,endTime:800}});s.applySpeakerTurns(turns);
              const source=s.sourceAssignments(s.utterances[0]);
              if(reference)assert.deepEqual(source,reference);else reference=source;
              const before=JSON.stringify(s.allTurns()),out=s.sentenceUtterances();
              const projected=out.flatMap(u=>u.speakerTextSpans.flatMap(span=>
                Array.from({{length:span.sourceEnd-span.sourceBegin}},()=>({{speakerId:span.speakerId,
                  secondarySpeakerIds:span.secondarySpeakerIds,overlap:span.overlap,
                  speakerInferred:span.speakerInferred,confidence:span.confidence}}))));
              if(publicReference)assert.deepEqual(projected,publicReference,
                'public per-source ownership and uncertainty cannot depend on punctuation');
              else publicReference=projected;
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

    def test_punctuation_model_deleting_ascii_cjk_space_keeps_owners(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          // sherpa's CT punctuation rejoins tokens with a space only between two
          // ASCII-leading tokens, so an ASCII/CJK separator is always dropped.
          const raw='WHAT IS 阿拉测试', text='WHAT IS阿拉测试。';
          const turn=(beginTime,endTime,speakerId)=>({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}});
          const s=new State();
          s.addUtterance({{rawText:raw,text,tokens:[...raw],tokenTimesMs:[...raw].map((_,i)=>i*100),
            beginTime:0,endTime:raw.length*100}});
          s.applySpeakerTurns([turn(0,800,'S1'),turn(800,1200,'S2')]);
          const before=s.allTurns(),out=s.sentenceUtterances();
          const owners=out.flatMap(u=>(u.speakerTextSpans??[]).flatMap(p=>
            [...u.text.slice(p.textBegin,p.textEnd)].map(()=>p.speakerId)));
          assert.deepEqual(owners,[...Array(7).fill('S1'),...Array(5).fill('S2')]);
          assert.equal(out.map(x=>x.text).join(''),text);assert.equal(out.map(x=>x.rawText).join(''),raw);
          assert.deepEqual(s.allTurns(),before);
        """)

    def test_postprocessor_clause_records_localize_lexical_rewrites(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const raw='先讨论方案这这个我理解然后继续嗯';
          const clauses=[['先讨论方案，','先讨论方案，'],['这这个我理解，','浙J个我理解，'],['然后继续，','然后继续，'],['嗯。','嗯。']];
          const source=clauses.map(c=>c[0]).join(''),text=clauses.map(c=>c[1]).join('');
          const spans=[];let sourceBegin=0,textBegin=0;
          for(const [input,output] of clauses){{spans.push({{sourceBegin,sourceEnd:sourceBegin+input.length,
            textBegin,textEnd:textBegin+output.length}});sourceBegin+=input.length;textBegin+=output.length;}}
          const turn=(beginTime,endTime,speakerId)=>({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}});
          const sample=(turns,presentation)=>{{const s=new State();s.addUtterance({{rawText:raw,text,tokens:[...raw],
            tokenTimesMs:[...raw].map((_,i)=>i*100),beginTime:0,endTime:raw.length*100,presentation}});
            s.applySpeakerTurns(turns);return s;}};
          const turns=[turn(0,500,'S1'),turn(500,1100,'S2'),turn(1100,1500,'S1'),turn(1500,1600,'S2')];
          const s=sample(turns,{{sourceText:source,spans}}),before=s.allTurns(),out=s.sentenceUtterances();
          assert.deepEqual(out.map(x=>[x.text,x.speakerId]),
            [['先讨论方案，','S1'],['浙J个我理解，','S2'],['然后继续，','S1'],['嗯。','S2']]);
          const rewritten=out[1].speakerTextSpans;
          assert.deepEqual(rewritten.map(p=>[p.textBegin,p.textEnd,p.speakerId]),[[0,7,'S2']],
            'a rewritten postprocessor record is one indivisible text span');
          assert.equal(out.map(x=>x.text).join(''),text);assert.equal(out.map(x=>x.rawText).join(''),raw);
          assert.deepEqual(s.allTurns(),before);
          // A speaker change inside the rewritten record keeps only that record uncertain.
          const inner=sample([turn(0,500,'S1'),turn(500,700,'S3'),turn(700,1100,'S2'),turn(1100,1500,'S1'),
            turn(1500,1600,'S2')],{{sourceText:source,spans}}).sentenceUtterances();
          assert.deepEqual(inner.map(x=>[x.text,x.speakerId]),
            [['先讨论方案，','S1'],['浙J个我理解，','UNKNOWN'],['然后继续，','S1'],['嗯。','S2']]);
          // Without records, or with records that do not rebuild the published text, nothing is guessed.
          for(const presentation of [undefined,{{sourceText:source,spans:spans.slice(1)}},
            {{sourceText:source.slice(1),spans}}]) {{
            assert.deepEqual(sample(turns,presentation).sentenceUtterances().map(x=>[x.text,x.speakerId]),
              [[text,'UNKNOWN']]);
          }}
        """)

    def test_police_trace_records_keep_owners_through_rewrite_trim_and_insertions(self):
        trace_module = ROOT / 'asr/harmony/sdk-police/src/main/ets/com/amphion/police/PoliceTextTrace.ts'
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          import {{ PoliceTextTrace, PoliceTextEdit, replaceMatches }} from {trace_module.as_uri()!r};
          const raw='先讨论方案这这个我理解然后继续嗯';
          const source=' 先讨论方案，这这个我理解，然后继续，嗯？ ';
          // The same step shapes the police pipeline uses: a global rewrite, a trim,
          // a sentence-final replacement and an appended full stop.
          const trace=new PoliceTextTrace(source);
          let text=source;
          const step=(next,edits)=>{{trace.step(text,next,edits);text=next;}};
          let edits=[];step(replaceMatches(text,/这这/g,edits,()=>'浙J'),edits);
          const trimmed=text.trim();step(trimmed,[new PoliceTextEdit(0,1,''),new PoliceTextEdit(text.length-1,text.length,'')]);
          step(text.slice(0,-1)+'。',[new PoliceTextEdit(text.length-1,text.length,'。')]);
          step(text+'。',[new PoliceTextEdit(text.length,text.length,'。')]);
          assert.equal(text,'先讨论方案，浙J个我理解，然后继续，嗯。。');
          assert(trace.matches(text));
          const presentation=trace.provenance();
          assert(presentation!==undefined);
          const turn=(beginTime,endTime,speakerId)=>({{beginTime,endTime,speakerId,secondarySpeakerIds:[],confidence:.9}});
          const s=new State();
          s.addUtterance({{rawText:raw,text:source,tokens:[...raw],tokenTimesMs:[...raw].map((_,i)=>i*100),
            beginTime:0,endTime:raw.length*100}});
          const direct=s.sentenceUtterances();
          const t=new State();
          t.addUtterance({{rawText:raw,text,tokens:[...raw],tokenTimesMs:[...raw].map((_,i)=>i*100),
            beginTime:0,endTime:raw.length*100,presentation}});
          t.applySpeakerTurns([turn(0,500,'S1'),turn(500,1100,'S2'),turn(1100,1500,'S1'),turn(1500,1600,'S2')]);
          const before=t.allTurns(),out=t.sentenceUtterances();
          assert.equal(out.map(x=>x.text).join(''),text);assert.equal(out.map(x=>x.rawText).join(''),raw);
          const owners=out.flatMap(u=>u.speakerTextSpans.flatMap(p=>[...u.text.slice(p.textBegin,p.textEnd)].map(()=>p.speakerId)));
          assert.deepEqual(owners,[...Array(6).fill('S1'),...Array(7).fill('S2'),...Array(5).fill('S1'),...Array(3).fill('S2')],
            'unchanged clauses keep token owners; the rewritten record and appended stops stay with their neighbours');
          for(const u of out)assert.equal(u.speakerTextSpans.map(p=>u.text.slice(p.textBegin,p.textEnd)).join(''),u.text);
          assert.deepEqual(t.allTurns(),before);
          assert.ok(direct.length>0);
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
        self.assertIn('this.textRunLabel(run)', demo, 'each visible speaker run needs an explicit SDK ID label')
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
          assert.ok(caller.finalSegments[0].speakerParts[0].speakerTextSpans.some(span=>span.speakerInferred));
          assert.equal(caller.segmentTextRuns(caller.finalSegments[0]).map(run=>run.text).join(''),text);
          assert.equal(caller.segmentSpeakerLabel(caller.finalSegments[0]),'说话人 1 · 含推断补全');
          const frozen=JSON.stringify(caller.finalSegments);caller.handleSpeakerDiarizationResult('s1',out);
          assert.equal(JSON.stringify(caller.finalSegments),frozen,'committed window delivered once');
          const mixed=session();mixed.transcript.addUtterance({rawText:'先说这件事我来回答',
            text:'先说这件事我来回答。',tokens:[...'先说这件事我来回答'],
            tokenTimesMs:[100,220,300,500,700,2780,3020,3340,3500],beginTime:100,endTime:3500});
          mixed.transcript.applySpeakerTurns([[0,1458,'S1'],[1458,1475,'S4'],[2420,2437,'S4'],[2437,3230,'S2']]
            .map(([beginTime,endTime,speakerId])=>({beginTime,endTime,speakerId,secondarySpeakerIds:[],overlap:false})));
          mixed.totalSamples=4000*16;
          const full=mixed.buildResult(0,undefined,4000,0);full.windowIndex=0;full.isSessionFinal=true;
          const other=new Caller();other.handleSpeakerDiarizationResult('s',full);
          assert.equal(other.finalSegments.length,1,'one original utterance remains one readable paragraph');
          assert.equal(other.finalSegments[0].text,'先说这件事我来回答。');
          const runs=other.segmentTextRuns(other.finalSegments[0]);
          assert.deepEqual(runs.map(({text,speakerIndex})=>({text,speakerIndex})),
            [{text:'先说这件事',speakerIndex:0},{text:'我来回答。',speakerIndex:1}]);
          assert.deepEqual(runs.map(run=>other.textRunLabel(run)+':'+run.text),
            ['说话人 1:先说这件事','说话人 2 · 含推断补全:我来回答。']);
          assert.equal(runs[1].speakerInferred,true);assert.equal(runs[1].confidence,0);
          const fixture=(text,rows)=>({speakerParts:[{text,speakerIndex:-1,confidence:0,
            speakerTextSpans:rows.map(([textBegin,textEnd,speakerIndex,extra={}])=>
              ({textBegin,textEnd,speakerIndex,confidence:.8,overlap:false,speakerInferred:false,...extra}))}]});
          const uncertain=fixture('你好张三回答。',[[0,1,2],[1,2,-1],[2,3,2],[3,4,2],
            [4,5,0],[5,6,0,{overlap:true,secondarySpeakerIndexes:[1]}],
            [6,7,0,{speakerInferred:true,confidence:0}]]);
          const before=JSON.stringify(uncertain), grouped=other.segmentTextRuns(uncertain);
          assert.deepEqual(grouped.map(r=>r.text),['你好张三','回答。'],
            'UNKNOWN and same-speaker token spans must not split intact words');
          assert.deepEqual(grouped.map(r=>other.textRunLabel(r)),
            ['说话人 3 · 部分文字归属不确定','说话人 1 · 含重叠发言 · 含推断补全']);
          assert.equal(grouped[1].confidence,0);assert.equal(JSON.stringify(uncertain),before);
          const unknown=other.segmentTextRuns(fixture('你好。',[[0,1,-1],[1,3,-1]]));
          assert.equal(unknown.length,1);assert.equal(other.textRunLabel(unknown[0]),'不确定');
          const short=other.segmentTextRuns(fixture('对好的',[[0,1,3],[1,2,0],[2,3,0]]));
          assert.deepEqual(short.map(r=>[r.speakerIndex,r.text]),[[3,'对'],[0,'好的']],
            'real one-character reply and public ID order are preserved');
          assert.equal(other.segmentSpeakerLabel(other.finalSegments[0]),'句内换人 · 含推断补全');
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
            speakerParts:[{sourceUtteranceId:'u1',speakerIndex,secondarySpeakerIndexes:ids,overlap,speakerInferred:false}]});
          assert.equal(label.segmentSpeakerLabel(segment([0,1])),'句内换人（文字归属不确定）');
          assert.equal(label.segmentSpeakerLabel(segment([0,1],true)),'多人／不确定 · 含重叠发言');
          const unconfirmed=segment([0,1]);delete unconfirmed.speakerParts[0].overlap;
          assert.equal(label.segmentSpeakerLabel(unconfirmed),'多人／不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0])),'不确定');
          assert.equal(label.segmentSpeakerLabel(segment([0],true)),'不确定 · 含重叠发言');
          assert.equal(label.segmentSpeakerLabel(segment([],false,0)),'说话人 1');
        """)


if __name__ == '__main__':
    unittest.main()
