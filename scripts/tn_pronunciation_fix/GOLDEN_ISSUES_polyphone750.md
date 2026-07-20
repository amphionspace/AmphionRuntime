# 多音字语料 750 条 — golden 标注疑误清单（A 类）

> 说明：以下 42 句中，端侧 G2P（前端分词 + 多音字词典）在上下文中输出的读音是正确的，而语料 `golden_pinyin` 标注疑似有误。
> 仅列“忽略声调仍不一致”（即声母/韵母选择不同）的真读错，不含变调/轻声约定差异。建议 golden 作者复核。

| 字 | 疑误 token 数 | 规律 |
|---|---|---|
| 地 | 17 | 结构助词/状语“地”应读轻声 de5，golden 标注为实词 di4 |
| 长 | 9 | 时长/长度义应读 cháng，golden 标注为 zhǎng（生长/首长义） |
| 行 | 3 | 银行/跨行/首行/下一行/行号（行当/行列义）应读 háng，golden 标注为 xíng |
| 藏 | 3 | 专名 西藏/藏文/藏族/藏毯 应读 Zàng，golden 标注为 cáng（收藏义） |
| 还 | 2 | 归还/偿还/还款义应读 huán，golden 标注为 hái（副词义） |
| 乐 | 2 | 乐曲/音乐义应读 yuè，golden 标注为 lè（欢乐义） |
| 调 | 2 | 调节/调整/调高义应读 tiáo，golden 标注为 diào |
| 重 | 1 | 重整/重新（再次义）应读 chóng、重视/重点（程度义）应读 zhòng，golden 标反 |
| 弹 | 1 | 弹奏义应读 tán，golden 标注为 dàn（子弹义） |
| 解 | 1 | 理解义应读 jiě，golden 标注为 xiè（姓氏/解送义） |
| 差 | 1 | 钦差/官差应读 chāi、差异应读 chā，golden 标反 |
| 朝 | 1 | 朝向/朝南义应读 cháo，golden 标注为 zhāo（早晨义） |
| 得 | 2 | 得到/得奖（获得义）应读 dé，golden 标注为 děi（必须义） |

## 地（结构助词/状语“地”应读轻声 de5，golden 标注为实词 di4）

- `polyphone-manual-04-07` 音乐会结束后，乐迷们快乐地交流各自喜欢的乐曲。
  - 第12个“地” 设备=de / golden=di
- `polyphone-manual-04-22` 观众在乐曲结束后热烈鼓掌，乐手们也快乐地向大家致意。
  - 第19个“地” 设备=de / golden=di
- `polyphone-manual-04-28` 乐器修复师播放音乐测试音色，听到准确旋律便乐呵呵地笑了。
  - 第24个“地” 设备=de / golden=di
- `polyphone-manual-04-29` 学校把音乐教室改造成艺术乐园，让学生快乐地尝试各种乐器。
  - 第20个“地” 设备=de / golden=di
- `polyphone-manual-11-09` 老人悠闲地坐在空地上，看孩子们快乐地踢球。
  - 第5个“地” 设备=de / golden=di
- `polyphone-manual-11-10` 工人小心地清理地面，避免地下电缆再次受损。
  - 第12个“地” 设备=de / golden=di
- `polyphone-manual-11-12` 雨后的空气清新，游客自在地躺在草地上休息。
  - 第12个“地” 设备=di / golden=de
- `polyphone-manual-11-20` 河水不断地冲刷湿地，使当地地貌发生缓慢变化。
  - 第5个“地” 设备=de / golden=di
- `polyphone-manual-11-21` 老师耐心地展开地图，让学生轮流地寻找自己的家乡。
  - 第8个“地” 设备=de / golden=di；第15个“地” 设备=de / golden=di
- `polyphone-manual-11-26` 摄影师静静地伏在草地上，专注地拍摄地平线的日出。
  - 第17个“地” 设备=de / golden=di
- `polyphone-manual-11-27` 工人有序地撤离工地，安全员认真地检查场地。
  - 第5个“地” 设备=di / golden=de
- `polyphone-manual-11-30` 调查人员仔细地测量地面裂缝，并如实地记录地点。
  - 第17个“地” 设备=di / golden=de
- `polyphone-manual-17-08` 医生根据检查调整药量，以便更好地调节患者血压。
  - 第15个“地” 设备=de / golden=di
- `polyphone-manual-20-11` 他强词夺理地辩解，只会让大家更强烈地怀疑事实。
  - 第17个“地” 设备=de / golden=di
- `polyphone-manual-23-05` 他说话结结巴巴，手里却熟练地打好了一个结实绳结。
  - 第13个“地” 设备=de / golden=di
- `polyphone-manual-23-12` 比赛结束后队员团结地围成一圈，共同总结结果。
  - 第10个“地” 设备=de / golden=di

## 长（时长/长度义应读 cháng，golden 标注为 zhǎng（生长/首长义））

- `polyphone-manual-05-11` 班长擅长长跑，每天训练都比其他队员坚持更长时间。
  - 第20个“长” 设备=chang / golden=zhang
- `polyphone-manual-05-17` 这段长城修复工程历时很长，附近村庄也在逐步发展壮大。
  - 第3个“长” 设备=chang / golden=zhang；第12个“长” 设备=chang / golden=zhang
