"""安卓真机 speakerTurns JSON → 与客户参考 RTTM/UEM 评分（23_score_diarization_scenarios 口径：10 ms 栅格、collar 0、计重叠、Hungarian）。

每份 voiceprint 运行文件同时给出两列：speakerIndex（声纹身份）与 modelSpeakerIndex（模型槽位），
即同一次运行、同一段音频上的严格 A/B。

用法: DQ_SCORER_DIR=<official-scorer 目录> python3 35_score_android_identity_device.py <目录，含 voiceprint/ 与 model/ 子目录>
结果文件由 DiarizationDerInstrumentedTest 产出；见 docs/speaker/ANDROID_VOICEPRINT_IDENTITY_DEVICE_20261105.md。
"""
import glob, importlib.util, json, os, sys
import numpy as np

R = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("sc", f"{R}/asr/tools/speaker/23_score_diarization_scenarios.py")
sc = importlib.util.module_from_spec(spec); spec.loader.exec_module(sc)
E = os.environ.get("DQ_SCORER_DIR", os.path.expanduser("~/.cache/amphion-runtime/customer-inputs-20261030/dq5-diar-eval-20261027/official-scorer"))
REF_ID = {
    "meetingMinutes-20260918-100350-257.wav": "100350-257",
    "meetingMinutes-20260918-102010-230.wav": "102010-230",
    "meetingMinutes-20260918-111223-816.wav": "111223-816",
    "会议-离线-无角色4.wav": "recording-a",
}

def uem_mask(rid, n):
    p = f"{E}/uem/dingqiao_meeting__{rid}.uem"
    if not os.path.exists(p):
        return None
    mask = np.zeros(n, bool)
    for line in open(p):
        parts = line.split()
        if len(parts) >= 4:
            b, e = float(parts[2]), float(parts[3])
            mask[max(0, int(b / sc.STEP)):min(n, int(e / sc.STEP))] = True
    return mask

def hyp_segments(data, field):
    segs, unknown = [], 0
    for w in data.get("windows", []):
        for t in w["speakerTurns"]:
            b, e = t["beginTime"] / 1000.0, t["endTime"] / 1000.0
            if e <= b:
                continue
            labels = []
            primary = t.get(field, -1)
            if primary is None or primary < 0:
                unknown += 1
            else:
                labels.append(primary)
            if field == "speakerIndex":
                labels += [s for s in t.get("secondarySpeakerIndexes", []) if s >= 0]
            for lab in dict.fromkeys(labels):
                segs.append((b, e, f"spk{lab}"))
    return segs, unknown

def score_file(path, field):
    data = json.load(open(path, encoding="utf-8"))
    rid = REF_ID[data["asset"]]
    ref = sc.read_rttm(f"{E}/ref/dingqiao_meeting__{rid}.rttm")
    hyp, unknown = hyp_segments(data, field)
    duration = max([e for _, e, _ in ref] + [e for _, e, _ in hyp] + [data["audioMs"] / 1000.0])
    n = int(duration / sc.STEP) + 1
    m = sc.score_one(ref, hyp, duration, uem_mask(rid, n))
    m["unknown_turns"] = unknown
    m["rtf"] = data.get("rtf")
    m["mode"] = data.get("speakerIdentityMode")
    return rid, m

def table(rows, title):
    print(f"\n=== {title} ===")
    print(f"{'录音':12s} {'DER':>7s} {'漏检':>6s} {'误报':>6s} {'混淆':>6s} {'参考人数':>4s} {'输出人数':>4s} {'UNKNOWN段':>5s} {'RTF':>6s}")
    tot = {"der": [], "w": []}
    for rid, m in rows:
        print(f"{rid:12s} {m['der']*100:6.2f}% {m['miss_rate']*100:5.1f}% {m['fa_rate']*100:5.1f}% {m['conf_rate']*100:5.1f}% "
              f"{m['ref_spk']:>4d} {m['hyp_spk']:>4d} {m['unknown_turns']:>5d} {m['rtf'] if m['rtf'] is None else round(m['rtf'],3)!s:>6}")
        tot["der"].append(m["der"]); tot["w"].append(m["total"])
    if rows:
        print(f"{'时长加权合计':12s} {100*np.average(tot['der'], weights=tot['w']):6.2f}%")

root = sys.argv[1]
for mode in ("voiceprint", "model"):
    files = sorted(f for f in glob.glob(f"{root}/{mode}/*.json") if os.path.getsize(f) > 0)
    if not files:
        continue
    if mode == "voiceprint":
        table([score_file(f, "speakerIndex") for f in files], "安卓真机 · speakerIdentityMode=voiceprint（speakerIndex = 声纹身份）")
        table([score_file(f, "modelSpeakerIndex") for f in files], "同一次运行 · modelSpeakerIndex（模型槽位，严格同音频 A/B）")
    else:
        table([score_file(f, "speakerIndex") for f in files], "安卓真机 · speakerIdentityMode=model（独立一轮，交叉验证）")
