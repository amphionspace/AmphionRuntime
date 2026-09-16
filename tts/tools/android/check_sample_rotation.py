#!/usr/bin/env python3
"""Device regression: an active sample request survives rotation and can stop.

Requires a provisioned, foreground sample in portrait with a long input.
Pass the portrait coordinates of Synthesize (or Speak) and Stop. Captures
callbacks without clearing logcat, and restores the device rotation settings.
"""

import argparse
import re
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--start", type=int, nargs=2, required=True)
    parser.add_argument("--stop", type=int, nargs=2, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    base = [args.adb, "-s", args.serial]

    def adb(*command):
        return subprocess.check_output(base + list(command), text=True, timeout=15)

    def setting(name, value):
        adb("shell", "settings", "put", "system", name, value)

    def wait_for(predicate, description, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.2)
        raise AssertionError("Timed out: " + description)

    saved = {name: adb("shell", "settings", "get", "system", name).strip()
             for name in ("accelerometer_rotation", "user_rotation")}
    capture = None
    started = False
    args.log.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to replace evidence from a prior run.
    with args.log.open("x") as output:
        try:
            setting("accelerometer_rotation", "0")
            setting("user_rotation", "0")
            wait_for(lambda: "-port-" in adb("shell", "am", "get-config"), "portrait")
            capture = subprocess.Popen(
                base + ["logcat", "-v", "raw", "-T", "1", "-s", "LitsTtsSample:I"],
                stdout=output, stderr=subprocess.STDOUT,
            )
            time.sleep(0.3)
            baseline = len(args.log.read_text())

            def logs():
                return args.log.read_text()[baseline:]

            adb("shell", "input", "tap", *map(str, args.start))
            started = True
            match = wait_for(lambda: re.search(r"onStart requestId=(\S+)", logs()), "request start")
            request = match.group(1)

            def sequences():
                text = logs()
                for event in ("onStop", "onError", "onComplete"):
                    assert f"{event} requestId={request}" not in text, text
                assert "sample 已启动" not in text, "Activity restarted during request"
                return [int(n) for n in re.findall(
                    rf"onData requestId={re.escape(request)} sequence=(\d+)", text)]

            wait_for(sequences, "first audio chunk")
            for rotation, orientation in (("1", "land"), ("0", "port")):
                before = sequences()[-1]
                setting("user_rotation", rotation)
                wait_for(lambda: f"-{orientation}-" in adb("shell", "am", "get-config"), orientation)
                wait_for(lambda: sequences()[-1] >= before + 3, "same request continues after rotation")
                print(f"PASS {orientation}: {request} continued", flush=True)

            adb("shell", "input", "tap", *map(str, args.stop))
            wait_for(lambda: f"onStop requestId={request}" in logs(), "explicit stop")
            started = False
            print("PASS explicit Stop still cancels the request", flush=True)
        finally:
            setting("user_rotation", "0")
            if started:
                wait_for(lambda: "-port-" in adb("shell", "am", "get-config"), "cleanup portrait")
                adb("shell", "input", "tap", *map(str, args.stop))
            for name, value in saved.items():
                if value == "null":
                    adb("shell", "settings", "delete", "system", name)
                else:
                    setting(name, value)
            if capture is not None:
                capture.terminate()
                capture.wait(timeout=5)


if __name__ == "__main__":
    main()
