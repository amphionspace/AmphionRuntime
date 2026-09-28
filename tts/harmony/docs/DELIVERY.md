# Harmony TTS 源码与模型交接

构建步骤与资源清单只在 [BUILD_FROM_SOURCE.md](BUILD_FROM_SOURCE.md) 维护。以下区分源码、受控资产和生成物。

| 内容 | 位置与处理方式 |
| --- | --- |
| SDK、sample、工程配置和文档 | 仓库 `tts/harmony/`；提交源码及必要工程文件 |
| TN 源码与构建工具 | `tts/training/dingqiao_lits/`、`tts/tools/tn/`；按源码编译说明准备依赖 |
| 模型、前端词典和规则 | `tts/tools/trial-export/dingqiao_lits_en_zh_vocos24k_streaming_proto_external_loop/0.1.0/`；从受控资产恢复，不进 Git |
| 模型复制结果 | `tts/harmony/sdk/src/main/resources/rawfile/lits-models/tts/`；构建生成，不作为源资产编辑 |
| TN 可执行文件 | `tts/harmony/build-ohos-tn/`；构建生成，或使用模型包中匹配平台的 TN 文件 |
| HAR 与 HAP | 各模块 `build/default/outputs/default/`；不进 Git |

源资产已经包含校验过的词典 `.bin`。普通构建只读复制，不在原始模型包中生成或覆盖词典。模型 ID、资源版本、SHA-256 和实际构建提交应随交接记录；源码目录不包含模型不等于交付可缺模型。

不得提交或放入源码包：`.hvigor`、`.ohos`、`build`、本地签名配置、私钥、证书口令和授权文件。需要授权时按约定受控交付。

HAR 是集成产物；sample HAP 是验证载体。若本次包含可安装 Demo，必须对签名及真机行为另行验证，不能交付 unsigned HAP 并宣称可安装。
