"""Lossless diagnostic persistence must not repeatedly encode retained model history."""
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk-dingqiao/src/main/ets/com/amphion/dingqiao'


class HarmonyDiagnosticJournalTest(unittest.TestCase):
    def run_journal(self, body: str) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sinks = (SOURCE / 'DiagnosticSinks.ets').read_text()
            sinks = sinks[sinks.index('export class NdjsonDiagnosticSink'):]
            (path / 'sinks.ts').write_text(
                f"import type {{ DiagnosticEvent }} from {(SOURCE/'DiagnosticsCore.ts').as_uri()!r};\n" + sinks)
            journal = (SOURCE / 'DiagnosticEventJournal.ets').read_text()
            journal = journal.replace("import { fileIo as fs } from '@kit.CoreFileKit';", "import { fs, util } from './fs.ts';")
            journal = journal.replace("import { util } from '@kit.ArkTS';", '')
            journal = journal.replace("import { DiagnosticEvent } from './DiagnosticsCore';",
                f"import type {{ DiagnosticEvent }} from {(SOURCE/'DiagnosticsCore.ts').as_uri()!r};")
            journal = journal.replace("from './DiagnosticSinks'", "from './sinks.ts'")
            (path / 'journal.ts').write_text(journal)
            (path / 'fs.ts').write_text(textwrap.dedent('''
                import nodefs from 'node:fs';
                export const faults={shortWrite:false,shortRead:false,open:0};
                export const util={TextEncoder:class{encodeInto(text){return new TextEncoder().encode(text)}}};
                const positions=new Map();
                export const fs={WhenceType:{SEEK_SET:0},OpenMode:{READ_ONLY:0,READ_WRITE:2,CREATE:4},
                  openSync(path,mode){const fd=nodefs.openSync(path,mode===0?'r':nodefs.existsSync(path)?'r+':'w+');faults.open++;positions.set(fd,0);return {fd}},
                  closeSync(fd){nodefs.closeSync(fd);positions.delete(fd);faults.open--},
                  lseek(fd,offset,whence){if(whence!==0)throw new Error('unexpected seek');positions.set(fd,offset);return offset},
                  writeSync(fd,buffer,options){const n=options.length-(faults.shortWrite?1:0);
                    const position=positions.get(fd)+(options.offset??0);
                    const count=nodefs.writeSync(fd,Buffer.from(buffer),0,n,position);positions.set(fd,position+count);return count},
                  readSync(fd,buffer,options){const n=options.length-(faults.shortRead?1:0);
                    const position=positions.get(fd)+(options.offset??0);
                    const count=nodefs.readSync(fd,Buffer.from(buffer),0,n,position);positions.set(fd,position+count);return count},
                  truncateSync(fd,length){nodefs.ftruncateSync(fd,length)}};
            '''))
            script = '''
                import assert from 'node:assert/strict';
                import fs from 'node:fs';
                import { DiagnosticEventJournal } from './journal.ts';
                import { NdjsonDiagnosticSink } from './sinks.ts';
                import { faults } from './fs.ts';
                const sink=new NdjsonDiagnosticSink();
                function event(sequence, name, fields, sessionId='session-1') {
                  return {schemaVersion:2,sequence,wallTimeMs:sequence,monotonicTimeNs:sequence,
                    runId:'run-1',engineId:'engine-1',sessionId,sessionGeneration:1,
                    streamGeneration:0,thread:'arkts-main',event:name,fields};
                }
                function encoded(events,array=false){let text='';sink.write(events,s=>text+=s,array);return text}
                function read(journal,events,array=false){const bytes=[];
                  journal.write(events,(buffer,n)=>bytes.push(Buffer.from(Buffer.from(buffer).subarray(0,n))),array);
                  return Buffer.concat(bytes).toString('utf8')}
            ''' + body
            entry = path / 'run.mts'
            entry.write_text(textwrap.dedent(script))
            subprocess.run(['node', '--experimental-strip-types', str(entry)], cwd=path, check=True)

    def test_model_payload_is_encoded_once_and_every_export_is_identical(self):
        self.run_journal('''
            let traversals=0;
            const matrix=Array.from({length:2402},(_,i)=>Array.from({length:105},(_,j)=>i===j?NaN:i/2402+j/105));
            const fields={jobId:'w00002359',trainingPosteriors:matrix,labels:['中文','a\\nb','"'],empty:[]};
            const records=[event(1,'START_LISTENING',{}),event(2,'DIARIZATION_COMMUNITY_COMMIT',fields),
              event(3,'DIARIZATION_COMMUNITY_WINDOW',{jobId:'w00000001',segmentations:Float32Array.of(0,1,0),embeddings:Float32Array.of(.1,NaN)}),
              event(4,'CANCEL_REQUESTED',{}),event(5,'CALLBACK_START',{},'session-2')];
            const expected=encoded(records),expectedArray=encoded(records,true);
            matrix.toJSON=function(){traversals++;return Array.from(this)};
            const journal=new DiagnosticEventJournal('events.full.ndjson');
            for(let flush=0;flush<3;flush++){
              journal.persist(records);
              assert.equal(read(journal,records),expected);
              assert.equal(read(journal,records,true),expectedArray);
            }
            assert.equal(traversals,1,'historical model matrix was re-encoded');
            assert.equal(records[1].fields.trainingPosteriors,undefined,'persisted matrix is still retained');
            assert.equal(records[2].fields.embeddings,undefined);
            assert.equal(read(journal,records.slice(4)),encoded([records[4]]),'cross-session bytes');
            assert.equal(fs.readFileSync('events.full.ndjson','utf8'),expected);
            assert.equal(faults.open,0);
        ''')

    def test_partial_write_keeps_fields_and_retry_preserves_exact_history(self):
        self.run_journal('''
            const journal=new DiagnosticEventJournal('events.full.ndjson');
            const a=event(1,'DIARIZATION_COMMUNITY_WINDOW',{embeddings:Float32Array.of(.1,.2)});
            const b=event(2,'DIARIZATION_COMMUNITY_COMMIT',{trainingPosteriors:[[.2,.8]],jobId:'w2'});
            const expected=encoded([a,b]);
            journal.persist([a]);const first=fs.readFileSync('events.full.ndjson','utf8');
            faults.shortWrite=true;
            assert.throws(()=>journal.persist([a,b]),/incomplete/);
            assert.deepEqual(b.fields.trainingPosteriors,[[.2,.8]]);
            assert.equal(fs.readFileSync('events.full.ndjson','utf8'),first);
            assert.equal(faults.open,0);
            faults.shortWrite=false;journal.persist([a,b]);
            assert.equal(read(journal,[a,b]),expected);
            assert.equal(fs.readFileSync('events.full.ndjson','utf8'),expected);
            faults.shortRead=true;
            assert.throws(()=>read(journal,[a,b]),/incomplete/);
            assert.equal(faults.open,0);
            faults.shortRead=false;
            assert.throws(()=>journal.write([a,b],()=>{throw new Error('destination full')}),/destination full/);
            assert.equal(faults.open,0);
        ''')

    def test_rolling_snapshot_keeps_full_journal_without_duplicate_records(self):
        self.run_journal('''
            const journal=new DiagnosticEventJournal('events.full.ndjson');
            const records=Array.from({length:4},(_,i)=>event(i+1,'DIARIZATION_COMMUNITY_SAMPLES',
              {jobId:`w${i}`,selectedSegmentationMask:[0,1,0,1]}));
            const expected=encoded(records);
            journal.persist(records.slice(0,2));
            journal.persist(records.slice(1,3));
            journal.persist(records.slice(2));
            assert.equal(fs.readFileSync('events.full.ndjson','utf8'),expected);
            assert.deepEqual(JSON.parse(read(journal,records.slice(2),true)).map(e=>e.sequence),[3,4]);
            assert.equal(faults.open,0);
        ''')


if __name__ == '__main__':
    unittest.main()