- `polyphone-manual-05-18` 董事长作了长时间说明，希望公司获得长期发展的机会。
  - 第6个“长” 设备=chang / golden=zhang
- `polyphone-manual-05-25` 这条长裙随着女孩长高变得不再合身，母亲决定加长裙摆。
  - 第3个“长” 设备=chang / golden=zhang；第22个“长” 设备=chang / golden=zhang
- `polyphone-manual-05-26` 长时间伏案影响身体健康，医生建议长期伏案者经常伸展颈部。
  - 第1个“长” 设备=chang / golden=zhang
- `polyphone-manual-05-29` 园长把长椅移到树荫下，让等待家长的孩子有地方休息。
  - 第4个“长” 设备=chang / golden=zhang
- `polyphone-manual-23-18` 研究结论得到验证后，长达两年的实验正式结束。
  - 第10个“长” 设备=chang / golden=zhang

## 行（银行/跨行/首行/下一行/行号（行当/行列义）应读 háng，golden 标注为 xíng）

- `polyphone-manual-01-04` 柜员发现客户填错银行行号，便请他在下一行重新填写。
  - 第19个“行” 设备=hang / golden=xing
- `polyphone-manual-01-11` 银行工作人员核验行号后，确认这笔跨行汇款可以正常执行。
  - 第17个“行” 设备=hang / golden=xing
- `polyphone-manual-01-26` 他把申请表的开户行名称写在首行，却把银行行号漏在下一页。
  - 第15个“行” 设备=hang / golden=xing

## 藏（专名 西藏/藏文/藏族/藏毯 应读 Zàng，golden 标注为 cáng（收藏义））

- `polyphone-manual-14-15` 档案馆收藏了大量藏文资料，其中隐藏着西藏旧城地图。
  - 第9个“藏” 设备=zang / golden=cang
- `polyphone-manual-14-22` 学者从藏文古籍中发现隐藏注释，重新解释了藏族传说。
  - 第4个“藏” 设备=zang / golden=cang
- `polyphone-manual-14-30` 游客在西藏购买藏毯，并把它作为珍贵收藏带回家。
  - 第8个“藏” 设备=zang / golden=cang

## 还（归还/偿还/还款义应读 huán，golden 标注为 hái（副词义））

- `polyphone-manual-02-15` 银行同意延长还款期限，但企业还是决定提前偿还贷款。
  - 第7个“还” 设备=huan / golden=hai
- `polyphone-manual-02-22` 他还没来得及还书，图书馆就发来了催还通知。
  - 第17个“还” 设备=huan / golden=hai

## 乐（乐曲/音乐义应读 yuè，golden 标注为 lè（欢乐义））

- `polyphone-manual-04-01` 音乐老师用轻快乐曲带动课堂气氛，孩子们听得十分欢乐。
  - 第8个“乐” 设备=yue / golden=le
- `polyphone-manual-04-15` 乐队把悲伤旋律改成轻快乐曲，希望给灾区孩子带去欢乐。
  - 第12个“乐” 设备=yue / golden=le

## 调（调节/调整/调高义应读 tiáo，golden 标注为 diào）

- `polyphone-manual-17-12` 她把空调温度调高，又调节出风口避免直吹。
  - 第7个“调” 设备=tiao / golden=diao
- `polyphone-manual-17-20` 母亲调好闹钟，又把空调调到适合睡眠的温度。
  - 第3个“调” 设备=tiao / golden=diao

## 重（重整/重新（再次义）应读 chóng、重视/重点（程度义）应读 zhòng，golden 标反）

- `polyphone-manual-03-26` 球队重整阵容后更加重视防守，并重新安排重点训练内容。
  - 第3个“重” 设备=chong / golden=zhong

## 弹（弹奏义应读 tán，golden 标注为 dàn（子弹义））

- `polyphone-manual-04-10` 作曲家修改乐谱后亲自弹奏乐曲，满意地露出快乐笑容。
  - 第11个“弹” 设备=tan / golden=dan

## 解（理解义应读 jiě，golden 标注为 xiè（姓氏/解送义））

- `polyphone-manual-07-04` 她从负数开始逐个往后数，以便理解数学中的数轴。
  - 第15个“解” 设备=jie / golden=xie

## 差（钦差/官差应读 chāi、差异应读 chā，golden 标反）

- `polyphone-manual-16-08` 钦差奉命调查粮价差异，并处理地方官差造成的问题。
  - 第17个“差” 设备=chai / golden=cha

## 朝（朝向/朝南义应读 cháo，golden 标注为 zhāo（早晨义））

- `polyphone-manual-25-22` 会议室朝南，座位统一朝向投影屏幕。
  - 第10个“朝” 设备=chao / golden=zhao

## 得（得到/得奖（获得义）应读 dé，golden 标注为 děi（必须义））

- `polyphone-manual-10-07` 运动员第一次参赛就得奖，教练激动得连声祝贺。
  - 第10个“得” 设备=de / golden=dei
- `polyphone-manual-10-16` 他讲得很清楚，听众很快就得到了解决问题的方法。
  - 第12个“得” 设备=de / golden=dei
