# 鸿蒙三人填单角色分离全归"其他角色"（客户 #29，2026-11-24 复测）证据

日期：2026-11-24。设备：鸿蒙 Mate 80，当前 `main` 构建（0.3.30 线）。客户附件
`meetingMinutes-20261124-110202-056.wav`（24.4 s，16 kHz 单声道）、录屏 `SVID_20261124_110201_1.mp4`。
证据目录 `~/amphion-evidence/20261124-issue29/`。结论：**不改代码**（用户决定），作为模型能力边界回复。

## 现象复现

`run_device_stress.py --mode customer-meeting-minutes --installed-package`（默认参数）回放，final 文本与客户完全一致：
"我是照明电话13800223344报案内容是电动车丢失。我是孙丽电话15988776655，我补充一下车辆颜色是白色。我是周强，我是现场的保安可以作证。YEAH。"
窗口里 5 个展示句 `speakerIndex=-1`、`overlap=true`；turns 19 段，73% 时长标 overlap；按文本 span 看赵明段 → 角色 0、孙丽段 → 角色 1、周强段一半 0 一半 1。

## 主机侧分析

- 说话人区间（ASR token 时间戳）：赵明 2.5–10.3 s，孙丽 11.4–16.8 s，周强 17.3–23.2 s；句间停顿 0.4~0.6 s，整段为一句。
- 声纹相似度（整段嵌入，余弦）：

| 模型 | 孙丽–赵明 | 周强–赵明 | 周强–孙丽 | 同一人前后半句 |
| --- | --- | --- | --- | --- |
| eres2net | 0.25 | **0.68** | 0.44 | 赵明 0.64 / 孙丽 0.40 / 周强 0.33 |
| campplus | 0.44 | **0.67** | **0.71** | 赵明 0.75 / 孙丽 0.67 / 周强 0.39 |

- Sortformer-66M-4spk（主机 ORT 1.16.3）：只有轨道 0（0~24 s）与轨道 1（1~22 s）活跃，且几乎全程同时活跃；没有第三条轨道。
- 主机 ASR（同模型，不带警务增强）："我是赵敏…我是县城的保安可以作证"，无 "YEAH"；真机带增强为"照明"、"现场"。预置热词池无"赵明/照明"。
- "YEAH。"来自会话收尾对最后 0.6 s（24.02–24.06 s）的单独 final（`FINAL_TAIL scope=session` → `utteranceIndex=2` 620 ms）；填充词门禁词表无 yeah。

## 判定

- 全归"其他角色"：三人声线在两套声纹模型与 Sortformer 上均不可分，SDK 按 #77 既定口径（同句两个身份重叠不冒认）输出 -1；与 #36 同一批说话人、同一结论。可选的"重叠句按文本 span 主导角色归属"只能得到两个角色且放宽保守口径，本轮不做。
- "照明"：人名识别错误，需热词。
- "YEAH。"：尾音幻觉，本轮不改填充词门禁。
- 逗号：标点模型对连读短句效果。

## 复现命令

```bash
printf '{"files":[{"path":"case.wav","sha256":"<sha256>","required_suffix":"可以作证"}]}' > tail-manifest.json
python3 delivery/harmony-dingqiao/delivery/run_device_stress.py --device <serial> --installed-package \
  --mode customer-meeting-minutes --data-dir <dir-with-case.wav> --files 1 --cycles 1 \
  --expected-tail-manifest tail-manifest.json --output-root <out>
# report.json: resultHex / speakerWindowsHex / speakerTurnsHex 为 UTF-16BE hex JSON
```
