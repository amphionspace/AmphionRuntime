# 机主接话泄露：鸿蒙真机定位与修复（2026-10-29）

## 问题

机主识别 + 实时转写：机主停止说话的瞬间非机主接上说话，非机主的首句被当作机主的话录入。
鸿蒙自 0.3.25 起已有"换人干净切分"（提交 `a49af8be` 等），但客户仍报此现象。

## 夹具：第一次真正执行 `speaker-vad-turn`

该验收模式自 0.3.20 起每次交付都被豁免，理由是"需要客户目标说话人夹具，本检出与受控数据包中
均不存在"。本轮用 `asr/tools/speaker/17_build_speaker_turn_device_fixture.py` 从 aishell3 构造：

- 取一个说话人最长的 3 条录音注册声纹；
- 每个 case 是该说话人的一条录音后面**无间隙**接另一个说话人的一条短录音（1.4~1.6 s，
  正是流式离场规则最弱的长度）；
- 断言文本取自两半各自单独解码的结果，所以 case 判的是**归属**而不是识别准确率。断言块取
  2~3 字且不含数字，以躲开设备侧的标点插入与 ITN 改写（第一版用 6 字断言，被"黎耀祥笑称"
  插入的逗号和"十六"→"16"判废）。

被拒绝的那段在鸿蒙上发**空 final** + `SPEAKER_VAD_REJECTED` 事件，非机主文字不进调用方，
所以"机主的话在、非机主的话不在、非空 final 条数正确"三条合起来就是判据。

## 首轮结果：6 例中 2 例泄露

| 用例 | 非机主首句 | 发布的 final | 判定 |
|---|---|---|---|
| turn-00~03 | 香木/满园/永洪/大臣… | 仅机主内容 | 拦住 |
| turn-04 | 周杰伦… | `搜狐娱乐讯据港媒报道，**周杰伦的**。` | **泄露** |
| turn-05 | 金莎… | `来一首死了，都要爱。**莎的歌**。`（2 条非空 final） | **泄露** |

另外 6 例中有 4 例是靠**收尾补救**才检出离场（`speechEndsBeforeFinish=0`），流式规则没抓住。

## 分支 A：finish 的"高置信度专用"策略把声纹证据丢了

会话 5 的诊断事件链：

```
score 0.709 → 0.737 → 0.670 → 0.486 → 0.389 → 0.174(below=1) → 0.174(below=2)  离场确认
resolver=diarization-async segments=2 decision=ambiguous reason=diarization-speaker-count:1
decision=fail-open reason=diarization-speaker-count:1
```

声纹证据无歧义（左 0.70 / 右 0.17），但 pyannote 聚类把两个人的两段**并成了同一个标签**，
`resolveDiarized` 要求恰好 2 个说话人于是放弃。该离场正好发生在音频末尾、走 finish 路径，而
Runtime 里 `if (finishTriggered) return undefined` 刻意跳过声学回退（注释：finish 只接受高置信度
结果），保守包含又只对 `sequential-boundary-ambiguous:` 开放——两道闸门同时关着，于是 fail-open。
整轮日志里 `resolver=acoustic` 出现 **0 次**。

**修法**（提交 `c2a97bb5`）：

1. finish 路径也走声学解析器。它对候选点做左右各一个窗长的独立声纹复核（左 ≥ 阈值、
   右 < 阈值−0.05、分差 ≥ 0.15），不依赖 diarization 的聚类。
2. 流式分数已确认离场时，任一解析器定不出边界就退到保守包含前缀，而不是发布已知混合。
   重叠（`unsupported-overlap`）与缓冲越界仍不可包含。

修后 turn-04 的链条变为 `diarization 歧义 → 声学回退歧义 → containment 切分`，
final 变成 `搜狐娱乐讯据港媒。`——非机主没了，代价是机主尾部"报道"被保守切点截掉。
该 cycle 的收尾时延同时从 1256 ms 降到 782 ms。

