"""Execute the production Community scheduling scope against platform faults."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'asr/harmony/sdk/src/main/cpp/community_diarization.cpp'
FIXTURES = Path(__file__).with_name('harmony_scheduling')


def community_scheduling_source():
    text = SOURCE.read_text()
    marker = text.index('// The engine-wide scheduling request')
    guard = text.rindex('#if defined(__OHOS__)', 0, marker)
    return text[text.index('namespace {', guard):text.index('#else', marker)]


class HarmonyCommunitySchedulingTest(unittest.TestCase):
    def test_request_outside_current_mask_reaches_kernel(self):
        self.run_scheduling('kernel-request')

    def test_platform_faults_and_diagnostics(self):
        self.run_scheduling()

    def run_scheduling(self, *args):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if compiler is None:
            self.skipTest('C++17 compiler unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'community-scheduling.h').write_text('''
#include <array>
#include <cerrno>
#include <cstring>
#include <memory>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include <sched.h>
#include <qos/qos.h>
#include <hilog/log.h>
#include <unistd.h>
''' + community_scheduling_source())
            binary = root / 'community-scheduling-test'
            subprocess.run([compiler, '-std=c++17', '-pthread', '-D__OHOS__',
                            '-I' + str(FIXTURES), '-I' + str(root),
                            str(FIXTURES / 'community_scheduling_test.cc'),
                            str(FIXTURES / 'platform_stubs.cc'), '-o', str(binary)], check=True)
            subprocess.run([str(binary), *args], check=True, timeout=15)


if __name__ == '__main__':
    unittest.main()
