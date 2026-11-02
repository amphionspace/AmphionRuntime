# coding: utf-8
from pathlib import Path
import csv, gzip, json, math, statistics, hashlib
from collections import defaultdict
p=Path(__file__).resolve().parent
rows=[json.loads(x) for x in (p/'rows.jsonl').read_text().splitlines()]
cold=next(x for x in rows if x['index']==-1)
warm=[x for x in rows if x['index']>=0]
phases=json.loads((p/'phases.json').read_text()); summary=json.loads((p/'summary.json').read_text()); inputs=json.loads((p/'inputs.json').read_text())
mem=[]
with ((p/'memory.csv').open() if (p/'memory.csv').exists() else gzip.open(p/'memory.csv.gz','rt')) as f:
 for x in csv.DictReader(f):mem.append((float(x['elapsed_ms']),int(x['request_index']),int(x['rss_kib'])))
peak_by_request=defaultdict(int)
for _,i,rss in mem:peak_by_request[i]=max(peak_by_request[i],rss)
for row in rows:row['sampledPeakRssKiB']=max(peak_by_request[row['index']],row['beforeRssKiB'],row['afterRssKiB'])
def stats(vals):
 v=sorted(vals);n=len(v)
 return dict(n=n,min=v[0],p50=v[math.ceil(.5*n)-1],p95=v[math.ceil(.95*n)-1],p99=v[math.ceil(.99*n)-1],max=v[-1],mean=sum(v)/n)
metrics=['firstPacketMs','lastPacketMs','completionMs','completionAfterLastPacketMs','maxInterPacketGapMs','audioDurationMs','rtf']
def group(rr):
 return {'count':len(rr),'errors':sum(x['error'] is not None or not x['finished'] or x['pcmBytes']<=0 for x in rr),
  'over500ms':sum(x['firstPacketMs']>500 for x in rr),
  'metrics':{k:stats([x[k] for x in rr]) for k in metrics},
  'afterRssKiB':stats([x['afterRssKiB'] for x in rr]),'sampledPeakRssKiB':max(x['sampledPeakRssKiB'] for x in rr)}
report={'count':len(warm),'cold':cold,'summary':summary,'phases':phases,'aggregate':group(warm),
 'perInput':{str(i):dict(text=text,**group([x for x in warm if x['inputId']==i])) for i,text in enumerate(inputs)},
 'blocks':{f'{lo+1}-{min(lo+100,len(warm))}':group(warm[lo:lo+100]) for lo in range(0,len(warm),100)},
 'allPhasesPeakRssKiB':max(x[2] for x in mem),'memorySamples':len(mem),'percentile':'nearest rank',
 'apkSha256':((p/'installed-apk-sha256.txt').read_text().split()[0] if (p/'installed-apk-sha256.txt').exists() else json.loads((p/'identity.json').read_text())['apkSha256'])}
