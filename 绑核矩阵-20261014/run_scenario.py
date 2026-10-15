#!/usr/bin/env python3
"""四场绑核/屏幕矩阵的单场编排器。

每场：等待降温 -> 记录起始温度 -> 后台流式抓 hilog -> 启动 run_device_stress.py
-> 检测会话首帧 -> (熄屏场) 定时 suspend / 结束前 wakeup -> 采样 /proc 与温度
-> 收尾记录结束温度。所有外部采样写入 <out>/sampler.ndjson。
"""
import argparse, json, os, re, signal, subprocess, sys, threading, time
from pathlib import Path

HDC = str(Path.home() / ".local/share/harmony/command-line-tools/sdk/default/openharmony/toolchains/hdc")
REPO = Path("/Users/momo/project/AmphionRuntime")
DRIVER = REPO / "delivery/harmony-dingqiao/delivery/run_device_stress.py"
BUNDLE = "com.amphion.asr.harmony.demo"


def hdc(*args, timeout=30):
    return subprocess.run([HDC, *args], capture_output=True, text=True, timeout=timeout).stdout


def shell(cmd, timeout=30):
    return hdc("shell", cmd, timeout=timeout)


def temps():
    out = shell("hidumper -s ThermalService -a -t")
    d, key = {}, None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Type:"):
            key = line.split(":", 1)[1].strip()
        elif line.startswith("Temperature:") and key:
            try:
                d[key] = int(line.split(":", 1)[1].strip()) / 1000.0
            except ValueError:
                pass
            key = None
    return d


def battery():
    out = shell("hidumper -s BatteryService -a -i")
    d = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            if k in ("capacity", "chargingStatus", "temperature", "nowCurrent"):
                try:
                    d[k] = int(v.strip())
                except ValueError:
                    pass
    return d


def cool_down(target_c, max_wait_s, log):
    start = time.time()
    while True:
        t = temps()
        back = t.get("shell_back", 0)
        if back <= target_c or time.time() - start > max_wait_s:
            log(f"降温结束 shell_back={back:.2f}C 等待={time.time()-start:.0f}s")
            return t
        log(f"降温中 shell_back={back:.2f}C 目标<={target_c}C")
        time.sleep(20)


