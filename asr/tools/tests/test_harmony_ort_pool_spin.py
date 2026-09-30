"""Bound the XNNPACK pool's idle spin in the pinned OHOS runtime build.

The role encoder runs one 10 s window per second, so its pthread pool is idle
between windows. Upstream yields a million times before blocking on both the
workers and the dispatching thread, which measured as 0.73 CPU-seconds per wall
second of pure overhead at four threads. These checks keep the build honest about
the bound instead of trusting a patch command's exit status.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools import build_harmony_onnxruntime as builder

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_SPIN = '#define PTHREADPOOL_SPIN_WAIT_ITERATIONS 1000000'
UPSTREAM_COMMENT = '/* Number of iterations in spin-wait loop before going into futex/condvar wait */'
UPSTREAM_TAIL = '\n#define PTHREADPOOL_CACHELINE_SIZE 64\n#if defined(__GNUC__)\n'


def header_fixture():
    # Reproduces the pinned file's shape: the patch locates its hunk at line 39,
    # so the fixture is padded to put `#endif` there, followed by the exact
    # context the hunk expects on both sides of the removed comment and constant.
    filler = ''.join('/* pinned line %d */\n' % number for number in range(1, 39))
    return (filler + '#endif\n\n\n' + UPSTREAM_COMMENT + '\n' + UPSTREAM_SPIN + '\n'
            + UPSTREAM_TAIL)


class HarmonyOrtPoolSpinTest(unittest.TestCase):
    def test_patch_replaces_the_upstream_constant(self):
        text = builder.POOL_PATCH.read_text()
        self.assertIn('-' + UPSTREAM_SPIN, text)
        self.assertIn('+' + builder.POOL_SPIN_MARKER, text)
        self.assertNotIn('+' + UPSTREAM_SPIN, text)

    def test_pool_patch_is_applied_once_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            source = build / '_deps/pthreadpool-src'
            (source / 'src').mkdir(parents=True)
            header = source / 'src/threadpool-common.h'
            header.write_text(header_fixture())
            self.assertTrue(builder.apply_pool_patch(build))
            patched = header.read_text()
            self.assertIn(builder.POOL_SPIN_MARKER, patched)
            self.assertNotIn(UPSTREAM_SPIN, patched)
            # A rebuilt tree must stay correct instead of failing on a second run.
            self.assertFalse(builder.apply_pool_patch(build))
            self.assertEqual(header.read_text(), patched)

    def test_missing_pool_source_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError) as caught:
                builder.apply_pool_patch(Path(directory))
            self.assertIn('pthreadpool source missing', str(caught.exception))

    def test_unpatched_result_is_rejected(self):
        # A patch that silently does nothing must be reported, not recorded.
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            source = build / '_deps/pthreadpool-src'
            (source / 'src').mkdir(parents=True)
            (source / 'src/threadpool-common.h').write_text('#endif\n')
            with self.assertRaises((RuntimeError, subprocess.CalledProcessError)):
                builder.apply_pool_patch(build)

    def test_patch_applies_to_the_pinned_upstream_source(self):
        candidates = sorted((ROOT / 'third_party/.derived').glob(
            'onnxruntime-ohos-*/*/_deps/pthreadpool-src/src/threadpool-common.h'))
        pristine = [path for path in candidates if UPSTREAM_SPIN in path.read_text()]
        if not pristine:
            self.skipTest('no unpatched derived pthreadpool source to check against')
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory) / 'src'
            tree.mkdir()
            (tree / 'threadpool-common.h').write_text(pristine[0].read_text())
            result = subprocess.run(
                ['patch', '-p1', '--dry-run', '--input', str(builder.POOL_PATCH)],
                cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
