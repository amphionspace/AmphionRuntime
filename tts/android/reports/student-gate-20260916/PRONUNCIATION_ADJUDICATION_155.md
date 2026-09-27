# 155 条发音差异逐条核对

范围：原真机 reviewed-675 结果中的 155 条差异。按原文语义、归一化文本、完整拼音串和代码核对；不是 155 段音频的听感测评，也未重新逐条审查其余 520 条。

## 结论

| 主分类 | 条数 |
| --- | ---: |
| 标注错误 | 34 |
| 语料内容无效或自相矛盾 | 18 |
| 读法／标注口径差异 | 86 |
| 前处理缺陷 | 17 |

主分类互斥，但一条可能兼有多个问题，见各条“附加问题”。保留原始标注，未把实际输出整批回填为正确答案；“可接受读法”尚未用于放宽自动验收。

## 已修复与验证

17 条涉及序数“一”的上下文：空格拆块使“第 100 轮”与“第一百轮”的处理不同；同一个序数内部的“一”也要保留上下文。修复前对照单测失败，修复后通过。155 条使用真机已记录的 TN 文本重新运行 JVM G2P：16 条与原标注一致，剩下那条同时存在旧标注漏字（116 → 一百十六）。这不等于 JNI/TN 真机重跑或主观音质通过。

## 判定依据

