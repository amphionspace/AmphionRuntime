import subprocess
import threading

class CPPProcessWrapper:
    def __init__(self, bin_path, *, strict_startup=False, strict_runtime=False, process_name=None):
        self.bin_path = bin_path
        self.strict_startup = strict_startup
        self.strict_runtime = strict_runtime
        self.process_name = process_name or bin_path
        self.proc = subprocess.Popen(
            [bin_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # 行缓冲
        )
        self._lock = threading.Lock()
        if self.strict_startup:
            self._check_startup()

    def _read_stderr(self):
        if self.proc.stderr is None:
            return ""
        try:
            return self.proc.stderr.read().strip()
        except Exception:
            return ""

    def _build_error(self, prefix):
        stderr = self._read_stderr()
        if stderr:
            return RuntimeError(
                f"{prefix} ({self.process_name}, path={self.bin_path}). stderr: {stderr}"
            )
        return RuntimeError(f"{prefix} ({self.process_name}, path={self.bin_path})")

    def _check_startup(self):
        try:
            self.proc.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            return
        raise self._build_error("TN_MODULE process failed to start")

    def communicate(self, text):
        # 预处理：确保输入只有一行且不为空
        input_text = text.replace("\n", " ").strip()
        if not input_text:
            return ""
        
        with self._lock:
            try:
                if self.proc.poll() is not None:
                    raise self._build_error(
                        f"TN_MODULE process exited with code {self.proc.returncode}"
                    )
                if self.proc.stdin is None or self.proc.stdout is None:
                    raise RuntimeError("stdin/stdout pipe is not available")
                self.proc.stdin.write(input_text + "\n")
                self.proc.stdin.flush()
                out = self.proc.stdout.readline()
                if not out:
                    if self.strict_runtime:
                        raise self._build_error("TN_MODULE process returned empty output")
                    return input_text
                return out.strip()
            except Exception as e:
                if self.strict_runtime:
                    raise
                # 返回原文本，避免单句失败直接打断整条推理链路
                return input_text

    def close(self):
        self.proc.terminate()
