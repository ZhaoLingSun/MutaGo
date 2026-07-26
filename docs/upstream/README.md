# 上游文档快照

本目录保存用于来源审计的不可变上游文档快照，不是 MutaGo 当前文档的正文入口。

## 当前快照

- 文件：[KataGo-README-v1.16.5.md](KataGo-README-v1.16.5.md)
- 来源：KataGo 根 `README.md`
- 上游稳定版本：`v1.16.5`
- 上游提交：`ba938676d7f42d70950b3a535af2466fb642008c`
- 状态：**FROZEN**

该文件与冻结基线提交中的根 README 内容相同，只用于保存上游项目在分化点的原始介绍、使用说明和链接上下文。MutaGo 当前项目入口是 [../../README.md](../../README.md)。

## 不可变规则

- **FROZEN：** 不修改快照正文，不修正拼写，不更新年份，不加入 MutaGo 说明。
- **FROZEN：** 不修复因文件移动而失效或改变含义的相对链接；修复会破坏快照属性。
- 阅读快照中的相对链接时，应把它们解释为相对于 KataGo `v1.16.5` 仓库根目录，而不是当前 `docs/upstream/` 目录。
- 需要查看快照所指的仓库文件时，应从当前继承树根目录导航，或查看上游同一提交；不要通过编辑快照来重定向链接。
- 未来切换上游基线时，不覆盖现有文件；应新增带版本号的快照，并在 [../../UPSTREAM.md](../../UPSTREAM.md) 中记录新的来源版本和提交。

## 完整性与验证

快照的用途是提供可审计的历史文本，因此任何格式化、换行转换、链接重写、拼写修复或自动文档迁移都会使其失去预期属性。维护工具应把版本化快照排除在自动改写范围之外。

若完整性检查发现差异，应以记录的 KataGo 提交 `ba938676d7f42d70950b3a535af2466fb642008c` 中根 `README.md` 为来源恢复，而不是手工拼接内容。恢复工作必须单独审阅并记录原因。

## 归属与用途

快照仍是继承的 KataGo 上游内容，适用 [../../LICENSE](../../LICENSE)、[../../CONTRIBUTORS](../../CONTRIBUTORS) 及原文件中的归属。保存该快照不表示 KataGo、其作者或贡献者认可、赞助或维护 MutaGo。

本目录不得用来放置 MutaGo 当前规则规范、架构决定、变更日志或发布说明；这些内容必须进入其当前文档位置。当前设计入口见 [../设计文档/README.md](../设计文档/README.md)。

## English Summary

This directory stores immutable provenance snapshots of upstream documentation. [KataGo-README-v1.16.5.md](KataGo-README-v1.16.5.md) reproduces the KataGo root README from stable v1.16.5 at commit `ba938676d7f42d70950b3a535af2466fb642008c`. Do not edit, reformat, or repair moved relative links in the snapshot; interpret those links relative to the original upstream repository root. Future baselines must add new versioned snapshots rather than overwrite this one. Restore any integrity failure from the recorded upstream commit, with separate review. The snapshot retains upstream licensing and attribution and does not imply endorsement or maintenance of MutaGo.