"""Identity decisions must use current speech and preserve acoustic evidence."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import (
    DIARIZATION, REGISTRY, ROOT, SESSION, TIMELINE, TS_LOADER, run_node,
)


class HarmonyDiarizationIdentityStabilityTest(unittest.TestCase):


    def test_fixed_original_references_recover_a_diluted_centroid_without_cross_matching(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const v=d=>[Math.cos(d*Math.PI/180),Math.sin(d*Math.PI/180)];
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array([1,0]),6000,0);
          r.assign(new Float32Array([-1,0]),6000,0);
          r.bindComplementaryProfile('S1',[v(-40),v(40)],[3000,3000]);
          r.bindComplementaryProfile('S2',[v(180)],[3000]);
          const p=v(60), ids=new Set(['S1','S2']);
          const match=(q=v(60),c=v(60))=>r.matchComplementaryQuery(p,p,q,c,ids);
          assert.equal(match()?.speakerId,'S1','averaging loses a supported original reference');
          assert.equal(match(v(60),v(-60)),undefined,'context and query cannot use conflicting references');
          assert.equal(match(v(88),v(88)),undefined,'reference matching requires its own higher threshold');
          assert.equal(r.fork().matchComplementaryQuery(p,p,v(60),v(60),ids)?.speakerId,'S1');
          r.bindComplementaryProfile('S1',[v(120)],[6000]);
          assert.equal(match(v(120),v(120)),undefined,'later references cannot extend the profile');
          const bounded=new OnlineSpeakerRegistry();bounded.assign(new Float32Array([1,0]),6000,0);
          bounded.bindComplementaryProfile('S1',[...Array.from({{length:8}},()=>v(0)),v(90)],Array(9).fill(1000));
          assert.equal(bounded.matchComplementaryQuery(p,p,v(90),v(90),new Set(['S1'])),undefined,
            'only the independently calibrated maximum of eight references is eligible');
        """)


    def test_complementary_profile_is_fixed_and_both_models_must_agree(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array([1,0]),6000,0);
          r.assign(new Float32Array([-1,0]),6000,0);
          const weak=[.52,Math.sqrt(1-.52**2)], strong=[.7,Math.sqrt(1-.7**2)];
          const ids=new Set(['S1','S2']);
          const match=(p=weak,c=weak,q=strong,x=strong)=>r.matchComplementaryQuery(p,c,q,x,ids);
          assert.equal(match(),undefined,'missing complementary model must not fabricate identity');
          r.bindComplementaryProfile('S1',[[1,0],[1,0]],[1000,2000]);
          r.bindComplementaryProfile('S2',[[-1,0]],[3000]);
          assert.equal(r.matchQuery(weak,ids),undefined);
          const before=JSON.stringify(r.snapshot());
          assert.equal(match()?.speakerId,'S1');
          assert.equal(r.fork().matchComplementaryQuery(weak,weak,strong,strong,ids)?.speakerId,'S1');
          assert.equal(match(weak,[-1,0]),undefined,'primary context disagreement');
          assert.equal(match(weak,weak,[-1,0],[-1,0]),undefined,'models disagree');
          assert.equal(match(weak,weak,[.63,Math.sqrt(1-.63**2)]),undefined,'independent threshold');
          assert.equal(match([0,1],[0,1]),undefined,'primary candidate is ambiguous');
          assert.equal(r.matchComplementaryQuery(weak,weak,strong,strong,new Set()),undefined);
          r.bindComplementaryProfile('S1',[[-1,0]],[3000]);
          assert.equal(match()?.speakerId,'S1','later evidence cannot overwrite the reference');
          assert.equal(JSON.stringify(r.snapshot()),before,'complementary matching cannot update primary identities');
        """)


    def test_quiet_output_requires_strong_existing_alternative_support(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const v=d=>[Math.cos(d*Math.PI/180),Math.sin(d*Math.PI/180)];
          const r=new OnlineSpeakerRegistry();
          r.assign(new Float32Array(v(0)),6000,0);
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set(['S1'])),undefined);
          r.assign(new Float32Array(v(80)),6000,10000,true,[v(90)],
            [{{embedding:v(50),queryEmbedding:v(35)}}]);
          const before=JSON.stringify(r.snapshot());
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set(['S1']))?.speakerId,'S1');
          assert.equal(r.fork().matchQuietQuery?.(v(80),v(80),new Set(['S1']))?.speakerId,'S1');
          assert.equal(r.matchQuietQuery?.(v(35),v(50),new Set(['S1'])),undefined,
            'weaker identity support alone must not authorize quiet output');
          assert.equal(r.matchQuietQuery?.(v(180),v(80),new Set(['S1'])),undefined);
          assert.equal(r.matchQuietQuery?.(v(80),v(80),new Set()),undefined);
          assert.equal(JSON.stringify(r.snapshot()),before,'queries cannot update or enroll profiles');
        """)

    def test_independent_known_query_prevents_duplicate_enrollment_without_chaining(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const first=[1,0,0,0], changed=[.55,Math.sqrt(1-.55**2),0,0];
          const y=(.64-.55*.64)/changed[1];
          const bridge=[.64,y,Math.sqrt(1-.64**2-y*y),0];
          const support=[{{embedding:bridge,queryEmbedding:bridge}}];
          function registry() {{
            const r=new OnlineSpeakerRegistry();
            r.assign(new Float32Array(first),6000,0);
            return r;
          }}
          const r=registry();
          assert.equal(r.assign(new Float32Array(changed),3200,10000,true,
            [changed],support).speakerId,'S1',
            'an independently recognized voice must not occupy a second role');
          assert.deepEqual(r.speakerIds(),['S1']);
          assert.equal(r.matchQuery(changed,new Set(['S1'])).speakerId,'S1');
          assert.equal(r.fork().matchQuery(changed,new Set(['S1'])).speakerId,'S1');
          assert.equal(r.matchKnown(changed),undefined,
            'an alternative query reference must not become a primary enrollment anchor');
          assert.equal(r.matchQuery(changed,new Set()),undefined);
          assert.equal(registry().assign(new Float32Array(changed),3200,10000,true,
            [changed],[]).speakerId,'S2','do not merge a different voice without independent support');
          const inconsistent=registry();
          inconsistent.assign(new Float32Array([0,0,0,1]),6000,0);
          assert.equal(inconsistent.assign(new Float32Array(changed),3200,10000,true,
            [changed],[{{embedding:[0,0,0,1],queryEmbedding:bridge}}]).speakerId,'S3',
            'context and owned query must independently agree');
          const again=[.1,.7,Math.sqrt(.5),0];
          assert.equal(r.assign(new Float32Array(again),3200,20000,true,[again]).speakerId,'S1');
          const next=[0,.45,Math.sqrt(1-.45**2),0];
          assert.equal(r.assign(new Float32Array(next),3200,30000,true,
            [next],[{{embedding:again,queryEmbedding:again}}]).speakerId,'S2',
            'a corrected alternative must not recursively qualify more alternatives');
        """)


    def test_uncertain_match_does_not_prove_a_new_identity(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ OnlineSpeakerRegistry }} from {REGISTRY.as_uri()!r};
          const registry=new OnlineSpeakerRegistry();
          registry.assign(new Float32Array([1,0,0]),6000,0);
          const uncertain=registry.assign(new Float32Array([.68,Math.sqrt(1-.68**2),0]),2000,2000);
          assert.equal(uncertain.speakerId,'UNKNOWN',
            'below acceptance but within known-speaker query range must not create a new person');
          assert.deepEqual(registry.speakerIds(),['S1']);
          assert.equal(registry.assign(new Float32Array([0,1,0]),2000,4000).speakerId,'S2');
          assert.equal(registry.assign(new Float32Array([Math.SQRT1_2,Math.SQRT1_2,0]),2000,6000).speakerId,'UNKNOWN');
          assert.deepEqual(registry.speakerIds(),['S1','S2']);
          assert.equal(registry.assign(new Float32Array([.9,0,Math.sqrt(.19)]),2000,8000).speakerId,'S1');
        """)


    def test_remapping_a_hidden_secondary_preserves_its_evidence_binding(self):
        run_node(f"""
          import assert from 'node:assert/strict';
          import {{ SpeakerDiarizationTranscriptState }} from {TIMELINE.as_uri()!r};
          const state=new SpeakerDiarizationTranscriptState();
          state.applySpeakerTurns([{{beginTime:0,endTime:2000,speakerId:'S1',
            secondarySpeakerIds:['S2','S3'],evidenceKey:'a',secondaryEvidenceKeys:['b','c']}}]);
          state.applyEvidenceRemap({{a:'S1',b:'S1',c:'S3'}});
          assert.deepEqual(state.allTurns()[0].secondarySpeakerIds,['S3']);
          state.applyEvidenceRemap({{b:'S2'}});
          assert.deepEqual(state.allTurns()[0].secondarySpeakerIds,['S2','S3'],
            'remapping b must neither consume nor replace the identity belonging to c');
        """)