- 语料原文决定数值、序数、日期与标识符的语义；旧标注不能把十三秒改成一三秒，或漏掉一百一十三中的一。无效日期要标为输入问题。
- [普通话语音教学：一的数量结构与序数结构](https://wenxueyuan.ruc.edu.cn/UploadFile/20140703/20140703092245142.pdf)区分了一与位数词结合的变调、序数用法。这里以序数上下文不因格式空格丢失作为代码不变量。
- [晋中学院：音变教学](https://wxy.jzxy.edu.cn/uploads/zwx/file/20180409/1rnlf6h7km.pdf)说明三声连读受语义分组影响；多音节不能只按相邻字符机械判断唯一调串。
- [山西财贸职业技术学院：上声变调](https://www.sxftc.edu.cn/cjc/info/1228/2998.htm)区分书面本调标注与实际语流变调。旧数据混用两种口径，所以声调不同不能一律视作读错。

## 逐条结果

### 001. v3-parity-zh-core-015

**原文：** 会议安排在 2026 年 7 月 16 日星期四。

**TN：** 会议安排在 二零二六年 七 月 十六 日星期四。

**判断：标注错误。** 日期中的 16 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 002. v3-parity-zh-core-025

**原文：** 会议安排在 2026 年 7 月 26 日星期四。

**TN：** 会议安排在 二零二六年 七 月 二十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 26 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 2026-07-26 是星期日，原文写星期四；同时存在日期数字拼音标注错误。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 003. v3-parity-zh-core-035

**原文：** 会议安排在 2026 年 7 月 36 日星期四。

**TN：** 会议安排在 二零二六年 七 月 三十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 36 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 36 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 004. v3-parity-zh-core-045

**原文：** 会议安排在 2026 年 7 月 46 日星期四。

**TN：** 会议安排在 二零二六年 七 月 四十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 46 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 46 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 si4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 si4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 005. v3-parity-zh-core-055

**原文：** 会议安排在 2026 年 7 月 56 日星期四。

**TN：** 会议安排在 二零二六年 七 月 五十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 56 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 56 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 006. v3-parity-zh-core-065

**原文：** 会议安排在 2026 年 7 月 66 日星期四。

**TN：** 会议安排在 二零二六年 七 月 六十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 66 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 66 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 007. v3-parity-zh-core-075

**原文：** 会议安排在 2026 年 7 月 76 日星期四。

**TN：** 会议安排在 二零二六年 七 月 七十六 日星期四。

**判断：语料内容无效或自相矛盾。** 日期中的 76 应按数值读；旧拼音把日期数字逐位拼读，缺少十位单位。

**附加问题：** 7 月没有 76 日。原文无效，同时存在上述拼音标注错误；TTS 不负责擅自改写用户日期。

**标注：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 liu4 ri4 xing1 qi1 si4`

**修复前实际：** `hui4 yi4 an1 pai2 zai4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 liu4 ri4 xing1 qi1 si4`

**处理：** 修订日期读法标注；无效日期改为有效日期另建样例，保留旧样例作容错输入。

### 008. v3-parity-zh-core-016

**原文：** 本次订单金额为 17234.56 元，优惠 8.8 折。

**TN：** 本次订单金额为 一万七千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ben3 ci4 ding4 dan1 jin1 e2 wei2 yi1 wan4 qi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ben3 ci4 ding4 dan1 jin1 e2 wei2 yi2 wan4 qi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 009. v3-parity-zh-core-058

**原文：** 验证码是 A9B8C7-59，请不要告诉别人。

**TN：** 验证码是 A九,B八,C七,杠五九,请不要告诉别人。

**判断：标注错误。** 59 后有逗号。旧标注把逗号后的请(qing3)与前面的九(jiu3)连做三声变调，标成 jiu2；当前在标点处断开，jiu3 正确。五九内部 wu2 jiu3 合理。

**标注：** `yan4 zheng4 ma3 shi4 EY1 jiu3 B IY1 ba1 S IY1 qi1 gang4 wu2 jiu2 qing3 bu2 yao4 gao4 su4 bie2 ren2`

**修复前实际：** `yan4 zheng4 ma3 shi4 EY1 jiu3 B IY1 ba1 S IY1 qi1 gang4 wu2 jiu3 qing3 bu2 yao4 gao4 su4 bie2 ren2`

**处理：** 修订跨标点变调标注；保留前处理的标点边界。

### 010. v3-parity-mixed-zh-en-012

**原文：** Go go go，13 秒后开始录音。

**TN：** Go go go,十三 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 yi1 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 shi2 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 011. v3-parity-mixed-zh-en-020

**原文：** Go go go，21 秒后开始录音。

**TN：** Go go go,二十一 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 er4 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 er4 shi2 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 012. v3-parity-mixed-zh-en-028

**原文：** Go go go，29 秒后开始录音。

**TN：** Go go go,二十九 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 er4 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 er4 shi2 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 013. v3-parity-mixed-zh-en-036

**原文：** Go go go，37 秒后开始录音。

**TN：** Go go go,三十七 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 san1 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 san1 shi2 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 014. v3-parity-mixed-zh-en-044

**原文：** Go go go，45 秒后开始录音。

**TN：** Go go go,四十五 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 si4 wu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 si4 shi2 wu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 015. v3-parity-mixed-zh-en-052

**原文：** Go go go，53 秒后开始录音。

**TN：** Go go go,五十三 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 wu3 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 wu3 shi2 san1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 016. v3-parity-mixed-zh-en-060

**原文：** Go go go，61 秒后开始录音。

**TN：** Go go go,六十一 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 liu4 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 liu4 shi2 yi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 017. v3-parity-mixed-zh-en-068

**原文：** Go go go，69 秒后开始录音。

**TN：** Go go go,六十九 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 liu4 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 liu4 shi2 jiu2 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 018. v3-parity-mixed-zh-en-076

**原文：** Go go go，77 秒后开始录音。

**TN：** Go go go,七十七 秒后开始录音。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `G OW1 G OW1 G OW1 qi1 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**修复前实际：** `G OW1 G OW1 G OW1 qi1 shi2 qi1 miao3 hou4 kai1 shi3 lu4 yin1`

**处理：** 修订数词拼音标注，保留当前 TN。

### 019. v3-parity-tn-numeric-date-money-unit-014

**原文：** 订单金额 15234.56 元，优惠 8.8 折。

**TN：** 订单金额 一万五千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 yi1 wan4 wu3 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 yi2 wan4 wu3 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 020. v3-parity-tn-numeric-date-money-unit-018

**原文：** 版本 v3.0.19 与 build 20260702 对齐。

**TN：** 版本 v三点零点一九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 021. v3-parity-tn-numeric-date-money-unit-034

**原文：** 速度 80km/h，距离目的地 35.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 三十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 san1 shi2 wu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 san1 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 022. v3-parity-tn-numeric-date-money-unit-050

**原文：** 订单金额 51234.56 元，优惠 8.8 折。

**TN：** 订单金额 五万一千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 wu3 wan4 yi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 wu3 wan4 yi4 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 023. v3-parity-tn-numeric-date-money-unit-054

**原文：** 版本 v3.0.55 与 build 20260702 对齐。

**TN：** 版本 v三点零点五五 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 wu3 wu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 wu2 wu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 024. v3-parity-tn-numeric-date-money-unit-058

**原文：** 速度 80km/h，距离目的地 59.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 五十九点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 wu3 shi2 jiu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 wu3 shi2 jiu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 025. v3-parity-tn-numeric-date-money-unit-078

**原文：** 版本 v3.0.79 与 build 20260702 对齐。

**TN：** 版本 v三点零点七九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 qi1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 qi1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 026. v3-parity-tn-numeric-date-money-unit-090

**原文：** 版本 v3.0.91 与 build 20260702 对齐。

**TN：** 版本 v三点零点九一 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 jiu3 yi1 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian2 jiu3 yi1 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 027. v3-parity-tn-numeric-date-money-unit-094

**原文：** 速度 80km/h，距离目的地 95.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 九十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 jiu3 shi2 wu3 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 jiu3 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 028. v3-parity-tn-numeric-date-money-unit-099

**原文：** 电量 100% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 029. v3-parity-tn-numeric-date-money-unit-100

**原文：** 股票 600519 今日上涨 101.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百零一点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 ling2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 ling2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 030. v3-parity-tn-numeric-date-money-unit-103

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 104 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百零四 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 ling2 si4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 ling2 si4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 ling2 si4 ci4`

**仍匹配原始标注：** 是

### 031. v3-parity-tn-numeric-date-money-unit-106

**原文：** 速度 80km/h，距离目的地 107.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百零七点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 ling2 qi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 ling2 qi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 032. v3-parity-tn-numeric-date-money-unit-110

**原文：** 订单金额 111234.56 元，优惠 8.8 折。

**TN：** 订单金额 十一万一千二百三十四点五六 元,优惠 八点八 折。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `ding4 dan1 jin1 e2 shi2 yi1 wan4 yi1 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**修复前实际：** `ding4 dan1 jin1 e2 shi2 yi2 wan4 yi4 qian1 er4 bai3 san1 shi2 si4 dian2 wu3 liu4 yuan2 you1 hui4 ba1 dian3 ba1 zhe2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 033. v3-parity-tn-numeric-date-money-unit-111

**原文：** 电量 112% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百一十二 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 yi1 shi2 er4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 yi4 shi2 er4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 034. v3-parity-tn-numeric-date-money-unit-112

**原文：** 股票 600519 今日上涨 113.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百一十三点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 yi1 shi2 san1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 yi4 shi2 san1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 035. v3-parity-tn-numeric-date-money-unit-114

**原文：** 版本 v3.0.115 与 build 20260702 对齐。

**TN：** 版本 v三点零点一一五 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 yi1 wu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 yi1 wu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 036. v3-parity-tn-numeric-date-money-unit-115

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 116 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百一十六 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**附加问题：** 这一条同时有标注错误：116 标成一百十六，缺少中间的一。前处理修复后仍与原始标注不匹配。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 shi2 liu4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 yi4 shi2 liu4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 yi1 shi2 liu4 ci4`

**仍匹配原始标注：** 否；原标注另有漏字，见附加问题

### 037. v3-parity-tn-numeric-date-money-unit-118

**原文：** 速度 80km/h，距离目的地 119.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百一十九点五 公里。

**判断：标注错误。** 119.5 应读一百一十九点五，旧标注漏了百后面的一；当前数值展开正确。一的表层变调与本调另属标注口径，mu4/m4 是相同模型 token 的别名。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 shi2 jiu2 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 yi4 shi2 jiu2 dian2 wu3 gong1 li3`

**处理：** 补回标注缺失的一，并在新标注中区分本调和实际送模型的变调。

### 038. v3-parity-tn-numeric-date-money-unit-123

**原文：** 电量 124% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百二十四 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 er4 shi2 si4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 er4 shi2 si4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 039. v3-parity-tn-numeric-date-money-unit-124

**原文：** 股票 600519 今日上涨 125.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百二十五点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 er4 shi2 wu2 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 er4 shi2 wu2 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 040. v3-parity-tn-numeric-date-money-unit-127

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 128 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百二十八 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 er4 shi2 ba1 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 er4 shi2 ba1 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 er4 shi2 ba1 ci4`

**仍匹配原始标注：** 是

### 041. v3-parity-tn-numeric-date-money-unit-130

**原文：** 速度 80km/h，距离目的地 131.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百三十一点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 san1 shi2 yi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 san1 shi2 yi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 042. v3-parity-tn-numeric-date-money-unit-135

**原文：** 电量 136% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百三十六 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 san1 shi2 liu4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 san1 shi2 liu4 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 043. v3-parity-tn-numeric-date-money-unit-136

**原文：** 股票 600519 今日上涨 137.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百三十七点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 san1 shi2 qi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 san1 shi2 qi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 044. v3-parity-tn-numeric-date-money-unit-138

**原文：** 版本 v3.0.139 与 build 20260702 对齐。

**TN：** 版本 v三点零点一三九 与 build 二零二六零七零二 对齐。

**判断：读法／标注口径差异。** 版本数字与后面的与连读时可发生三声变调；旧标注保留数字本调或不同韵律分组。当前没有增删版本数字。是否在版本号后停顿需由统一韵律规则决定，不能只以这一份拼音串判错。

**标注：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 san1 jiu3 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**修复前实际：** `ban2 ben3 V IY1 san1 dian3 ling2 dian3 yi1 san1 jiu2 yu3 B IH1 L D er4 ling2 er4 liu4 ling2 qi1 ling2 er4 dui4 qi2`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 045. v3-parity-tn-numeric-date-money-unit-139

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 140 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百四十 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 si4 shi2 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 si4 shi2 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 si4 shi2 ci4`

**仍匹配原始标注：** 是

### 046. v3-parity-tn-numeric-date-money-unit-142

**原文：** 速度 80km/h，距离目的地 143.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百四十三点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 si4 shi2 san1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 si4 shi2 san1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 047. v3-parity-tn-numeric-date-money-unit-147

**原文：** 电量 148% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百四十八 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 si4 shi2 ba1 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 si4 shi2 ba1 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 048. v3-parity-tn-numeric-date-money-unit-148

**原文：** 股票 600519 今日上涨 149.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百四十九点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 si4 shi2 jiu2 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 si4 shi2 jiu2 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 049. v3-parity-tn-numeric-date-money-unit-151

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 152 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百五十二 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai2 wu3 shi2 er4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai2 wu3 shi2 er4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai2 wu3 shi2 er4 ci4`

**仍匹配原始标注：** 是

### 050. v3-parity-tn-numeric-date-money-unit-154

**原文：** 速度 80km/h，距离目的地 155.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百五十五点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai2 wu3 shi2 wu2 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai2 wu3 shi2 wu2 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 051. v3-parity-tn-numeric-date-money-unit-159

**原文：** 电量 160% ，预计还能使用 30 分钟。

**TN：** 电量 百分之一百六十 ,预计还能使用 三十 分钟。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `dian4 liang4 bai3 fen1 zhi1 yi1 bai3 liu4 shi2 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**修复前实际：** `dian4 liang4 bai3 fen1 zhi1 yi4 bai3 liu4 shi2 yu4 ji4 hai2 neng2 shi3 yong4 san1 shi2 fen1 zhong1`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 052. v3-parity-tn-numeric-date-money-unit-160

**原文：** 股票 600519 今日上涨 161.23% ，请播报。

**TN：** 股票 六零零五一九 今日上涨 百分之一百六十一点二三 ,请播报。

**判断：读法／标注口径差异。** 数词与百、千、万等位数词结合时，一可在连续语流中变调；旧标注保留 yi1，当前给模型的是 yi4/yi2。单看书面本调与表层调的不同，不能认定前处理读错；数值展开未改变。

**标注：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi1 bai3 liu4 shi2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**修复前实际：** `gu3 piao4 liu4 ling2 ling2 wu3 yi1 jiu3 jin1 ri4 shang4 zhang2 bai3 fen1 zhi1 yi4 bai3 liu4 shi2 yi1 dian3 er4 san1 qing3 bo1 bao4`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 053. v3-parity-tn-numeric-date-money-unit-163

**原文：** 请加入 1/2 杯牛奶和 3/4 杯水，第 164 次。

**TN：** 请加入 二分之一 杯牛奶和 四分之三 杯水,第 一百六十四 次。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 liu4 shi2 si4 ci4`

**修复前实际：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi4 bai3 liu4 shi2 si4 ci4`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `qing3 jia1 ru4 er4 fen1 zhi1 yi1 bei1 niu2 nai3 he2 si4 fen1 zhi1 san1 bei1 shui3 di4 yi1 bai3 liu4 shi2 si4 ci4`

**仍匹配原始标注：** 是

### 054. v3-parity-tn-numeric-date-money-unit-166

**原文：** 速度 80km/h，距离目的地 167.5 公里。

**TN：** 速度 八十千米每小时,距离目的地 一百六十七点五 公里。

**判断：读法／标注口径差异。** 小数附近的三声连读或一百的一变调，与旧标注本调／分组口径不同；数值和单位未改变。mu4/m4 是相同模型 token 的反查别名，不是把目读成另一个声音。

**标注：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 mu4 di4 di4 yi1 bai3 liu4 shi2 qi1 dian2 wu3 gong1 li3`

**修复前实际：** `su4 du4 ba1 shi2 qian1 mi2 mei2 xiao3 shi2 ju4 li2 m4 di4 di4 yi4 bai3 liu4 shi2 qi1 dian2 wu3 gong1 li3`

**处理：** 保留原始标注；新的验收数据须注明本调／变调及停连口径，列出有限的可接受读法，不全局忽略声调。

### 055. v3-parity-polyphone-surname-proper-014

**原文：** 单于姓单，单独处理时不能读错，第 15 轮。

**TN：** 单于姓单,单独处理时不能读错,第 十五 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 yi1 wu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 shi2 wu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 056. v3-parity-polyphone-surname-proper-026

**原文：** 单于姓单，单独处理时不能读错，第 27 轮。

**TN：** 单于姓单,单独处理时不能读错,第 二十七 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 er4 qi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 er4 shi2 qi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 057. v3-parity-polyphone-surname-proper-038

**原文：** 单于姓单，单独处理时不能读错，第 39 轮。

**TN：** 单于姓单,单独处理时不能读错,第 三十九 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 san1 jiu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 san1 shi2 jiu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 058. v3-parity-polyphone-surname-proper-050

**原文：** 单于姓单，单独处理时不能读错，第 51 轮。

**TN：** 单于姓单,单独处理时不能读错,第 五十一 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 wu3 yi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 wu3 shi2 yi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 059. v3-parity-polyphone-surname-proper-062

**原文：** 单于姓单，单独处理时不能读错，第 63 轮。

**TN：** 单于姓单,单独处理时不能读错,第 六十三 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 liu4 san1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 liu4 shi2 san1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 060. v3-parity-polyphone-surname-proper-074

**原文：** 单于姓单，单独处理时不能读错，第 75 轮。

**TN：** 单于姓单,单独处理时不能读错,第 七十五 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 qi1 wu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 qi1 shi2 wu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 061. v3-parity-polyphone-surname-proper-086

**原文：** 单于姓单，单独处理时不能读错，第 87 轮。

**TN：** 单于姓单,单独处理时不能读错,第 八十七 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 ba1 qi1 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 ba1 shi2 qi1 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 062. v3-parity-polyphone-surname-proper-098

**原文：** 单于姓单，单独处理时不能读错，第 99 轮。

**TN：** 单于姓单,单独处理时不能读错,第 九十九 轮。

**判断：标注错误。** 秒数／第几轮是数值读法，旧标注把两位数拆成数字序列，漏了十。当前 TN 的完整数词正确；相关姓氏、多音字本身不是这条差异的原因。

**标注：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 jiu2 jiu3 lun2`

**修复前实际：** `chan2 yu2 xing4 shan4 dan1 du2 chu2 li3 shi2 bu4 neng2 du2 cuo4 di4 jiu3 shi2 jiu3 lun2`

**处理：** 修订数词拼音标注，保留当前 TN。

### 063. v3-parity-polyphone-surname-proper-099

**原文：** 区老师住在区庄附近，第 100 轮。

**TN：** 区老师住在区庄附近,第 一百 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi1 bai3 lun2`

**修复前实际：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi4 bai3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `ou1 lao3 shi1 zhu4 zai4 ou1 zhuang1 fu4 jin4 di4 yi1 bai3 lun2`

**仍匹配原始标注：** 是

### 064. v3-parity-polyphone-surname-proper-100

**原文：** 曾参和曾老师都在名单里，第 101 轮。

**TN：** 曾参和曾老师都在名单里,第 一百零一 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi1 bai3 ling2 yi1 lun2`

**修复前实际：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi4 bai3 ling2 yi1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `zeng1 shen1 he2 zeng1 lao3 shi1 dou1 zai4 ming2 dan1 li3 di4 yi1 bai3 ling2 yi1 lun2`

**仍匹配原始标注：** 是

### 065. v3-parity-polyphone-surname-proper-101

**原文：** 解经理正在解释合同，第 102 轮。

**TN：** 解经理正在解释合同,第 一百零二 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi1 bai3 ling2 er4 lun2`

**修复前实际：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi4 bai3 ling2 er4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `xie4 jing1 li3 zheng4 zai4 jie3 shi4 he2 tong5 di4 yi1 bai3 ling2 er4 lun2`

**仍匹配原始标注：** 是

### 066. v3-parity-polyphone-surname-proper-102

**原文：** 音乐响起以后，乐队开始排练，第 103 轮。

**TN：** 音乐响起以后,乐队开始排练,第 一百零三 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi1 bai3 ling2 san1 lun2`

**修复前实际：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi4 bai3 ling2 san1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `yin1 yue4 xiang2 qi2 yi3 hou4 yue4 dui4 kai1 shi3 pai2 lian4 di4 yi1 bai3 ling2 san1 lun2`

**仍匹配原始标注：** 是

### 067. v3-parity-polyphone-surname-proper-103

**原文：** 长大以后要去长安旅行，第 104 轮。

**TN：** 长大以后要去长安旅行,第 一百零四 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi1 bai3 ling2 si4 lun2`

**修复前实际：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi4 bai3 ling2 si4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `zhang3 da4 yi3 hou4 yao4 qu4 chang2 an1 lv3 xing2 di4 yi1 bai3 ling2 si4 lun2`

**仍匹配原始标注：** 是

### 068. v3-parity-polyphone-surname-proper-104

**原文：** 薄荷味很淡，薄书记也在现场，第 105 轮。

**TN：** 薄荷味很淡,薄书记也在现场,第 一百零五 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi1 bai3 ling2 wu3 lun2`

**修复前实际：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi4 bai3 ling2 wu3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `bo4 he5 wei4 hen3 dan4 bo2 shu1 ji4 ye3 zai4 xian4 chang3 di4 yi1 bai3 ling2 wu3 lun2`

**仍匹配原始标注：** 是

### 069. v3-parity-polyphone-surname-proper-105

**原文：** 任先生负责本次任务，第 106 轮。

**TN：** 任先生负责本次任务,第 一百零六 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi1 bai3 ling2 liu4 lun2`

**修复前实际：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi4 bai3 ling2 liu4 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `ren2 xian1 sheng1 fu4 ze2 ben3 ci4 ren4 wu4 di4 yi1 bai3 ling2 liu4 lun2`

**仍匹配原始标注：** 是

### 070. v3-parity-polyphone-surname-proper-106

**原文：** 朴老师介绍朴素的设计，第 107 轮。

**TN：** 朴老师介绍朴素的设计,第 一百零七 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi1 bai3 ling2 qi1 lun2`

**修复前实际：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi4 bai3 ling2 qi1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `piao2 lao3 shi1 jie4 shao4 pu3 su4 de5 she4 ji4 di4 yi1 bai3 ling2 qi1 lun2`

**仍匹配原始标注：** 是

### 071. v3-parity-polyphone-surname-proper-107

**原文：** 秘鲁客户咨询秘书安排，第 108 轮。

**TN：** 秘鲁客户咨询秘书安排,第 一百零八 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi1 bai3 ling2 ba1 lun2`

**修复前实际：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi4 bai3 ling2 ba1 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `bi4 lu3 ke4 hu4 zi1 xun2 mi4 shu1 an1 pai2 di4 yi1 bai3 ling2 ba1 lun2`

**仍匹配原始标注：** 是

### 072. v3-parity-polyphone-surname-proper-108

**原文：** 重庆火锅很好吃，重量也很足，第 109 轮。

**TN：** 重庆火锅很好吃,重量也很足,第 一百零九 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi1 bai3 ling2 jiu3 lun2`

**修复前实际：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi4 bai3 ling2 jiu3 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `chong2 qing4 huo3 guo1 hen2 hao3 chi1 zhong4 liang4 ye2 hen3 zu2 di4 yi1 bai3 ling2 jiu3 lun2`

**仍匹配原始标注：** 是

### 073. v3-parity-polyphone-surname-proper-109

**原文：** 银行行长正在整理行程，第 110 轮。

**TN：** 银行行长正在整理行程,第 一百一十 轮。

**判断：前处理缺陷。** 第与数字被空格拆成不同汉字块，导致序数中的一误走数量词变调。无空格与有空格输入应遵循同一序数读法；一百一十等数词内部的一也应保留序数上下文。

**标注：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi1 bai3 yi1 shi2 lun2`

**修复前实际：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi4 bai3 yi4 shi2 lun2`

**处理：** 已修复上下文传递：跨空白、跨同一数词保留第；标点或其他词终止该上下文。

**修复后：** `yin2 hang2 hang2 zhang3 zheng4 zai4 zheng2 li3 xing2 cheng2 di4 yi1 bai3 yi1 shi2 lun2`

**仍匹配原始标注：** 是

### 074. v3-parity-tn-numeric-date-money-unit-000

**原文：** 编号 1 的房间是 204，温度 -24.5 度。

**TN：** 编号 一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 075. v3-parity-tn-numeric-date-money-unit-012

**原文：** 编号 13 的房间是 204，温度 -24.5 度。

**TN：** 编号 十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 076. v3-parity-tn-numeric-date-money-unit-024

**原文：** 编号 25 的房间是 204，温度 -24.5 度。

**TN：** 编号 二十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 er4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 er4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 077. v3-parity-tn-numeric-date-money-unit-036

**原文：** 编号 37 的房间是 204，温度 -24.5 度。

**TN：** 编号 三十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 san1 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 san1 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 078. v3-parity-tn-numeric-date-money-unit-048

**原文：** 编号 49 的房间是 204，温度 -24.5 度。

**TN：** 编号 四十九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 si4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 si4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 079. v3-parity-tn-numeric-date-money-unit-060

**原文：** 编号 61 的房间是 204，温度 -24.5 度。

**TN：** 编号 六十一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 liu4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 liu4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 080. v3-parity-tn-numeric-date-money-unit-072

**原文：** 编号 73 的房间是 204，温度 -24.5 度。

**TN：** 编号 七十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 qi1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 qi1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 081. v3-parity-tn-numeric-date-money-unit-084

**原文：** 编号 85 的房间是 204，温度 -24.5 度。

**TN：** 编号 八十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 ba1 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 ba1 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 082. v3-parity-tn-numeric-date-money-unit-096

**原文：** 编号 97 的房间是 204，温度 -24.5 度。

**TN：** 编号 九十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 jiu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 jiu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 083. v3-parity-tn-numeric-date-money-unit-108

**原文：** 编号 109 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百零九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 ling2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 ling2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 084. v3-parity-tn-numeric-date-money-unit-120

**原文：** 编号 121 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百二十一 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 er4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 er4 shi2 yi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 085. v3-parity-tn-numeric-date-money-unit-132

**原文：** 编号 133 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百三十三 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 san1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 san1 shi2 san1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 086. v3-parity-tn-numeric-date-money-unit-144

**原文：** 编号 145 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百四十五 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 si4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 si4 shi2 wu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 087. v3-parity-tn-numeric-date-money-unit-156

**原文：** 编号 157 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百五十七 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai2 wu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai2 wu3 shi2 qi1 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 088. v3-parity-tn-numeric-date-money-unit-168

**原文：** 编号 169 的房间是 204，温度 -24.5 度。

**TN：** 编号 一百六十九 的房间是 二零四,温度零下二十四点五度。

**判断：读法／标注口径差异。** -24.5 度读零下二十四点五度或负二十四点五度，数值含义相同，当前温度归一化合理。编号中一百等的 yi1/yi4 差异属于本调与表层调。

**标注：** `bian1 hao4 yi1 bai3 liu4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 fu4 er4 shi2 si4 dian2 wu3 du4`

**修复前实际：** `bian1 hao4 yi4 bai3 liu4 shi2 jiu3 de5 fang2 jian1 shi4 er4 ling2 si4 wen1 du4 ling2 xia4 er4 shi2 si4 dian2 wu3 du4`

**处理：** 语义验收接受负／零下两种明确写出的候选；无需修改温度前处理。

### 089. v3-parity-tn-numeric-date-money-unit-001

**原文：** 今天是 2026 年 7 月 2 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 二 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 090. v3-parity-tn-numeric-date-money-unit-013

**原文：** 今天是 2026 年 7 月 14 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 十四 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 091. v3-parity-tn-numeric-date-money-unit-025

**原文：** 今天是 2026 年 7 月 26 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 二十六 日,下午 三点零五分 开会。

**判断：读法／标注口径差异。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 er4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 092. v3-parity-tn-numeric-date-money-unit-037

**原文：** 今天是 2026 年 7 月 38 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 三十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 38 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 san1 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 093. v3-parity-tn-numeric-date-money-unit-049

**原文：** 今天是 2026 年 7 月 50 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 五十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 50 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 wu3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 094. v3-parity-tn-numeric-date-money-unit-061

**原文：** 今天是 2026 年 7 月 62 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 六十二 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 62 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 liu4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 095. v3-parity-tn-numeric-date-money-unit-073

**原文：** 今天是 2026 年 7 月 74 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 七十四 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 74 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 qi1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 096. v3-parity-tn-numeric-date-money-unit-085

**原文：** 今天是 2026 年 7 月 86 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 八十六 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 86 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 ba1 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 ba1 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 097. v3-parity-tn-numeric-date-money-unit-097

**原文：** 今天是 2026 年 7 月 98 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 九十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 98 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 jiu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 jiu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 098. v3-parity-tn-numeric-date-money-unit-109

**原文：** 今天是 2026 年 7 月 110 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百一十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 110 日，不是有效日期；不把这些输入当正常日期发音验收。；旧标注还把 110 写成一百十，漏了一；应为一百一十。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 yi4 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 099. v3-parity-tn-numeric-date-money-unit-121

**原文：** 今天是 2026 年 7 月 122 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百二十二 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 122 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 er4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 er4 shi2 er4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 100. v3-parity-tn-numeric-date-money-unit-133

**原文：** 今天是 2026 年 7 月 134 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百三十四 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 134 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 san1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 san1 shi2 si4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 101. v3-parity-tn-numeric-date-money-unit-145

**原文：** 今天是 2026 年 7 月 146 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百四十六 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 146 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 si4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 si4 shi2 liu4 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 102. v3-parity-tn-numeric-date-money-unit-157

**原文：** 今天是 2026 年 7 月 158 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百五十八 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 158 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai2 wu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai2 wu3 shi2 ba1 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 103. v3-parity-tn-numeric-date-money-unit-169

**原文：** 今天是 2026 年 7 月 170 日，下午 3:05 开会。

**TN：** 今天是 二零二六年 七 月 一百七十 日,下午 三点零五分 开会。

**判断：语料内容无效或自相矛盾。** 3:05 读三点零五或三点零五分均正确；分是时间单位，不是误读冒号。

**附加问题：** 原文为 7 月 170 日，不是有效日期；不把这些输入当正常日期发音验收。

**标注：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi1 bai3 qi1 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 kai1 hui4`

**修复前实际：** `jin1 tian1 shi4 er4 ling2 er4 liu4 nian2 qi1 yue4 yi4 bai3 qi1 shi2 ri4 xia4 wu3 san1 dian3 ling2 wu3 fen1 kai1 hui4`

**处理：** 接受两个时间读法；无效日期另建有效样例，旧输入仅保留容错检查。

### 104. v3-parity-tn-numeric-date-money-unit-005

**原文：** 路径 /sdcard/test/6/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 105. v3-parity-tn-numeric-date-money-unit-017

**原文：** 路径 /sdcard/test/18/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 106. v3-parity-tn-numeric-date-money-unit-029

**原文：** 路径 /sdcard/test/30/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠三零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 san1 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 san1 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 107. v3-parity-tn-numeric-date-money-unit-041

**原文：** 路径 /sdcard/test/42/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠四二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 si4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 si4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 108. v3-parity-tn-numeric-date-money-unit-053

**原文：** 路径 /sdcard/test/54/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠五四,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 wu3 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 wu3 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 109. v3-parity-tn-numeric-date-money-unit-065

**原文：** 路径 /sdcard/test/66/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠六六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 liu4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 liu4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 110. v3-parity-tn-numeric-date-money-unit-077

**原文：** 路径 /sdcard/test/78/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠七八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 qi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 qi1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 111. v3-parity-tn-numeric-date-money-unit-089

**原文：** 路径 /sdcard/test/90/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠九零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 jiu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 jiu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 112. v3-parity-tn-numeric-date-money-unit-101

**原文：** 路径 /sdcard/test/102/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一零二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 ling2 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 ling2 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 113. v3-parity-tn-numeric-date-money-unit-113

**原文：** 路径 /sdcard/test/114/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一一四,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 yi1 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 yi1 si4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 114. v3-parity-tn-numeric-date-money-unit-125

**原文：** 路径 /sdcard/test/126/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一二六,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 er4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 er4 liu4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 115. v3-parity-tn-numeric-date-money-unit-137

**原文：** 路径 /sdcard/test/138/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一三八,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 san1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 san1 ba1 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 116. v3-parity-tn-numeric-date-money-unit-149

**原文：** 路径 /sdcard/test/150/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一五零,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 wu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 wu3 ling2 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 117. v3-parity-tn-numeric-date-money-unit-161

**原文：** 路径 /sdcard/test/162/audio.wav 已生成。

**TN：** 路径 斜杠sdcard斜杠test斜杠一六二,斜杠audio点wav 已生成。

**判断：读法／标注口径差异。** sdcard 是路径标识符。当前完整拼出 S D C A R D，没有丢字；旧标注按 SD 加 card 读，更自然但并非唯一合法读法。路径数字、斜杠和后缀在本条均完整。

**标注：** `lu4 jing4 xie2 gang4 EH1 S D IY1 K AA1 R D xie2 gang4 T EH1 S T xie2 gang4 yi1 liu4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**修复前实际：** `lu4 jing4 xie2 gang4 EH1 S D IY1 S IY1 EY1 AA1 R D IY1 xie2 gang4 T EH1 S T xie2 gang4 yi1 liu4 er4 xie2 gang4 AO1 D IY0 OW2 dian3 D AH1 B AH0 L Y UW0 EY1 V IY1 yi3 sheng1 cheng2`

**处理：** 不按功能缺陷改动；可把 SD+card 作为将来技术词词典的自然度优化，需明确产品读法。

### 118. v3-parity-tn-numeric-date-money-unit-011

**原文：** 坐标 N22.12 E113.11，导航继续。

**TN：** 坐标 北纬二十二点一二 东经一百一十三点一一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 119. v3-parity-tn-numeric-date-money-unit-023

**原文：** 坐标 N22.24 E113.23，导航继续。

**TN：** 坐标 北纬二十二点二四 东经一百一十三点二三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 er4 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 er4 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 er4 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 er4 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 120. v3-parity-tn-numeric-date-money-unit-035

**原文：** 坐标 N22.36 E113.35，导航继续。

**TN：** 坐标 北纬二十二点三六 东经一百一十三点三五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 san1 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian3 san1 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 san1 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 san1 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 121. v3-parity-tn-numeric-date-money-unit-047

**原文：** 坐标 N22.48 E113.47，导航继续。

**TN：** 坐标 北纬二十二点四八 东经一百一十三点四七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 si4 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 si4 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 si4 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 si4 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 122. v3-parity-tn-numeric-date-money-unit-059

**原文：** 坐标 N22.60 E113.59，导航继续。

**TN：** 坐标 北纬二十二点六零 东经一百一十三点五九,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。；点五九／点九五的三声组合另有分组差异：A+BC 与 AB+C 不能一律要求同一个表层调串。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 liu4 ling2 dong1 jing1 yi1 bai3 shi2 san1 dian2 wu2 jiu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 liu4 ling2 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 wu2 jiu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 123. v3-parity-tn-numeric-date-money-unit-071

**原文：** 坐标 N22.72 E113.71，导航继续。

**TN：** 坐标 北纬二十二点七二 东经一百一十三点七一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 qi1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 qi1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 qi1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 qi1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 124. v3-parity-tn-numeric-date-money-unit-083

**原文：** 坐标 N22.84 E113.83，导航继续。

**TN：** 坐标 北纬二十二点八四 东经一百一十三点八三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 ba1 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 ba1 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 ba1 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 ba1 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 125. v3-parity-tn-numeric-date-money-unit-095

**原文：** 坐标 N22.96 E113.95，导航继续。

**TN：** 坐标 北纬二十二点九六 东经一百一十三点九五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。；点五九／点九五的三声组合另有分组差异：A+BC 与 AB+C 不能一律要求同一个表层调串。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian2 jiu3 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian2 jiu2 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian2 jiu3 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 jiu2 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 126. v3-parity-tn-numeric-date-money-unit-107

**原文：** 坐标 N22.108 E113.107，导航继续。

**TN：** 坐标 北纬二十二点一零八 东经一百一十三点一零七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 ling2 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 ling2 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 ling2 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 ling2 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 127. v3-parity-tn-numeric-date-money-unit-119

**原文：** 坐标 N22.120 E113.119，导航继续。

**TN：** 坐标 北纬二十二点一二零 东经一百一十三点一一九,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 ling2 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 yi1 jiu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 er4 ling2 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 yi1 jiu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 128. v3-parity-tn-numeric-date-money-unit-131

**原文：** 坐标 N22.132 E113.131，导航继续。

**TN：** 坐标 北纬二十二点一三二 东经一百一十三点一三一,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 san1 er4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 san1 yi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 san1 er4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 san1 yi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 129. v3-parity-tn-numeric-date-money-unit-143

**原文：** 坐标 N22.144 E113.143，导航继续。

**TN：** 坐标 北纬二十二点一四四 东经一百一十三点一四三,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 si4 si4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 si4 san1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 si4 si4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 si4 san1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 130. v3-parity-tn-numeric-date-money-unit-155

**原文：** 坐标 N22.156 E113.155，导航继续。

**TN：** 坐标 北纬二十二点一五六 东经一百一十三点一五五,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**附加问题：** 旧标注还跨逗号把末位三声音节与导航的导做变调；当前在逗号停止连读，保留末位三声。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 wu3 liu4 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 wu2 wu2 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 wu3 liu4 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 wu2 wu3 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 131. v3-parity-tn-numeric-date-money-unit-167

**原文：** 坐标 N22.168 E113.167，导航继续。

**TN：** 坐标 北纬二十二点一六八 东经一百一十三点一六七,导航继续。

**判断：标注错误。** 经度整数部分 113 应读一百一十三；旧标注统一漏掉百后面的一。当前完整数词正确，一的变调与本调属于另一个标注维度。

**标注：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 liu4 ba1 dong1 jing1 yi1 bai3 shi2 san1 dian3 yi1 liu4 qi1 dao3 hang2 ji4 xu4`

**修复前实际：** `zuo4 biao1 bei2 wei3 er4 shi2 er4 dian3 yi1 liu4 ba1 dong1 jing1 yi4 bai3 yi4 shi2 san1 dian3 yi1 liu4 qi1 dao3 hang2 ji4 xu4`

**处理：** 补回标注缺失的一，修正跨标点变调；不要把正确的前处理改成漏字。

### 132. v3-parity-frontend-rules-technical-003

**原文：** 命令 adb shell am start -n demo/4 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 133. v3-parity-frontend-rules-technical-013

**原文：** 命令 adb shell am start -n demo/14 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠一四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 yi1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 yi1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 134. v3-parity-frontend-rules-technical-023

**原文：** 命令 adb shell am start -n demo/24 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠二四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 er4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 er4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 135. v3-parity-frontend-rules-technical-033

**原文：** 命令 adb shell am start -n demo/34 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠三四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 san1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 san1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 136. v3-parity-frontend-rules-technical-043

**原文：** 命令 adb shell am start -n demo/44 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠四四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 si4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 137. v3-parity-frontend-rules-technical-053

**原文：** 命令 adb shell am start -n demo/54 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠五四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 wu3 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 wu3 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 138. v3-parity-frontend-rules-technical-063

**原文：** 命令 adb shell am start -n demo/64 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠六四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 liu4 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 liu4 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 139. v3-parity-frontend-rules-technical-073

**原文：** 命令 adb shell am start -n demo/74 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠七四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 qi1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 qi1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 140. v3-parity-frontend-rules-technical-083

**原文：** 命令 adb shell am start -n demo/84 不应读乱。

**TN：** 命令 adb shell am start 杠n demo斜杠八四 不应读乱。

**判断：读法／标注口径差异。** 这里的 am 是 adb shell 的命令名，不是 I am 中的英语动词。拼读 A M 可以准确传达命令；旧标注把它读成英语单词 am，只能作为另一种读法选择。

**标注：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L AE1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 ba1 si4 bu4 ying1 du2 luan4`

**修复前实际：** `ming4 ling4 EY1 D IY1 B IY1 SH EH1 L EY1 EH1 M S T AA1 R T gang4 EH1 N D EH1 M OW0 xie2 gang4 ba1 si4 bu4 ying1 du2 luan4`

**处理：** 保留命令上下文的字母读法；若扩充候选，只针对这些命令样例，不影响普通英语。

### 141. v3-parity-symbols-unicode-failsoft-003

**原文：** ＡＢＣ１２３ 已经转换完成，编号 4。

**TN：** ABC一二三 已经转换完成,编号 四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 142. v3-parity-symbols-unicode-failsoft-013

**原文：** ＡＢＣ１２３ 已经转换完成，编号 14。

**TN：** ABC一二三 已经转换完成,编号 十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 143. v3-parity-symbols-unicode-failsoft-023

**原文：** ＡＢＣ１２３ 已经转换完成，编号 24。

**TN：** ABC一二三 已经转换完成,编号 二十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 er4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 er4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 144. v3-parity-symbols-unicode-failsoft-033

**原文：** ＡＢＣ１２３ 已经转换完成，编号 34。

**TN：** ABC一二三 已经转换完成,编号 三十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 san1 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 san1 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 145. v3-parity-symbols-unicode-failsoft-043

**原文：** ＡＢＣ１２３ 已经转换完成，编号 44。

**TN：** ABC一二三 已经转换完成,编号 四十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 si4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 146. v3-parity-symbols-unicode-failsoft-053

**原文：** ＡＢＣ１２３ 已经转换完成，编号 54。

**TN：** ABC一二三 已经转换完成,编号 五十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 wu3 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 wu3 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 147. v3-parity-symbols-unicode-failsoft-063

**原文：** ＡＢＣ１２３ 已经转换完成，编号 64。

**TN：** ABC一二三 已经转换完成,编号 六十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 liu4 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 liu4 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 148. v3-parity-symbols-unicode-failsoft-073

**原文：** ＡＢＣ１２３ 已经转换完成，编号 74。

**TN：** ABC一二三 已经转换完成,编号 七十四。

**判断：读法／标注口径差异。** 全角 ABC123 已正确转为半角标识符。标识符中的 123 逐位读一二三合理；旧标注读一百二十三也能表达数字，但不能作为唯一强制读法。

**标注：** `EY1 B IY1 S IY1 yi1 bai3 er4 shi2 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 qi1 shi2 si4`

**修复前实际：** `EY1 B IY1 S IY1 yi1 er4 san1 yi3 jing1 zhuan3 huan4 wan2 cheng2 bian1 hao4 qi1 shi2 si4`

**处理：** 按标识符逐位读的现有规则保留；数量词与标识符分别验收。

### 149. v3-parity-symbols-unicode-failsoft-005

**原文：** 货币符号 ¥6.00、$6.99、€6 同时出现。

**TN：** 货币符号 六元、六点九九美元、六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 liu4 dian3 ling2 ling2 yuan2 liu4 dian2 jiu2 jiu2 mei3 yuan2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 liu4 yuan2 liu4 dian3 jiu2 jiu2 mei3 yuan2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 150. v3-parity-symbols-unicode-failsoft-015

**原文：** 货币符号 ¥16.00、$16.99、€16 同时出现。

**TN：** 货币符号 十六元、十六点九九美元、十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 shi2 liu4 dian3 ling2 ling2 yuan2 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 shi2 liu4 yuan2 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 151. v3-parity-symbols-unicode-failsoft-025

**原文：** 货币符号 ¥26.00、$26.99、€26 同时出现。

**TN：** 货币符号 二十六元、二十六点九九美元、二十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 er4 shi2 liu4 dian3 ling2 ling2 yuan2 er4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 er4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 er4 shi2 liu4 yuan2 er4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 er4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 152. v3-parity-symbols-unicode-failsoft-035

**原文：** 货币符号 ¥36.00、$36.99、€36 同时出现。

**TN：** 货币符号 三十六元、三十六点九九美元、三十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 san1 shi2 liu4 dian3 ling2 ling2 yuan2 san1 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 san1 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 san1 shi2 liu4 yuan2 san1 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 san1 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 153. v3-parity-symbols-unicode-failsoft-045

**原文：** 货币符号 ¥46.00、$46.99、€46 同时出现。

**TN：** 货币符号 四十六元、四十六点九九美元、四十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 si4 shi2 liu4 dian3 ling2 ling2 yuan2 si4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 si4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 si4 shi2 liu4 yuan2 si4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 si4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 154. v3-parity-symbols-unicode-failsoft-055

**原文：** 货币符号 ¥56.00、$56.99、€56 同时出现。

**TN：** 货币符号 五十六元、五十六点九九美元、五十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 wu3 shi2 liu4 dian3 ling2 ling2 yuan2 wu3 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 wu3 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 wu3 shi2 liu4 yuan2 wu3 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 wu3 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。

### 155. v3-parity-symbols-unicode-failsoft-065

**原文：** 货币符号 ¥66.00、$66.99、€66 同时出现。

**TN：** 货币符号 六十六元、六十六点九九美元、六十六欧元 同时出现。

**判断：读法／标注口径差异。** 人民币金额 .00 可以省略，六元与六点零零元表达同一金额。美元金额的小数仍完整；点九九美中的多个三声有不同停连分组，不能把单个表层调串视为唯一答案。

**标注：** `huo4 bi4 fu2 hao4 liu4 shi2 liu4 dian3 ling2 ling2 yuan2 liu4 shi2 liu4 dian2 jiu2 jiu2 mei3 yuan2 liu4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**修复前实际：** `huo4 bi4 fu2 hao4 liu4 shi2 liu4 yuan2 liu4 shi2 liu4 dian3 jiu2 jiu2 mei3 yuan2 liu4 shi2 liu4 ou1 yuan2 tong2 shi2 chu1 xian4`

**处理：** 接受明确的等值金额读法；把金额内容正确性与自然连读韵律分开评价。
