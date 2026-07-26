# 来源、归属与非背书说明

> 本文件用于汇总项目来源、归属位置和维护审计入口，不是许可证文本，也不替代法律意见。适用的权利与义务以 [LICENSE](LICENSE)、所含组件的原始许可证、NOTICE、COPYING 和文件内声明为准。本文件不增加、删减或修改那些条款。

## 项目来源

MutaGo 是从 [KataGo](https://github.com/lightvector/KataGo) 演进的独立下游项目。冻结的上游基线为 KataGo stable `v1.16.5`，提交 `ba938676d7f42d70950b3a535af2466fb642008c`；完整历史和同步政策见 [UPSTREAM.md](UPSTREAM.md)。

基线根 README 的不可变来源快照保存在 [docs/upstream/KataGo-README-v1.16.5.md](docs/upstream/KataGo-README-v1.16.5.md)。该快照用于审计，不是 MutaGo 当前项目入口。

## 上游版权与贡献者

仓库保留的 KataGo 内容受 [LICENSE](LICENSE) 及其中引用的独立组件许可证约束。根许可证记录：

> Copyright 2025 David J Wu ("lightvector") and/or other authors of the content in this repository.

继承的作者、直接贡献者和间接贡献者信息见 [CONTRIBUTORS](CONTRIBUTORS)。各文件中已有的版权头、来源说明和独立许可文本仍是对应内容的重要归属记录。

MutaGo 后续新增或修改内容的版权与作者身份以实际贡献和文件记录为准；其许可适用范围由根 [LICENSE](LICENSE) 及任何明确的文件或组件级许可证决定。

## 第三方内容

基线树包含 vendored 库、外部来源代码、证书集合、测试资产以及具有独立许可证或归属说明的内容。经基线树核验的入口列在 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

- 原始许可证、NOTICE、COPYING 和文件内嵌版权头是权威文本；本文件与索引都不替代它们。
- 当前文档与边界启动工作不新增、替换或重新打包 MutaGo 模型、检查点或数据，也不创建发行物。基线中已有的测试模型和数据保持其上游来源与原始说明。
- 未来若加入新依赖、新模型、新数据或重新打包第三方内容，应根据实际发行范围核对来源、版本、许可证和所需归属；审计未完成时保持 **AUDIT-BLOCKED**。

## 发行包维护清单

当 MutaGo 维护者未来制作完整源代码包、二进制包或其他发行物时，应按发行物实际包含的内容逐项审计，并在适用的原始许可条款要求范围内保留相应的：

- [LICENSE](LICENSE) 与相关版权、许可文本；
- [CONTRIBUTORS](CONTRIBUTORS) 中与所含内容有关的来源记录；
- 对应第三方组件的原始许可证、NOTICE、COPYING 或文件内声明；
- 用于解释项目来源和第三方路径的本文件及 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，如果发行包选择包含这些维护索引。

以上是项目的发行审计清单，不是对所有复制、修改或分发行为新增的许可条件。某一文件是否需要随具体发行物提供、以何种形式提供，只能依据实际包含内容及其原始许可证判断。

## 名称与非背书

KataGo、相关项目名称及作者姓名仅用于准确说明来源和归属。MutaGo 是独立项目，不代表、隶属于或获得 KataGo、David J Wu、KataGo 贡献者、其雇主或任何相关组织的认可、赞助、认证、支持或维护承诺。

本说明不主张获得任何商标、商品名或背书权利。对名称或标识的具体使用，应另行核对适用规则。

## English Summary

MutaGo is an independent downstream of KataGo stable v1.16.5 at commit `ba938676d7f42d70950b3a535af2466fb642008c`. This notice is an informational provenance and audit index; it does not replace, expand, reduce, or modify the root LICENSE or any component license, NOTICE, COPYING file, or embedded attribution. Upstream copyright and contributor records remain available in [LICENSE](LICENSE) and [CONTRIBUTORS](CONTRIBUTORS), with third-party locations indexed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Future release bundles must be audited according to their actual contents and the original applicable license terms. No endorsement, sponsorship, certification, support, or maintenance by KataGo or its contributors is claimed.