#!/usr/bin/env python3
"""Check patched ORT completion and allocator ownership with host fixtures.

The method and notifier bodies come from the actual runtime source. Only queues,
the profiler, and platform mutex/CV primitives are replaced by the test fixture.
The allocator fixture also executes the real provider destructor against live
and freed buffers. Real allocator/RSS and device lifecycle gates remain required.
"""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


FIXTURE = Path(__file__).parent / "tests/harmony_onnxruntime/completion_test.cc.in"


def verify(source: Path) -> None:
    header = source / "include/onnxruntime/core/platform/EigenNonBlockingThreadPool.h"
    text = header.read_text()
    start = text.index("  void EndParallelSectionInternal(")
    end = text.index("\n  void EndParallelSection(", start)
    notifiers = []
    for name, statement in (
        ("FinishChild", "ps.tasks_finished++;"),
        ("FinishDispatch", "ps.dispatch_done.store(true, std::memory_order_release);"),
        ("FinishWork", "ps.work_done.store(true, std::memory_order_release);"),
    ):
        pattern = (r"\{\s*std::lock_guard<OrtMutex> completion_lock\(ps.completion_mutex\);\s*"
                   + re.escape(statement) + r"\s*ps.completion_cv.notify_one\(\);\s*\}")
        matches = re.findall(pattern, text)
        if len(matches) != 1:
            raise RuntimeError(f"Expected one mutex-protected notifier for {name}")
        notifiers.append(f"void {name}(Section& ps) {matches[0]}")
    test = FIXTURE.read_text().replace("/* END_PARALLEL_SECTION */", text[start:end])
    test = test.replace("/* COMPLETION_NOTIFIERS */", "\n".join(notifiers))
    provider = (source / "onnxruntime/core/providers/xnnpack/xnnpack_execution_provider.cc").read_text()
    start = provider.index("XnnpackExecutionProvider::~XnnpackExecutionProvider() {")
    end = provider.index("\n}", start) + 2
    arena = FIXTURE.with_name("arena_lifetime_test.cc.in").read_text()
    arena = arena.replace("/* DESTRUCTOR */", provider[start:end])
    with tempfile.TemporaryDirectory(prefix="amphion-ort-completion-") as directory:
        for name, program in (("completion", test), ("arena_lifetime", arena)):
            cpp = Path(directory) / f"{name}_test.cc"
            binary = Path(directory) / f"{name}_test"
            cpp.write_text(program)
            subprocess.run(["c++", "-std=c++17", "-O2", "-pthread", str(cpp), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Patched ONNX Runtime checkout")
    verify(parser.parse_args().source)
