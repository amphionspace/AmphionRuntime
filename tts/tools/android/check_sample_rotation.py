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
    parser.add_argument("--playback", action="store_true",
                        help="Check the app's AudioFlinger track instead of PCM callbacks (Android 10)")
    parser.add_argument("--package", default="com.lits.tts.studentdemo")
    parser.add_argument("--active-request", help="Observe an already running request instead of tapping Start")
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
            time.sleep(0.8)  # Configuration updates precede the rotation animation.
            capture = subprocess.Popen(
                base + ["logcat", "-v", "raw", "-T", "1", "-s", "LitsTtsSample:I"],
                stdout=output, stderr=subprocess.STDOUT,
            )
            time.sleep(0.3)
            baseline = len(args.log.read_text())

            def logs():
                return args.log.read_text()[baseline:]

            if not args.active_request:
                adb("shell", "input", "tap", *map(str, args.start))
            started = True
            request = args.active_request
            if request is None:
                match = wait_for(lambda: re.search(r"onStart requestId=(\S+)", logs()), "request start")
                request = match.group(1)

            def check_active():
                text = logs()
                for event in ("onStop", "onError", "onComplete"):
                    assert f"{event} requestId={request}" not in text, text
                assert "sample 已启动" not in text, "Activity restarted during request"
                return text

            def sequences():
                text = check_active()
                return [int(n) for n in re.findall(
                    rf"onData requestId={re.escape(request)} sequence=(\d+)", text)]

            pid = adb("shell", "pidof", args.package).strip()

            def playback():
                check_active()
                dump = adb("shell", "dumpsys", "media.audio_flinger")
                for line in dump.splitlines():
                    fields = line.split()
                    # Android 10 mixer-track row: Id Active Client ... Server.
                    if len(fields) > 19 and fields[1:3] == ["yes", pid]:
                        return fields[0], int(fields[17], 16)
                return None

            track = wait_for(playback, "active playback track") if args.playback else None
            if not args.playback:
                wait_for(sequences, "first audio chunk")
            for rotation, orientation in (("1", "land"), ("0", "port")):
                before = playback()[1] if args.playback else sequences()[-1]
                setting("user_rotation", rotation)
                wait_for(lambda: f"-{orientation}-" in adb("shell", "am", "get-config"), orientation)
                time.sleep(0.8)
                if args.playback:
                    def advanced():
                        current = playback()
                        if current is None:
                            return False
                        assert current[0] == track[0], "Playback track replaced during rotation"
                        return current[1] > before
                    wait_for(advanced, "same playback track advances after rotation")
                else:
                    wait_for(lambda: sequences()[-1] >= before + 3, "same request continues after rotation")
                print(f"PASS {orientation}: {request} continued", flush=True)

            adb("shell", "input", "tap", *map(str, args.stop))
            wait_for(lambda: f"onStop requestId={request}" in logs(), "explicit stop")
            if args.playback:
                def track_stopped():
                    dump = adb("shell", "dumpsys", "media.audio_flinger")
                    return not any(line.split()[1:3] == ["yes", pid]
                                   for line in dump.splitlines())
                wait_for(track_stopped, "no active app playback track after Stop")
            started = False
            print("PASS explicit Stop still cancels the request", flush=True)
        finally:
            setting("user_rotation", "0")
            if started:
                wait_for(lambda: "-port-" in adb("shell", "am", "get-config"), "cleanup portrait")
                time.sleep(0.8)
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
