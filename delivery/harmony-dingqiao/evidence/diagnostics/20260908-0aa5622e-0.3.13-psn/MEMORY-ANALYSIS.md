# 声纹回退内存门禁诊断

源码：0aa5622e77cb55da46d40522af70ce1a372e331c。

首次 3 轮全部 SDK 契约 PASS，RSS 头尾增长 84.609 MiB，VmData 增长 9.656 MiB，因原有 64 MiB 阈值 FAIL。失败证据保留为 non-canonical，未修改阈值。

待证伪假设：增长集中在冷态首次评分和分配器驻留，热态不会按轮持续增长。
新增观测：每 5 秒获取 hidumper --mem，比较 native heap PSS、Heap Alloc、.hap 映射；与既有逐秒 RSS/VmData 及 cold/warm 回调轨迹对齐。
唯一输入变化：保持同一 HAP、语料与参数，将观察窗从 3 轮扩展到 12 轮，以包含足够的热态阶段。
放弃判据：热态 Heap Alloc 与 RSS 持续按轮上升，或任一 SDK 契约失败。
停止条件：单次 12 轮结束，或 240 秒超时；不无条件追加重放。

结果：12 轮、132.555 秒，SDK 与 memory 均 PASS。稳态 RSS 610.664 → 610.176 MiB（-0.488 MiB），VmData +4.281 MiB，threads -1；系统 Heap Alloc 在热态出现回落。该观察窗未见按轮持续累积；不推断更长时运行必然无泄漏。