assert len(warm)==1000 and [x['index'] for x in warm]==list(range(1000))
assert report['aggregate']['errors']==0
assert all(x['firstPacketMs']<=x['lastPacketMs']<=x['completionMs'] for x in warm)
assert all(x['chunks']>0 and x['audioDurationMs']>0 for x in rows)
(p/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
repo=next((q for q in [p,*p.parents] if (q/'tts/android/docs').is_dir()), p.parents[1]/'AmphionRuntime')
docdir=repo/'tts/android/docs'
data=docdir/'benchmarks/imf-1000-20261102';data.mkdir(parents=True,exist_ok=True)
for name in ['rows.jsonl','inputs.json','phases.json','summary.json','report.json','instrumentation.log','target.init.gradle']:
 (data/name).write_bytes((p/name).read_bytes())
if (p/'memory.csv').exists():
 with gzip.open(data/'memory.csv.gz','wb') as f:f.write((p/'memory.csv').read_bytes())
(data/'analyze.py').write_bytes(Path(__file__).read_bytes())
# Retain the run identity without device SN, private filesystem paths or license material.
(data/'identity.json').write_text(json.dumps({'device':'TECNO KI8','android':13,'apkSha256':report['apkSha256'],'model':'IMF 170000','modelCheckpointSha256':'fbaf5c4f7f96cf5864164c66b371f68994da54472b3e67fa1005df7a61c50c8a','chunkFrames':50,'sampleRateHz':24000,'temperature':0,'voiceId':'lits-female-02','language':'zh-en','speed':1.0,'sampleBit':16,'channels':1,'playType':'SYNTHESIZE_ONLY'},indent=2)+'\n')
S=report['aggregate']; M=S['metrics']; mb=lambda kib:kib*1024/1e6
phase_names={'before_sdk_init':'SDK 初始化前（App 基线）','after_sdk_init':'SDK init 后','after_model_load':'模型加载后','after_cold_synthesis':'首次合成后','after_1000_synthesis':'第 1,000 次合成后','before_engine_shutdown':'关闭引擎前','after_engine_shutdown':'shutdown 返回后','two_seconds_after_shutdown':'shutdown 后再等 2 秒'}
baseline=phases[0]['rssKiB']; init=next(x['rssKiB'] for x in phases if x['phase']=='after_sdk_init')
lines=['# IMF Android：1,000 次首包、尾包及内存测试','', '测试日期：2026-11-02（Asia/Shanghai）。这是当前已安装 IMF App 的性能实测，不是全语料音质验收。','',
 '## 1. 结论','',f"- 热态请求 **{len(warm):,} 次，失败 {S['errors']} 次**；10 条固定语料各 100 次，循环交替。",
 f"- 首包 P95 **{M['firstPacketMs']['p95']:.2f} ms**，{'满足' if M['firstPacketMs']['p95']<=500 else '未达到'} ≤500 ms；超过 500 ms 的请求 **{S['over500ms']}/1000**。",
 f"- 按输入单独统计：经纬度语句（ID 2）的首包 P95 **{report['perInput']['2']['metrics']['firstPacketMs']['p95']:.2f} ms**，未达到500ms；其余9条输入的P95均低于500ms。不能声称所有语料均达标。",
 f"- SDK init 阶段 RSS 增量 **{mb(init-baseline):.2f} MB**。这不包含之后的模型加载，不能代表整个 SDK 可用状态的内存。",
 f"- 合成期间进程峰值 RSS **{mb(S['sampledPeakRssKiB']):.2f} MB**，{'满足' if mb(S['sampledPeakRssKiB'])<=200 else '未达到'} ≤200 MB。",
 f"- 冷进程从 SDK init 开始到首次 PCM **{summary['coldInitToFirstPacketMs']:.2f} ms**；单独一轮，不计入热态分位数。",'',
 '## 2. 被测对象与条件','',
 '- 真机：TECNO KI8，Android 13；USB 连接。运行中不重新安装 App、不更换模型，不读取大文件或持续调用 dumpsys。',
 '- 目标 App：`com.lits.tts.demo31`；测试代码加载到目标进程，通过公共 SDK API 调用。未启动可见 Activity，因此基线不代表正在显示完整界面的内存。',
 '- IMF 170000、FP32、24 kHz，speaker 1（`lits-female-02`），zh-en，语速 1.0，温度 0、50 帧分块，其余保持现有默认值。',
 '- 同一引擎串行合成，`SYNTHESIZE_ONLY`；每条完整结束才提交下一条。没有首包后取消、并发压测或扬声器播放。',
 '- 资源已安装，重启 App 进程测一次冷态；没有清除操作系统文件缓存，不能称为存储冷缓存或首次安装性能。',
 '- 冷请求之后直接运行 1,000 次热态请求；每次不强制 GC，不人工加入降温间隔。',
 f"- 被测 APK SHA-256：`{report['apkSha256']}`。测试源码所在 Git HEAD 不等同于此 APK 的编译版本，结果绑定实际 APK。",
 f"- 总耗时（含初始化、关闭和关闭后观察）：{summary['totalElapsedMs']/60000:.2f} 分钟。",'',
 '## 3. 指标定义','',
 '| 指标 | 计时/计算方法 | 用来判断什么 |','|---|---|---|',
 '| 首包延迟 | 调用 speak 前 → 第一次收到非空 onData。单调时钟，包含排队、前端及首块模型计算。 | 多久能拿到可播放音频；不等于用户实际听到声音的时间。 |',
 '| 尾包延迟 | 调用 speak 前 → 最后一次非空 onData；合成完成后确认哪个包是最后一包。 | 全部音频多久交付；随文本和音频长度变化，不能沿用首包的500ms目标。 |',
 '| 合成完成耗时 | 调用 speak 前 → SYNTHESIS_COMPLETE 回调入口。 | SDK 何时通知本次合成完成；不是等待线程醒来的时间。 |',
 '| 完成回调与尾包间隔 | 合成完成回调时间减去最后一个非空音频包时间。 | 区分音频已交付与结束通知的额外开销。 |',
 '| 最大块间隔 | 同一请求相邻两个非空 onData 到达时间差的最大值，不包含首包等待。 | 是否存在突出的输出间歇；缓冲大小和每块音频时长不同，不能据此直接断言播放卡顿。 |',
 '| 音频时长 | PCM字节数 ÷（采样率 × 声道数 × 每采样字节数）。 | 实际生成多少秒音频，不是执行耗时。 |',
 '| RTF（实时率） | 合成完成耗时 ÷ PCM音频时长，分子分母使用相同单位。 | 小于1说明总合成速度快于播放速度；0.2表示生成10秒音频约需2秒。不保证每个块都及时到达。 |',
 '| P50 / P95 / P99 | 排序后第 ceil(p×N) 个值（nearest-rank）。 | 典型延迟及慢请求；P95不是最大值，也不表示每次都达标。 |',
 '| RSS | /proc/self/status 的 VmRSS，即目标 App 进程驻留物理内存。 | 包括模型、前端、native/Java堆、代码及测试框架；不是整台手机内存，不是PSS，也不是模型文件大小。 |',
 '| 相对基线增量 | 某阶段RSS − init之前RSS。 | 该阶段比测试启动基线多占多少内存；不能精确归因到某个库。 |',
 '| 合成峰值RSS | 合成请求期间每20ms采样，结合请求开始/结束快照取最大值。 | 本轮可观察的内存高水位；更短暂尖峰可能被漏采。 |',
 '| 每100次内存中位数 | 每个100次窗口里，请求合成结束时RSS的中位数。 | 观察持续运行后的趋势；增长也可能来自缓存/分配器，单轮不能证明泄漏。 |',
 '| 错误/超时 | SDK onError、非完整结束、无PCM、序号异常或90秒超时均判失败并停止。 | 失败不静默剔除，也不补跑成功请求来替代。 |','',
 '## 4. 热态总体结果','',
 '下表混合不同长度语料，首包可作总体参考；尾包、完成耗时和RTF应结合下一节按输入汇总。','',
 '| 指标 | 平均 | P50 | P95 | P99 | 最大 |','|---|---:|---:|---:|---:|---:|']
names={'firstPacketMs':'首包（ms）','lastPacketMs':'尾包（ms）','completionMs':'完成（ms）','completionAfterLastPacketMs':'完成减尾包（ms）','maxInterPacketGapMs':'最大块间隔（ms）','audioDurationMs':'音频时长（ms）','rtf':'RTF'}
for k in metrics:
 st=M[k];lines.append('| '+names[k]+' | '+' | '.join(f'{st[x]:.3f}' for x in ['mean','p50','p95','p99','max'])+' |')
lines+=['','## 5. 按语料结果','', '| ID | 次数 | 首包P50 / P95（ms） | 尾包P95（ms） | 完成P95（ms） | 音频中位时长（秒） | RTF P95 | 超500ms次数 |', '|---|---:|---:|---:|---:|---:|---:|---:|']
for i,g in report['perInput'].items():
 m=g['metrics'];lines.append(f"| {i} | {g['count']} | {m['firstPacketMs']['p50']:.2f} / {m['firstPacketMs']['p95']:.2f} | {m['lastPacketMs']['p95']:.2f} | {m['completionMs']['p95']:.2f} | {m['audioDurationMs']['p50']/1000:.3f} | {m['rtf']['p95']:.3f} | {g['over500ms']} |")
lines+=['','### 输入原文','']
for i,t in enumerate(inputs):lines.append(f'- **{i}**：{t}')
lines+=['','## 6. 冷启动与内存分阶段','',f"SDK init **{summary['initMs']:.2f} ms**；createEngine **{summary['createEngineMs']:.2f} ms**；随后首条 speak 首包 **{cold['firstPacketMs']:.2f} ms**、尾包 **{cold['lastPacketMs']:.2f} ms**。init开始至首包 **{summary['coldInitToFirstPacketMs']:.2f} ms**。",'',
 '| 阶段 | App总RSS（MB） | 相对初始化前增量（MB） |','|---|---:|---:|']
for x in phases:lines.append(f"| {phase_names[x['phase']]} | {mb(x['rssKiB']):.2f} | {mb(x['rssKiB']-baseline):+.2f} |")
lines+=[f"| 合成期间采样峰值 | {mb(S['sampledPeakRssKiB']):.2f} | {mb(S['sampledPeakRssKiB']-baseline):+.2f} |",'',
 '这里 **1 MB = 1,000,000 字节**；原始数据KiB为1024字节。初始化前已经有App进程、Android运行时及测试框架；1.x或2.x MB的init增量不是“整个App只占这些内存”。阶段差值包含少量授权文件读取、采样和测试记录开销，不能视为SDK内部精确分配量。模型加载增量还包括运行库与前端资源。shutdown后保留的RSS也不能直接当作泄漏，可能包含共享环境、缓存、Java对象和内存分配器保留页。','',
 '## 7. 连续运行趋势','', '| 请求范围 | 首包P95（ms） | 尾包P95（ms） | RTF P95 | 请求结束RSS中位数（MB） | 合成峰值RSS（MB） |', '|---|---:|---:|---:|---:|---:|']
for key,g in report['blocks'].items():
 m=g['metrics'];lines.append(f"| {key} | {m['firstPacketMs']['p95']:.2f} | {m['lastPacketMs']['p95']:.2f} | {m['rtf']['p95']:.3f} | {mb(g['afterRssKiB']['p50']):.2f} | {mb(g['sampledPeakRssKiB']):.2f} |")
lines += ['', f"前100次到最后100次，请求结束RSS的P50由 **{mb(report['blocks']['1-100']['afterRssKiB']['p50']):.2f} MB** 变为 **{mb(report['blocks']['901-1000']['afterRssKiB']['p50']):.2f} MB**；本轮没有观察到持续内存上涨。这个结论仅覆盖本轮约29分钟测试，不能据此证明不存在任何内存泄漏。"]
lines+=['','温度和系统热状态只在冷态及每100次结束时记录，用于解释运行环境，不是TTS验收指标。电池温度不是CPU温度；系统热状态无告警也不代表绝对没有降频。','',
 '| 请求完成数 | 电池温度（°C） | Android thermalStatus |', '|---|---:|---:|']
for row in rows:
 if 'conditions' in row:lines.append(f"| {row['index']+1} | {row['conditions']['batteryTemperatureC']:.1f} | {row['conditions']['thermalStatus']} |")
lines+=['','## 8. 证据、限制和复现','',
 '- 不进行主观听感、发音正确性或扬声器端的延迟/卡顿验收。未保存1000份PCM，避免无意义I/O和大文件；保留字节数和音频时长。',
 '- 这是一台真机、一次进程运行、10条固定输入重复测试；不是1000条独立文本，也不是所有机型/输入的保证。',
 '- 20ms RSS采样及测试框架有自身开销。基线和增量是观察值，没有通过估算“扣掉测试框架”来美化结果。',
 '- 所有计时均使用Android单调时钟；设备墙上时间与测试日期可能不同，不影响耗时。',
 '- 首包≤500ms、合成峰值≤200MB沿用用户目标；尾包没有套用500ms门槛。init≤10MB仅对应轻量授权/配置阶段。',
 '- 原始证据位于 [benchmarks/imf-1000-20261102](benchmarks/imf-1000-20261102/)：`rows.jsonl`逐次请求，`inputs.json`语料，`memory.csv.gz`内存采样，`phases.json`阶段快照，`summary.json`冷态与运行参数，`report.json`分组统计，`identity.json`构建身份。',
 '- 测试源码归档在证据目录 `Imf1000BenchmarkTest.kt`；不加入默认设备测试集合，避免日常测试无意触发30分钟长跑。测试必须针对相同APK、模型、配置并提供设备有效授权；本报告不携带私钥、授权文件或设备SN。',
 '- `target.init.gradle`把测试目标设为已安装demo31，并让测试依赖与App匹配；只安装测试APK，不安装aarHost宿主或重建SDK。每次运行需使用新的输出目录，测试拒绝覆盖旧结果。',
 '- 本地完整运行日志保存在工作区 `outputs/imf-benchmark-1000-20261102/`。','']
lines += ['### 复现步骤', '', '1. 保持上述APK、模型和有效设备授权一致。将归档的 `Imf1000BenchmarkTest.kt` 临时复制到 `tts/android/aarHost/src/androidTest/java/com/lits/tts/aarhost/`；为新运行修改源码中的输出目录名称，不能覆盖此次证据。', '2. 在 `tts/android` 使用提供的 `target.init.gradle`，构建 `:aarHost:assembleDebugAndroidTest -x :sdk:assembleRelease -x :stageBundledTtsResources`。这里跳过SDK和模型组装，只编译测试APK；编译依赖需使用与目标App公共API相符的AAR。', '3. 只安装 `aarHost/build/outputs/apk/androidTest/debug/aarHost-debug-androidTest.apk`，force-stop目标App，然后运行 `adb shell am instrument -w -e class com.lits.tts.aarhost.Imf1000BenchmarkTest com.lits.tts.demo31.test/androidx.test.runner.AndroidJUnitRunner`。', '4. 通过 `adb exec-out run-as com.lits.tts.demo31 cat files/<新输出目录>/<文件>` 获取原始数据，归档到新目录。结束后移除临时测试源码。', '5. 本次证据可在证据目录执行 `python3 analyze.py` 重算；报告使用 nearest-rank 分位数。`SHA256SUMS`用于验证归档文件完整性。', '']
(docdir/'IMF_1000_REQUEST_BENCHMARK_20261102.md').write_text('\n'.join(lines))
print(json.dumps({'count':len(warm),'first':M['firstPacketMs'],'tail':M['lastPacketMs'],'rtf':M['rtf'],'peakMB':mb(S['sampledPeakRssKiB'])},indent=2))
