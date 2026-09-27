"""Lossless evidence snapshots and ownership at the file boundary."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests.test_harmony_speaker_diarization_session import DIARIZATION


class HarmonyDiarizationEvidenceSpoolTest(unittest.TestCase):
    def run_spool(self, body):
        source = (DIARIZATION / 'DiarizationEvidenceSpool.ets').read_text()
        source = source[source.index('export interface DiarizationEvidence'):]
        shim = '''
          import assert from 'node:assert/strict';
          import nodefs from 'node:fs';
          let shortWrite=false,shortRead=false,open=0;
          const fs={OpenMode:{READ_ONLY:0,WRITE_ONLY:1,CREATE:2,APPEND:4},
            openSync(path,mode){const fd=nodefs.openSync(path,mode===0?'r':'a');open++;return {fd}},
            closeSync(fd){nodefs.closeSync(fd);open--},
            accessSync:path=>nodefs.existsSync(path),unlinkSync:path=>nodefs.unlinkSync(path),
            writeSync(fd,buffer){return nodefs.writeSync(fd,Buffer.from(buffer),0,buffer.byteLength-(shortWrite?1:0))},
            readSync(fd,buffer,options){return nodefs.readSync(fd,Buffer.from(buffer),0,options.length-(shortRead?1:0),options.offset)}};
          function values(n){const v=new Float32Array(n+2);for(let i=0;i<n;i++)v[i+1]=i/7;
            v[2]=NaN;v[3]=-0;v[4]=Infinity;return v.subarray(1,n+1)}
          const bytes=v=>Buffer.from(v.buffer,v.byteOffset,v.byteLength);
        '''
        with tempfile.TemporaryDirectory() as directory:
            entry = Path(directory) / 'spool.mts'
            entry.write_text(shim + source + body)
            subprocess.run(['node', '--experimental-strip-types', str(entry)], cwd=directory, check=True)

    def test_prefix_snapshot_preserves_every_bit_and_owns_its_storage(self):
        self.run_spool('''
          const spool=new DiarizationEvidenceSpool('.');
          const segments=values(1767),embeddings=values(768);
          const expectedSegments=Buffer.from(bytes(segments)),expectedEmbeddings=Buffer.from(bytes(embeddings));
          spool.append(segments,embeddings);segments.fill(99);embeddings.fill(99);
          spool.append(segments,embeddings);
          let first=spool.read(1);
          assert.deepEqual(bytes(first.segments),expectedSegments);assert.deepEqual(bytes(first.embeddings),expectedEmbeddings);
          first.segments.fill(55);first.embeddings.fill(55);
          const all=spool.read(2);
          assert.deepEqual(bytes(all.segments.subarray(0,1767)),expectedSegments);
          assert.deepEqual(bytes(all.embeddings.subarray(0,768)),expectedEmbeddings);
          assert.ok(all.segments.subarray(1767).every(v=>v===99));
          assert.throws(()=>spool.read(3),/exceeds/);
          spool.close();assert.equal(open,0);
          assert.deepEqual(bytes(spool.read(1).segments),expectedSegments);
          spool.remove();assert.equal(open,0);assert.ok(!nodefs.existsSync('segments.f32'));
          assert.ok(!nodefs.existsSync('embeddings.f32'));spool.remove();
        ''')

    def test_incomplete_io_never_publishes_an_incomplete_window_and_closes_readers(self):
        self.run_spool('''
          const spool=new DiarizationEvidenceSpool('.');
          const segments=values(1767),embeddings=values(768);
          spool.append(segments,embeddings);
          shortRead=true;assert.throws(()=>spool.read(1),/incomplete/);assert.equal(open,2);
          shortRead=false;shortWrite=true;
          assert.throws(()=>spool.append(segments,embeddings),/incomplete/);
          assert.throws(()=>spool.read(2),/exceeds/);
          assert.deepEqual(bytes(spool.read(1).segments),bytes(segments));
          spool.remove();assert.equal(open,0);
        ''')
