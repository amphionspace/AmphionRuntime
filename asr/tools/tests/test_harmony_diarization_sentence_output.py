"""Whole ASR sentences must not imply a single speaker when evidence disagrees."""
import unittest

from asr.tools.tests.test_harmony_community_diarization import run_community_session as run_session
from asr.tools.tests.test_harmony_speaker_diarization_session import ROOT, TIMELINE, run_node


class HarmonyDiarizationSentenceOutputTest(unittest.TestCase):
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
          assert.deepEqual(separate.sentenceUtterances().map(x=>x.speakerId),['S1','UNKNOWN']);
        """)

    def test_lexical_rewrite_keeps_independently_aligned_clauses(self):
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
            [['先讨论方案。','S1'],['这J个我理解。','UNKNOWN'],['然后继续。','S1'],['嗯。','S2']]);
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

    def test_partial_alignment_cuts_agree_with_exhaustive_edit_paths(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState as State }} from {TIMELINE.as_uri()!r};
          const words=[];
          function wordsAt(prefix,n) {{if(prefix)words.push(prefix);if(n)for(const c of ['甲','乙'])wordsAt(prefix+c,n-1);}}
          wordsAt('',3);
          function minimumPaths(raw,text) {{
            let best=Infinity, paths=[];
            function walk(i,j,cost,owners) {{
              if(cost>best)return;
              if(i===raw.length&&j===text.length) {{
                if(cost<best){{best=cost;paths=[];}}paths.push(owners);return;
              }}
              if(i<raw.length)walk(i+1,j,cost+1,owners);
              if(j<text.length)walk(i,j+1,cost+1,owners.concat(-1));
              if(i<raw.length&&j<text.length)walk(i+1,j+1,cost+(raw[i]===text[j]?0:1),
                owners.concat(raw[i]===text[j]?i:-1));
            }}
            walk(0,0,0,[]);return paths;
          }}
          for(const raw of words)for(const target of words) {{
            const paths=minimumPaths(raw,target);
            for(let cut=1;cut<target.length;cut++) {{
              const text=target.slice(0,cut)+'。'+target.slice(cut)+'。';
              const input={{utteranceId:'u1',rawText:raw,text,tokens:[...raw],
                tokenTimesMs:[...raw].map((_,i)=>i*100),beginTime:0,endTime:raw.length*100}};
              const parts=new State().punctuationUnits(input);
              const left=paths[0][cut-1],right=paths[0][cut];
              const safe=left>=0&&right===left+1&&paths.every(p=>p[cut-1]===left&&p[cut]===right);
              assert.equal(parts.length,safe?2:1,JSON.stringify({{raw,text,paths}}));
              if(safe)assert.equal(parts[1].beginTime,right*100);
              assert.equal(parts.map(p=>p.rawText).join(''),raw);
              assert.equal(parts.map(p=>p.text).join(''),text);
            }}
          }}
          const unicode=new State().punctuationUnits({{utteranceId:'u1',rawText:'𠮷野继续一百元完',
            text:'𠮷野。继续100元。完。',tokens:['𠮷','野','继','续','一','百','元','完'],
            tokenTimesMs:[0,100,200,300,400,500,600,700],beginTime:0,endTime:800}});
          assert.equal(unicode.map(x=>x.rawText).join(''),'𠮷野继续一百元完');
          assert.equal(unicode[1].beginTime,200);
          const interior=new State().punctuationUnits({{utteranceId:'u1',rawText:'甲乙一百元',
            text:'甲。乙100元。',tokens:['甲乙','一百','元'],tokenTimesMs:[0,100,200],beginTime:0,endTime:300}});
          assert.equal(interior.length,1,'a punctuation cut inside one native token has no timestamp');
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
          assert.deepEqual(result.map(x=>[x.text,x.speakerId]),[['100元。','UNKNOWN'],['然后继续。','S2']]);
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