class Sampler(threading.Thread):
    """每 interval 秒采一次：进程 cpuset / 掩码 / CPU 时间 / 线程数 / 温度。"""

    def __init__(self, path, interval=2.0, thread_every=5):
        super().__init__(daemon=True)
        self.path = path
        self.interval = interval
        self.thread_every = thread_every
        self.stop_flag = threading.Event()
        self.pid = None

    def find_pid(self):
        out = shell(f"pidof {BUNDLE}").strip()
        return out.split()[0] if out else None

    def run(self):
        n = 0
        with open(self.path, "w", encoding="utf-8") as fh:
            while not self.stop_flag.is_set():
                rec = {"wallTimeMs": int(time.time() * 1000)}
                try:
                    live = self.find_pid()
                    if live:
                        self.pid = live
                    rec["pid"] = self.pid
                    if self.pid:
                        p = self.pid
                        blob = shell(
                            f"cat /proc/{p}/cpuset 2>/dev/null; echo '|'; "
                            f"grep -E 'Cpus_allowed_list|Threads' /proc/{p}/status 2>/dev/null; echo '|'; "
                            f"cat /proc/{p}/stat 2>/dev/null | cut -d' ' -f14-17"
                        )
                        parts = blob.split("|")
                        rec["cpuset"] = parts[0].strip() if parts else ""
                        if len(parts) > 1:
                            for ln in parts[1].splitlines():
                                if "Cpus_allowed_list" in ln:
                                    rec["cpus_allowed"] = ln.split(":", 1)[1].strip()
                                if "Threads" in ln:
                                    rec["threads"] = ln.split(":", 1)[1].strip()
                        if len(parts) > 2:
                            rec["cpu_ticks"] = parts[2].strip()
                        if n % self.thread_every == 0:
                            masks = shell(
                                f"for t in /proc/{p}/task/*; do grep -h Cpus_allowed_list $t/status 2>/dev/null; done"
                            )
                            agg = {}
                            for ln in masks.splitlines():
                                if ":" in ln:
                                    m = ln.split(":", 1)[1].strip()
                                    agg[m] = agg.get(m, 0) + 1
                            rec["thread_masks"] = agg
                    if n % self.thread_every == 0:
                        rec["temps"] = temps()
                        rec["battery"] = battery()
                except Exception as exc:  # 采样不得影响被测
                    rec["sampler_error"] = str(exc)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                self.stop_flag.wait(self.interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--cpu-ids", default="none")
    ap.add_argument("--screen", choices=["on", "off"], default="on")
    ap.add_argument("--suspend-after", type=float, default=60.0, help="会话首帧后多少秒熄屏")
    ap.add_argument("--audio-seconds", type=float, default=523.7)
    ap.add_argument("--unlock-at", type=float, default=None,
                    help="会话首帧后多少秒亮屏并滑动解锁（恢复 top-app）；默认输入结束后才亮屏")
    ap.add_argument("--pace-ms", type=int, default=20)
    ap.add_argument("--num-threads", type=int, default=4)
    ap.add_argument("--cool-to", type=float, default=30.0)
    ap.add_argument("--cool-max", type=float, default=420.0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    logf = open(out / "orchestrator.log", "w", encoding="utf-8")

    def log(msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(line, flush=True)
        logf.write(line + "\n")
        logf.flush()

    log(f"=== 场次 {args.name} 开始 cpuIds={args.cpu_ids} screen={args.screen} ===")
    shell("power-shell wakeup")
    shell("power-shell timeout -o 3600000")
    shell(f"aa force-stop {BUNDLE}")  # 确保每场从冷进程开始
    time.sleep(2)
    pre_t = cool_down(args.cool_to, args.cool_max, log)
    pre_b = battery()
    log(f"起始温度 {json.dumps(pre_t, ensure_ascii=False)} 电池 {pre_b}")

    hilog_path = out / "hilog-stream.txt"
    shell("hilog -r")  # 先清缓冲，再开流，避免抓到上一场的残留
    time.sleep(1)
    hl = subprocess.Popen([HDC, "hilog"], stdout=open(hilog_path, "w"), stderr=subprocess.DEVNULL)

    cmd = [
        sys.executable, str(DRIVER),
        "--data-dir", args.data_dir, "--mode", "paced", "--files", "1", "--cycles", "1",
        "--pace-ms", str(args.pace_ms), "--enable-diarization", "--capture-diagnostics",
        "--installed-package", "--asr-qos", "user-initiated",
        "--asr-num-threads", str(args.num_threads), "--diarization-hop-ms", "2000",
        "--diarization-encoder", "auto", "--timeout", "1800",
        "--sample-interval", "1.0", "--output-root", str(out / "stress"),
    ]
    if args.cpu_ids != "none":
        cmd += ["--asr-cpu-ids", args.cpu_ids]
    if args.screen == "off":
        cmd += ["--allow-screen-off", "--hold-mic-capture"]
    log("驱动命令: " + " ".join(cmd))

    sampler = Sampler(out / "sampler.ndjson")
    sampler.start()
    drv_log = open(out / "driver.log", "w", encoding="utf-8")
    t_start = time.time()
    drv = subprocess.Popen(cmd, cwd=str(REPO), stdout=drv_log, stderr=subprocess.STDOUT)

    # 检测会话首帧
    t0 = None
    while drv.poll() is None and t0 is None:
        try:
            txt = hilog_path.read_text(encoding="utf-8", errors="replace")
            if "event=DIARIZATION_AUDIO_APPENDED" in txt or "event=AUDIO_PROGRESS" in txt:
                t0 = time.time()
        except FileNotFoundError:
            pass
        if t0 is None:
            time.sleep(1)
    if t0:
        log(f"检测到会话首帧，T0=+{t0-t_start:.1f}s")
    else:
        log("未检测到会话首帧（驱动已退出）")

    suspended = False
    if args.screen == "off" and t0:
        def screen_plan():
            nonlocal suspended
            time.sleep(args.suspend_after)
            if drv.poll() is None:
                shell("power-shell suspend")
                suspended = True
                log(f"已熄屏（会话首帧后 {args.suspend_after:.0f}s）")
            wake_at = args.unlock_at if args.unlock_at is not None else args.audio_seconds + 5
            time.sleep(max(0.0, wake_at - args.suspend_after))
            if drv.poll() is None:
                shell("power-shell wakeup")
                time.sleep(1.5)
                shell("uinput -T -m 600 1800 600 600 300")
                time.sleep(1.5)
                pid = shell(f"pidof {BUNDLE}").strip().split()
                cs = shell(f"cat /proc/{pid[0]}/cpuset").strip() if pid else "?"
                log(f"已亮屏并解锁（会话首帧后 {wake_at:.0f}s），cpuset={cs}")
        threading.Thread(target=screen_plan, daemon=True).start()

    rc = drv.wait()
    t_end = time.time()
    sampler.stop_flag.set()
    sampler.join(timeout=10)
    hl.terminate()
    shell("power-shell wakeup")
    post_t = temps()
    post_b = battery()
    log(f"驱动退出 rc={rc} 墙钟={t_end-t_start:.1f}s 结束温度 {json.dumps(post_t, ensure_ascii=False)} 电池 {post_b}")

    meta = {
        "name": args.name, "cpu_ids": args.cpu_ids, "screen": args.screen,
        "pace_ms": args.pace_ms, "num_threads": args.num_threads,
        "audio_seconds": args.audio_seconds, "suspend_after_s": args.suspend_after,
        "suspended": suspended, "driver_rc": rc,
        "wall_start": t_start, "wall_t0": t0, "wall_end": t_end,
        "wall_total_s": t_end - t_start,
        "temps_pre": pre_t, "temps_post": post_t,
        "battery_pre": pre_b, "battery_post": post_b,
        "command": cmd,
    }
    (out / "scenario.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"=== 场次 {args.name} 结束 ===")
    return 0 if rc == 0 else rc


if __name__ == "__main__":
    sys.exit(main())
