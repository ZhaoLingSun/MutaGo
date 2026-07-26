# 上游来源与同步政策

本文记录 MutaGo 的上游来源、冻结基线、历史保留和后续同步政策。

## 上游身份

| 字段 | 值 | 状态 |
| --- | --- | --- |
| 上游项目 | [lightvector/KataGo](https://github.com/lightvector/KataGo) | **FROZEN** |
| 上游稳定版本 | `v1.16.5` | **FROZEN** |
| 上游提交 | `ba938676d7f42d70950b3a535af2466fb642008c` | **FROZEN** |
| MutaGo 起点 | 上述提交的完整树与完整 Git 历史 | **FROZEN** |

该提交对应 KataGo stable `v1.16.5` 标签。MutaGo 从这一分化点以新的下游提交继续演进。

## 历史与归属保留

- **FROZEN：** 保留 KataGo 的完整 Git 祖先历史；不得重新初始化、压平、伪造或删除上游来源。
- **FROZEN：** 保留上游 [LICENSE](LICENSE)、[CONTRIBUTORS](CONTRIBUTORS)、vendored notice、文件内嵌版权头和可审计来源信息。
- 不得改写上游提交的作者、时间、提交信息或归属，也不得把 MutaGo 修改伪装成原始 KataGo 内容。
- MutaGo 的修改应以新的、可审计的下游提交表达。
- 禁止用 force push、rebase、reset 或其他历史重写方式从共享历史中移除已记录的上游或下游来源。

## 上游 README 快照

基线根 README 的不可变快照保存在 [docs/upstream/KataGo-README-v1.16.5.md](docs/upstream/KataGo-README-v1.16.5.md)。

- **FROZEN：** 该文件与基线提交中的 KataGo 根 `README.md` 内容相同，只用于来源审计和历史阅读。
- 不得为了修复移动后失效的相对链接、更新年份或措辞、修正拼写或加入 MutaGo 说明而编辑快照。
- 快照中的相对链接应解释为相对于 KataGo `v1.16.5` 仓库根目录；详细阅读规则见 [docs/upstream/README.md](docs/upstream/README.md)。
- 未来采用新的上游基线时，不得覆盖既有快照；应新增带版本号的快照并记录精确来源提交。

## 后续同步政策

未来吸收 KataGo 变更时，必须先明确同步范围、来源提交和 MutaGo 适配边界，然后采用可审计流程：

1. 记录精确上游版本、提交 SHA 或提交范围。
2. **Merge：** 非 squash、非历史重写的 merge 可以使原始上游提交继续作为合并结果的祖先；应保留其作者与提交身份。
3. **Cherry-pick：** cherry-pick 会创建新的下游提交 ID，原始上游提交不会因此成为下游分支祖先。必须在提交说明或同步记录中写明每个原始 SHA 及对应关系，不能声称 cherry-pick 保留了原提交祖先关系。
4. **补丁或手工移植：** 仅在 merge/cherry-pick 不适用时使用，并记录原始 SHA、文件范围、偏离原因和本地修改；手工移植不能冒充完整上游同步。
5. 在变更说明中区分纯上游内容、MutaGo 适配和任何规则语义变化。冻结玩法语义不得通过普通上游同步被静默改变。
6. 重新检查 [LICENSE](LICENSE)、[CONTRIBUTORS](CONTRIBUTORS)、[NOTICE.md](NOTICE.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 以及受影响的第三方文件内声明。
7. 运行与受影响路径相匹配的构建、测试、回放和兼容性检查，并明确记录未运行项目。
8. 不覆盖既有版本化文档快照；需要时新增快照和相应索引项。

同步频率、未来选择哪些 KataGo 提交以及逐次冲突解决方案当前为 **UNFROZEN**，必须由每个同步任务单独审阅。无论采用何种方式，都不得 force push 或改写共享历史。

## 独立项目与非背书

- **FROZEN：** MutaGo 是独立下游项目，不是 KataGo 的官方发行版。
- MutaGo 的名称、规则、接口、发布和维护决定由 MutaGo 贡献者负责。
- KataGo 名称、仓库链接和作者信息仅用于准确说明来源与归属。
- 不得声称 KataGo、David J Wu、KataGo 贡献者、其雇主或任何相关组织认可、赞助、认证、支持或维护 MutaGo。

## English Summary

MutaGo is an independent, full-history downstream of KataGo stable v1.16.5 at commit `ba938676d7f42d70950b3a535af2466fb642008c`. Preserve upstream ancestry, authorship, licensing, contributor records, vendored notices, and embedded attribution. The versioned upstream README snapshot is immutable and provenance-only. A non-squash merge can preserve original upstream commits as ancestors; cherry-pick creates new commit IDs and does not make the source commits ancestors, so exact source SHAs and mappings must be recorded. Manual ports require equally explicit provenance. Never force-push or rewrite shared history, never silently change frozen MutaGo gameplay during an upstream sync, and never claim upstream endorsement.