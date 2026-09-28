#!/usr/bin/env python3
"""Replay one captured cluster boundary; missing run vectors are an error.

The output is host diagnostic evidence, never a phone performance measurement.
The captured session, window order, frame geometry and commit prefix are fixed.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import struct
import subprocess

from diarization_evaluation import file_record, write_new
from analyze_diarization_diagnostics import load_events


def snapshot(events: list[dict], session: str, sequence: int) -> tuple[bytes, dict]:
    selected = [e for e in events if e.get("sessionId") == session and e["_sequence"] <= sequence]
    commits = [e for e in selected if e["_sequence"] == sequence and e["event"] in
               {"DIARIZATION_COMMUNITY_COMMIT", "DIARIZATION_COMMUNITY_PREVIEW"}]
    if len(commits) != 1:
        raise ValueError("select exactly one session/cluster event sequence")
    boundary = commits[0]["fields"]
    windows = {}
    for event in selected:
        if event["event"] == "DIARIZATION_COMMUNITY_WINDOW":
            fields = event["fields"]
            if fields["jobId"] in windows:
                raise ValueError("duplicate window identity")
            windows[fields["jobId"]] = fields
    seg, emb, vectors, ranges, starts = [], [], [], [], []
    for index, job in enumerate(boundary["jobIds"]):
        if job not in windows:
            raise ValueError(f"missing prefix window {job}; use events.full.ndjson, not the bounded journal")
        w = windows[job]
        if len(w["segmentations"]) != 589*3 or len(w["embeddings"]) != 768:
            raise ValueError("truncated window tensors")
        local_ranges = w.get("runRanges", [])
        local_vectors = w.get("runEmbeddings", [])
        if len(local_ranges) % 4 or len(local_vectors) != len(local_ranges)//4*256:
            raise ValueError("runEmbeddings missing or truncated; cannot substitute full-window embeddings")
        seg.extend(w["segmentations"]);emb.extend(w["embeddings"]);vectors.extend(local_vectors)
        starts.append(w["windowStartSample"])
        for pos in range(0,len(local_ranges),4):
            local_window, channel, begin, end = local_ranges[pos:pos+4]
            if local_window != 0 or any(int(x) != x for x in (channel,begin,end)):
                raise ValueError("invalid local run coordinate")
            ranges.extend([index,int(channel),int(begin),int(end)])
    if starts != boundary["windowStartSamples"]:
        raise ValueError("captured window order/ownership differs from commit")
    def pack(code, values):
        # JSON null represents a non-finite embedding, not a zero vector.
        return struct.pack('<'+code*len(values),*[float('nan') if v is None else v for v in values])
    body=struct.pack('<IIIId',0x43525031,len(starts),len(ranges)//4,4,boundary['beginTime']*16)
    body+=pack('d',starts)+pack('f',seg)+pack('f',emb)+pack('f',vectors)+pack('i',ranges)
    return body,boundary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',type=Path,required=True)
    parser.add_argument('--session',required=True)
    parser.add_argument('--sequence',type=int,required=True)
    parser.add_argument('--plda',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    body,boundary=snapshot(load_events(args.events),args.session,args.sequence)
    args.output_dir.mkdir(parents=True,exist_ok=False)
    input_path=args.output_dir/'snapshot.bin';input_path.write_bytes(body)
    root=Path(__file__).resolve().parents[3]
    source=root/'asr/tools/replay_community_cluster.cpp';binary=args.output_dir/'replay'
    subprocess.run(['c++','-std=c++17','-O2','-I',str(root/'asr/harmony/sdk/src/main/cpp'),str(source),'-o',str(binary)],check=True)
    raw=subprocess.check_output([str(binary),str(args.plda),str(input_path)])
    result=json.loads(raw)
    parity={key:result[key]==boundary[key] for key in ('hard','frameHard','trainingIndices','trainingRunIndices','ahc') if key in boundary}
    report={'scope':'host same-tensor replay; not device performance or identity truth',
            'session':args.session,'sequence':args.sequence,'capturedFieldEquality':parity,
            'inputs':{'events':file_record(args.events),'plda':file_record(args.plda),
                      'snapshot':file_record(input_path),'helper':file_record(source),
                      'cluster':file_record(root/'asr/harmony/sdk/src/main/cpp/community_cluster.h'),
                      'kmeans':file_record(root/'asr/harmony/sdk/src/main/cpp/community_kmeans.h')},
            'replay':result}
    write_new(args.output_dir/'replay.json',report)
    print(json.dumps({'output':str(args.output_dir),'parity':parity,'speakerCount':result['speakerCount']}))
    return 0 if parity and all(parity.values()) else 1


if __name__=='__main__':
    raise SystemExit(main())
