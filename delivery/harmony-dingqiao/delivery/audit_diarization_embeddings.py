#!/usr/bin/env python3
"""Label captured run geometry with external RTTM for first-divergence diagnosis.

Labels never enter clustering. Pair diagnostics exclude overlapping time spans
so repeated windows of the same PCM cannot masquerade as independent recall.
Ambiguous or overlapping reference runs are retained but not used for pairs.
"""
from __future__ import annotations
import argparse
import math
from pathlib import Path
import statistics

from analyze_diarization_diagnostics import load_events
from diarization_evaluation import file_record, write_new
from evaluate_speaker_diarization_report import _load_reference
from replay_diarization_snapshot import snapshot


def audit(events, reference, session):
    boundaries = [e for e in events if e.get('sessionId') == session and e['event'] == 'DIARIZATION_COMMUNITY_COMMIT']
    if not boundaries:
        raise ValueError('no committed boundary for coverage audit')
    snapshot(events, session, boundaries[-1]['_sequence'])
    rows = []
    for event in events:
        if event.get('sessionId') != session or event['event'] != 'DIARIZATION_COMMUNITY_WINDOW':
            continue
        w = event['fields']; ranges = w.get('runRanges', []); vectors = w.get('runEmbeddings', [])
        if len(vectors) != len(ranges)//4*256:
            raise ValueError('run vectors missing; collect a complete snapshot before diagnosis')
        for r in range(len(ranges)//4):
            local, channel, begin, end = ranges[r*4:r*4+4]
            counts, overlap, silence, acoustic_overlap = {}, 0, 0, 0
            for frame in range(begin, end):
                at = (w['windowStartSample']+495.5+frame*270)/16000
                refs = {speaker for start, stop, speaker in reference if start <= at < stop}
                if len(refs) > 1: overlap += 1
                elif not refs: silence += 1
                else:
                    speaker = next(iter(refs));counts[speaker] = counts.get(speaker, 0)+1
                if sum(w['segmentations'][frame*3:frame*3+3]) > 1: acoustic_overlap += 1
            total = end-begin
            label = max(counts, key=counts.get) if counts else None
            purity = counts.get(label, 0)/total
            vector = vectors[r*256:(r+1)*256]
            finite = all(v is not None and math.isfinite(v) for v in vector)
            norm = math.sqrt(sum(v*v for v in vector)) if finite else 0
            eligible = bool(norm > 0 and purity >= .9 and overlap == 0 and acoustic_overlap == 0)
            rows.append({'jobId': w['jobId'], 'runIndex': r, 'channel': channel,
                         'beginTime': (w['windowStartSample']+495.5+begin*270)/16,
                         'endTime': min((w['windowStartSample']+495.5+end*270)/16,w['realEndSample']/16),
                         'frames': total, 'referenceSpeaker': label, 'referencePurity': purity,
                         'referenceFrames': counts, 'referenceOverlapFrames': overlap,
                         'referenceSilenceFrames': silence, 'acousticOverlapFrames': acoustic_overlap,
                         'finiteEmbedding': bool(norm > 0), 'pairEligible': eligible,
                         '_vector': [v/norm for v in vector] if eligible else None})
    same, different = [], []
    nearest = []
    for i, a in enumerate(rows):
        if not a['pairEligible']: continue
        by_class = {True: [], False: []}
        for j, b in enumerate(rows):
            if i==j or not b['pairEligible'] or max(a['beginTime'],b['beginTime']) < min(a['endTime'],b['endTime']):
                continue
            score=sum(x*y for x,y in zip(a['_vector'],b['_vector']))
            same_person=a['referenceSpeaker']==b['referenceSpeaker']
            by_class[same_person].append(score)
            if j>i: (same if same_person else different).append(score)
        if all(by_class.values()):
            nearest.append({'jobId':a['jobId'],'runIndex':a['runIndex'],
                            'referenceSpeaker':a['referenceSpeaker'],
                            'sameMinusDifferent':max(by_class[True])-max(by_class[False])})
    def distribution(values):
        return {'count':len(values),'min':min(values,default=None),'median':statistics.median(values) if values else None,'max':max(values,default=None)}
    for row in rows: del row['_vector']
    refs=sorted({r[2] for r in reference})
    return {'scope':'RTTM labels for diagnosis only; 90% pure clean runs; temporal overlap excluded from pairs',
            'perReference':{speaker:{'dominantRuns':sum(r['referenceSpeaker']==speaker for r in rows),
                                    'pairEligibleRuns':sum(r['referenceSpeaker']==speaker and r['pairEligible'] for r in rows),
                                    'finiteDominantRuns':sum(r['referenceSpeaker']==speaker and r['finiteEmbedding'] for r in rows)} for speaker in refs},
            'sameSpeakerCosine':distribution(same),'differentSpeakerCosine':distribution(different),
            'nearestIndependentRunMargins':nearest,'runs':rows,
            'modelSeparabilityStatus':'INCONCLUSIVE; inspect per-person coverage and signed margins, not just mean distance'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events',type=Path,required=True);p.add_argument('--session',required=True)
    p.add_argument('--reference-rttm',type=Path,required=True);p.add_argument('--reference-offset-seconds',type=float,default=0)
    p.add_argument('--duration-seconds',type=float,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    result=audit(load_events(a.events),_load_reference(a.reference_rttm,a.reference_offset_seconds,a.duration_seconds),a.session)
    result['inputs']={'events':file_record(a.events),'reference':file_record(a.reference_rttm),
                      'referenceOffsetSeconds':a.reference_offset_seconds,'durationSeconds':a.duration_seconds}
    write_new(a.output,result)
    print(result['perReference'])


if __name__=='__main__':main()