## 分支 B：短句只有句级分可依，而阈值压在噪声里

会话 6 的声纹分一路 0.648 → 0.537 从未跌破阈值，没有任何 `SPEAKER_TURN` 决策。换人处有自然
停顿，普通 VAD 先把两人切成两句，非机主那 1.6 s 独立成句。Speaker VAD 的流式判定需要
winSec + hopSec（默认 2 s）才能出结论，这句太短，只剩句级分可依。

主机按 SDK 同样方式复算该段：**0.362**，而默认阈值 0.35 —— 高出 0.012 被放行。
（同时排除了"缓冲串音"：机主段 0.673、非机主段 0.362，分得很开。）

短段分布实测（`asr/tools/speaker/18_eval_short_segment_threshold.py`，aishell3 三段注册，ERes2Net）：

| 段长 | 机主自己最低 | 非机主最高 | 非机主≥0.35 | 非机主≥0.45 |
|---|---|---|---|---|
| 1.0 s | 0.525 | 0.400 | 2.5% | 0% |
| 1.5 s | 0.600 | 0.377 | 2.5% | 0% |
| 2.0 s | 0.603 | 0.432 | 5.0% | 0% |
| 3.0 s | 0.636 | 0.459 | 7.2% | 1.0% |

0.35 落在非机主分布尾部，而 0.35~0.52 之间是一条空带。

**修法**（提交 `fab43be7`）：流式机器从未确认过的句子，句级分需同时过配置阈值和实测空带下沿
**0.45**（`UNCONFIRMED_SPEAKER_FINAL_MIN_SCORE`）；已确认的句子保持配置阈值；调用方把阈值设得
更严时以调用方为准。

## 修复后：6 例全部拦住

| 用例 | 修复前 | 修 A 后 | 修 A+B 后 |
|---|---|---|---|
| turn-00~03 | 拦住 | 拦住 | 拦住 |
| turn-04 | 泄露 | 拦住 | 拦住 |
| turn-05 | 泄露 | 泄露 | **拦住** |

`target_speaker_content` 判定 PASS，鸿蒙全量 459 个 Python 测试通过。

## 仍未解决

- **收尾补救时延**：4 个走收尾补救的 cycle 里 3 个超过载体自设的 1200 ms 预算
  （1563~1761 ms），`speaker-vad-turn` 整体仍判 FAIL。构成（cycle 0）：分割推理 159 ms +
  机主前缀重解码 792 ms + 前缀 final 补尾刷新 404 ms + 打分派发约 300 ms。该时延在修复前后
  基本不变（1637/1621/1813 → 1693/1563/1761），不是本次修复引入；1.7 s 也在随包文档声明的
  "结束到最终角色结果 1.1~2.4 s"之内，且说话过程中 partial 持续刷新。处置待定：按实测放宽
  预算，或把前缀投机预解码提前到分数开始下滑时以藏掉那 792 ms。
- **0.45 下沿的注册同源偏乐观**：注册音与测试音同一会话，机主一侧偏高（与
  `AIDATATANG_SPEAKER_VAD_EVAL.md` 同一限制）。跨会话注册下机主短句是否会被误拒，必须用
  客户真实声纹 + 一段机主短句复测后才能认为该下沿在生产上成立。
- **安卓同类缺口**：安卓的句级门用同一个 score-only 阈值，短句盲区相同；其换人切分与收尾
  短窗补判在 `fix/android-speaker-turn-split` 分支，等安卓真机验证。

## 产物

- 夹具生成器 `asr/tools/speaker/17_build_speaker_turn_device_fixture.py`
- 阈值测量 `asr/tools/speaker/18_eval_short_segment_threshold.py`
- 设备产物 `~/.cache/amphion-runtime/delivery-staging/asr/harmony/0.3.26/2d49bec5/scratch/`
  下的 `speaker-turn-device2`（修复前）、`speaker-turn-fixA`、`speaker-turn-fixB`（修复后）
