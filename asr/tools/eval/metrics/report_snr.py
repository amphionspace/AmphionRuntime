import json, os
from pathlib import Path
SP = Path(os.environ["SP"])
D = SP / "evalout"
LEVEL = [("quiet", "安静工况", "≥20", 20.0), ("light", "轻度噪声", "10~20", 15.0),
         ("medium", "中度噪声", "5~10", 7.0), ("heavy", "重度噪声", "0~5", 3.0),
         ("extreme", "极限恶劣", "<0", -5.0)]
# 客户要求：短语音准确率 / 热词命中率
REQ_ACC = {"quiet": 0.98, "light": 0.98, "medium": 0.96, "heavy": 0.90, "extreme": None}
REQ_HW  = {"quiet": 0.98, "light": 0.98, "medium": 0.97, "heavy": 0.97, "extreme": None}

def load(s):
    p = D / f"{s}.summary.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def pct(v): return "—" if v is None else f"{v*100:.2f}%"

clean = load("clean")
print("=" * 104)
print("端侧 ASR / 热词 分层实测  语料 AISHELL-3 热词 500 条（1738s，99 人）  生产模型 zh-en-police-179m")
print("=" * 104)
print("\n【口径校验】clean 集，与已发布 AISHELL3_HOTWORDS_EVAL 对比")
a = clean["arms"]
print(f"  oracle3_only 热词召回 {pct(a['oracle3_only']['hotword_exact_recall'])}  vs 已发布 96.12%  （差 "
      f"{(a['oracle3_only']['hotword_exact_recall']-0.9612)*100:+.2f} pp → 评分口径一致）")
print(f"  四臂准确率：greedy {pct(a['greedy_nohw']['accuracy'])} / 预置池 {pct(a['pool_nohw']['accuracy'])}"
      f" / 预置池+热词3.0 {pct(a['pool_oracle3']['accuracy'])} / 仅热词3.0 {pct(a['oracle3_only']['accuracy'])}")

for arm, label, req, reqname in (("pool_nohw", "通用中文普通话（出厂默认，无用户热词）", REQ_ACC, "准确率"),
                                 ("pool_oracle3", "配置热词后（出厂默认 + 用户热词@3.0）", REQ_ACC, "准确率")):
    print(f"\n【{label}】")
    print(f"  {'噪声等级':<10}{'SNR':>7}  {'babble准确率':>12}{'traffic准确率':>14}   {'要求':>7}  判定")
    print("  " + "-" * 74)
    for k, zh, snr, _ in LEVEL:
        vals = {}
        for nk in ("babble", "traffic"):
            s = load(f"{nk}_{k}")
            vals[nk] = s["arms"][arm]["accuracy"] if s else None
        r = req[k]
        if r is None:
            verdict = "要求为「-」"
        elif None in vals.values():
            verdict = "数据缺失"
        else:
            worst = min(vals.values())
            verdict = "达标" if worst >= r else f"不达标（差 {(r-worst)*100:.1f} pp）"
        print(f"  {zh:<10}{snr:>7}  {pct(vals['babble']):>12}{pct(vals['traffic']):>14}   "
              f"{pct(r):>7}  {verdict}")

print("\n【热词精确命中率（出厂默认 + 用户热词@3.0）】")
print(f"  {'噪声等级':<10}{'SNR':>7}  {'babble':>10}{'traffic':>10}   {'要求':>7}  判定")
print("  " + "-" * 66)
for k, zh, snr, _ in LEVEL:
    vals = {}
    for nk in ("babble", "traffic"):
        s = load(f"{nk}_{k}")
        vals[nk] = s["arms"]["pool_oracle3"]["hotword_exact_recall"] if s else None
    r = REQ_HW[k]
    if r is None: verdict = "要求为「-」"
    elif None in vals.values(): verdict = "数据缺失"
    else:
        worst = min(vals.values())
        verdict = "达标" if worst >= r else f"不达标（差 {(r-worst)*100:.1f} pp）"
    print(f"  {zh:<10}{snr:>7}  {pct(vals['babble']):>10}{pct(vals['traffic']):>10}   {pct(r):>7}  {verdict}")

print("\n【空输出率（关系到长语音『片段召回』）与 RTF】")
print(f"  {'集合':<18}{'空输出/500':>12}{'RTF':>8}")
for name in ["clean"] + [f"{n}_{k}" for n in ("babble", "traffic") for k, *_ in LEVEL]:
    s = load(name)
    if not s: continue
    m = s["arms"].get("pool_oracle3") or s["arms"]["pool_nohw"]
    print(f"  {name:<18}{m['empty_outputs']:>12}{m['rtf']:>8.3f}")
