# Golden pinyin/phoneme 疑似错误（供人工复审）

源文件：`pronunciation-golden-round3-results-with-pinyin-fixed.jsonl`（675 条）

说明: 只列出我认为 **golden 本身可疑/错误** 的样例，不是系统 actual 与 golden 不一致的全部 mismatch。同类模板只给代表样例 + id 列表。

---

## A. 高置信：字段约定错误

### A1. en-core：ARPABET 写入了 `golden_pinyin`（60/60）

约定：`golden_pinyin` 只覆盖中文音节；英文在 `golden_phoneme`。

- **v3-parity-en-core-000**: Hello, welcome to the text to speech parity test number 1.
  - golden_pinyin: `HH AH0 L OW1 W EH1 L K AH0 M ...`（整段 ARPABET）
  - actual_pinyin: `[]`（空，符合中文-only）
  - 建议: `golden_pinyin=[]`；核对 `golden_phoneme`

同类还有 **v3-parity-known-regression-005 / 006**（英文句同样把 ARPABET 塞进了 golden_pinyin）。

### A2. 验证码：拉丁字母写入 `golden_pinyin`（8条）

- **v3-parity-zh-core-008**: 验证码是 A9B8C7-9，请不要告诉别人。
  - golden_pinyin: `yan4 zheng4 ma3 shi4 EY1 jiu3 B IY1 ba1 S IY1 qi1 gang4 jiu3 ...`
  - actual_pinyin: `yan4 zheng4 ma3 shi4 jiu3 ba1 qi1 gang4 jiu3 ...`
  - 问题: `EY1/B/IY1/S/IY1` 不应在 golden_pinyin；且与 golden_phoneme 声调对不齐
  - 建议中文部分: `yan4 zheng4 ma3 shi4 jiu3 ba1 qi1 gang4 jiu3 qing3 bu2 yao4 gao4 su4 bie2 ren2`
  - 同类: `zh-core-008/018/028/038/048/058/068/078`

---

## B. 高置信：读音错误

### B1. 「串行」标成 `chuan4 hang2`（应为 `chuan4 xing2`）

- **v3-parity-known-regression-009**: 排队请求应该串行完成，并且每个 requestId 都只终止一次。
  - golden_pinyin: `... chuan4 hang2 wan2 cheng2 ...`
  - 建议: `chuan4 xing2`（“串行/并行”的行）
  - 注: actual 也是 `hang2`，属于 golden 与系统一起错

### B2. 「五点」未做三声变调（8条）

表面调约定下，`wu3 dian3` → `wu2 dian3`。

- **v3-parity-zh-core-004**: 闹钟设为 5 点 05 分，提醒我喝水。
  - golden: `... wu3 dian3 ling2 wu3 ... ti2 xing3 ...`
  - 建议: `... wu2 dian3 ling2 wu3 ... ti2 xing3 ...`
  - 注: `05`→`ling2 wu3`、`提醒`→`ti2 xing3` 这两处 fixed 是对的
  - 同类: `zh-core-004/014/024/034/044/054/064/074`

### B3. 「不能」未做「不」变调（9条）

- **v3-parity-polyphone-surname-proper-002**: 单于姓单，单独处理时不能读错，第 3 轮。
  - golden: `bu4 neng2` → 建议 `bu2 neng2`
  - 同类: `...-002/014/026/038/050/062/074/086/098`

### B4. 「一」变调缺失（多处）

- **第 1 轮/名/条** 后接非去声：`di4 yi1 lun2/ming2/tiao2` → 建议 `yi4`
  - 例: `v3-parity-polyphone-surname-proper-000`, `v3-parity-known-regression-002`, `v3-parity-symbols-unicode-failsoft-000`
- **第 1 次** 后接去声：`di4 yi1 ci4` → 建议 `yi2`
  - 例: `v3-parity-mixed-zh-en-000`
- **第一百…**: `di4 yi1 bai3` → 建议 `yi4 bai3`（约十几条 tn/polyphone）

### B5. URL / 邮箱类 golden_pinyin 严重残缺（frontend-rules，约 27 条）

`golden_phoneme` 里其实有英文段，但 `golden_pinyin` 只剩符号中文读法，且符号读法也不完整。

