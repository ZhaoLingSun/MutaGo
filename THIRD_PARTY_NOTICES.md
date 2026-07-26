# 第三方许可证与归属索引

本文是 KataGo `v1.16.5` 冻结基线树中第三方许可证、NOTICE 与来源说明位置的可维护索引，不是许可证全文，也不是发布级 SBOM。

- **FROZEN：** 下列路径已在提交 `ba938676d7f42d70950b3a535af2466fb642008c` 的树中核验。
- **FROZEN：** 每个原始许可证、NOTICE、COPYING 或文件内嵌版权头仍是对应内容的权威文本。
- **AUDIT-BLOCKED：** 发布级依赖清单、二进制打包义务和未 vendored 运行时依赖必须在实际发行范围确定后审计。

## 独立许可证与 NOTICE 文件

| 组件或来源 | 许可证/说明 | 仓库内权威路径 |
| --- | --- | --- |
| CLBlast 内核 | Apache License 2.0 | [cpp/external/clblast/LICENSE](cpp/external/clblast/LICENSE) |
| ghc::filesystem 1.5.8 | MIT | [cpp/external/filesystem-1.5.8/LICENSE](cpp/external/filesystem-1.5.8/LICENSE) |
| half 2.2.0 | MIT | [cpp/external/half-2.2.0/LICENSE.txt](cpp/external/half-2.2.0/LICENSE.txt) |
| cpp-httplib | MIT | [cpp/external/httplib/LICENSE](cpp/external/httplib/LICENSE) |
| katagocoreml-cpp | BSD 3-Clause | [cpp/external/katagocoreml/LICENSE](cpp/external/katagocoreml/LICENSE) |
| katagocoreml 汇总归属 | Apple coremltools、nlohmann/json、FP16 及测试模型说明 | [cpp/external/katagocoreml/NOTICE](cpp/external/katagocoreml/NOTICE) |
| katagocoreml vendored FP16 | MIT | [cpp/external/katagocoreml/vendor/deps/FP16/LICENSE](cpp/external/katagocoreml/vendor/deps/FP16/LICENSE) |
| Apple Core ML protobuf definitions | BSD 3-Clause | [cpp/external/katagocoreml/vendor/mlmodel/format/LICENSE.txt](cpp/external/katagocoreml/vendor/mlmodel/format/LICENSE.txt) |
| Apple coremltools MLModel/MILBlob 部分 | BSD 3-Clause | [cpp/external/katagocoreml/vendor/mlmodel/LICENSE.txt](cpp/external/katagocoreml/vendor/mlmodel/LICENSE.txt) |
| Apple ModelPackage 部分 | BSD 3-Clause | [cpp/external/katagocoreml/vendor/modelpackage/LICENSE.txt](cpp/external/katagocoreml/vendor/modelpackage/LICENSE.txt) |
| Apple Swift CMake modules | Apache License 2.0 with Runtime Library Exception | [cpp/external/macos/LICENSE](cpp/external/macos/LICENSE) |
| Mozilla CA certificate bundle | 来源与 MPL 2.0 说明 | [cpp/external/mozilla-cacerts/LICENSE](cpp/external/mozilla-cacerts/LICENSE) |
| TCLAP 1.2.5 | MIT；本树包含轻微修改说明 | [cpp/external/tclap-1.2.5/COPYING](cpp/external/tclap-1.2.5/COPYING)、[cpp/external/tclap-1.2.5/README](cpp/external/tclap-1.2.5/README) |
| KataGo Transformer 衍生的 PyTorch 模型部分 | MIT；作者与修改范围说明 | [python/katago/train/LICENSE_AND_AUTHORS](python/katago/train/LICENSE_AND_AUTHORS) |
| Muon optimizer 衍生代码 | MIT | [python/muon/LICENSE](python/muon/LICENSE)、[python/muon/README.md](python/muon/README.md) |

## 文件内嵌归属

以下内容的许可证或来源说明直接保存在源码中：

