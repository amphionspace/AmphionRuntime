# ZIP 角色分离快速专项

结果：PASS。使用已绑定最终 ZIP 的正式 HAR 与包内源码构建 HAP。

首轮约171秒真实语音缺少120秒后句末，未覆盖中间分窗，原始FAIL保留。第二轮仅在130.869秒已有语句结束处插入5秒静音，保持其余音频、参数、HAP和设备一致。

第二轮批次：[{"windowIndex": 0, "windowBeginTime": 0, "windowEndTime": 133120, "isSessionFinal": false, "degraded": false, "speakerCount": 4}, {"windowIndex": 1, "windowBeginTime": 133120, "windowEndTime": 175880, "isSessionFinal": true, "degraded": false, "speakerCount": 4}]

本次只验证分窗、冻结和结束回调，不代表精度、长期稳定性或断网抓包验收。源码载体内部资源探针不可用。

详见 [报告](report.json)。