- **v3-parity-frontend-rules-technical-000**: 请访问 https://example.com/help/1?q=lits-v3。
  - golden_pinyin: `qing2 fang3 wen4 xie2 gang4 xie2 gang4 xie2 gang4 xie2 gang4 yi1 deng3 yu2 gang4 san1`
  - 问题:
    1. 几乎没有域名/路径的中文可读表示（依赖 phoneme 里的英文）
    2. `?` 被标成 `deng3 yu2`（把 `=` 的读法错位到了 `?`）；actual 是 `wen4 hao4`
  - actual_pinyin: `... dian3 xie2 gang4 ... yi1 wen4 hao4 deng3 yu2 gang4 san1`

- **v3-parity-frontend-rules-technical-001**: 反馈邮箱是 service+2@example.com。
  - golden_pinyin: `fan3 kui4 you2 xiang1 shi4 jia1 er4 ai4 te4`（缺 `.`→`dian3` 等）
  - actual: 末尾多 `dian3`

- **v3-parity-frontend-rules-technical-009**: 链接 www.example.com/release/v3/10 需要稳定。
  - golden 把 `www.` 的点丢掉，只剩一串 `xie2 gang4`
  - actual 有 `dian3 dian3`

同类: frontend-rules 中所有 `http/www/@` 模板（url≈18，mail≈9）。

### B6. 同一句里小数点「点」调值不一致（规则性 bug，约 70 条量级）

根因: 自动标注对小数点 `dian3` 做了三声连读；后接三声数字（五/九）→`dian2`，否则仍 `dian3`。

若产品要求小数点统一 `dian3`（与当前系统一致），则 golden 错；若坚持严格表面变调，可保留，但同句会不一致。

- **v3-parity-zh-core-006**: 本次订单金额为 7234.56 元，优惠 8.8 折。
  - `7234.56` → `dian2 wu3`；`8.8折` → `dian3 ba1`
- **v3-parity-symbols-unicode-failsoft-005**: ¥6.00→`dian3`，\$6.99→`dian2 jiu2 jiu3`
- **v3-parity-tn-numeric-date-money-unit-059**: 22.60→`dian3`，113.59→`dian2 wu2 jiu2`

---

## C. 需产品约定（不一定算标错）

### C1. 年份 `2026年`：基数 vs 逐字（约 23 条）

- **v3-parity-zh-core-005**: 会议安排在 2026 年 7 月 6 日星期四。
  - golden: `er4 qian1 ling2 er4 shi2 liu4 nian2`（二千零二十六）
  - actual: `er4 ling2 er4 liu4 nian2`（二零二六）

### C2. 电话横线 `-`：省略 vs 读 `gang4`（8 条）

- **v3-parity-zh-core-007**: 客服电话是 400-800-0008，请稍后拨打。
  - golden 省略横线；actual 读 `gang4`
  - 注: fixed 已去掉更糟的 `fu4(负)`，这是改进

### C3. `10号楼`：`shi2` vs `yi1 ling2`（1 条）

- **v3-parity-zh-core-009**: 请导航到深圳市南山区科技园 10 号楼。

### C4. 房间号 `204`：基数 `er4 bai3 ling2 si4` vs 逐字 `er4 ling2 si4`

- **v3-parity-known-regression-000**: 房间 204 的门已经打开...
  - 若产品对门牌/房间号要求逐字读，则 golden 偏基数

---

## D. 我认为 golden 正确（避免误伤）

- `调到` → `tiao2 dao4`（系统常错成 `diao4`）
- `提醒` → `ti2 xing3`（fixed 已改对）
- `相差` → `xiang1 cha4`（actual 的 `cha1` 才是错的）
- 多音字集抽查通过：重庆/银行行长/单于/区老师/曾参/解经理/音乐/长安/薄荷/朴老师/秘鲁/处理(chu2 li3)
- `05分` 补 `ling2`：相对旧 oracle 是改进
- `不要` → `bu2 yao4`：正确

---

## 建议你优先复审的顺序

1. **B1 串行**（明确读错，1 条但关键）
2. **A1/A2 字段污染**（60+8+2，改法明确）
3. **B5 URL/邮箱**（frontend-rules 整类 golden_pinyin 基本不可用）
4. **B2/B3/B4 变调**（规则清晰，可批量修）
5. **B6 小数点 dian2/dian3**（先定产品策略再改）
6. **C 类产品约定**（年份/电话杠/门牌）