| 内容 | 归属位置 |
| --- | --- |
| nlohmann/json 3.8.0 | [cpp/external/nlohmann_json/json.hpp](cpp/external/nlohmann_json/json.hpp) 文件头内的 MIT 文本与版权声明。 |
| Aaron D. Gifford 的 SHA-2 实现及 David J Wu 的接口修改 | [cpp/core/sha2.cpp](cpp/core/sha2.cpp) 文件头内的原始许可和修改说明。 |
| Michi GTP 实现的改编部分 | [python/play.py](python/play.py) 中的来源和 MIT 许可证链接说明。 |

这些文件内嵌声明在重构、格式化、代码生成或 vendoring 更新中不得被意外删除。具体保留义务以各声明的原文为准。

## 基线审计说明

### half 版本文字差异

根 [LICENSE](LICENSE) 的依赖说明仍写有 `half-2.1.0`，但冻结基线中的实际目录、README 和许可证路径是 `cpp/external/half-2.2.0`，其 README 标识版本 2.2.0。

- **FROZEN：** 本索引按实际基线树记录为 2.2.0。
- **AUDIT-BLOCKED：** 是否以及如何修正根 LICENSE 的历史说明文字，需要单独的法律与来源审阅；启动工作不得静默改写上游许可证文件。

### sgfmill

根 [LICENSE](LICENSE) 明确提到 `sgfmill`，仓库中的多个 Python 文件也导入它，但 KataGo `v1.16.5` 树中没有 vendored `sgfmill` 源码或独立的 `sgfmill` 许可证文件。

- **AUDIT-BLOCKED：** 在未来创建 Python 包清单、锁文件、容器或发行物前，必须核对实际采用的 sgfmill 版本、获取渠道、许可证文本和对应发行要求。
- 当前启动工作不新增包清单或依赖，因此本文件只记录缺口，不选择或锁定版本。

### 上游测试模型与数据

KataGo 基线已包含用于测试的小型模型和数据。相关说明位于 [cpp/tests/models/README.txt](cpp/tests/models/README.txt)，katagocoreml 的模型归属说明位于 [cpp/external/katagocoreml/NOTICE](cpp/external/katagocoreml/NOTICE)。

- **FROZEN：** 当前文档与边界启动工作不新增、替换或重新打包任何 MutaGo 生产的模型、检查点或数据，也不创建发行物。
- 继承的上游测试资产仍是基线树的一部分；复制完整基线树时可能随树一并复制，其处理必须遵守原始归属和许可文本。不得把这些资产描述为 MutaGo 训练、发布或拥有的新模型。
- **AUDIT-BLOCKED：** 未来若单独分发、重新打包或替换模型、检查点或数据，必须逐项记录来源、版本、许可证、训练数据政策、哈希、发行范围和审计结果。

## 维护规则

新增、升级、删除或重新打包第三方内容时，维护者应：

1. 识别实际包含内容及其原始许可证、版权和 notice；
2. 更新本索引中的真实路径、版本、来源与本地修改；
3. 检查 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md) 是否仍准确；
4. 保持源文件内嵌声明和独立许可文件可追溯；
5. 根据拟发行物的实际组成审计依赖、模型、数据和二进制打包；
6. 在证据齐备前把相应发行状态标记为 **AUDIT-BLOCKED**。

本索引只帮助定位权威文本，不创建独立于原始许可证的新条件。

## English Summary

This file indexes third-party attribution locations verified in the full-history KataGo v1.16.5 baseline at `ba938676d7f42d70950b3a535af2466fb642008c`. Original license, NOTICE, COPYING, and embedded source headers remain authoritative; this index adds no license conditions. The vendored half directory is version 2.2.0 although the inherited root LICENSE says 2.1.0, and changing that inherited wording remains audit-blocked. sgfmill is referenced but not vendored, so future packaging must audit the exact dependency and applicable terms. The bootstrap adds no new, replacement, or repackaged MutaGo-produced models, checkpoints, or data and creates no release. Existing upstream test assets remain baseline content and may accompany copies of the tree under their original attribution and license terms; they are not MutaGo-produced models. Future dependency, model, data, or binary distributions require release-scope provenance and license review.