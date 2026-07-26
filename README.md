# MutaGo

MutaGo 是从 KataGo 完整历史演进的独立下游项目，目标是构建具有明确规则身份、可审计事件记录、独立差分预言机和薄平台边界的变体围棋引擎与平台。首个规则集是 **Collapse Go / 坍缩围棋**，规则文档版本为 `0.1.0-draft`。

> **当前阶段：文档与仓库边界脚手架。** 本仓库已经建立项目入口、治理政策、设计文档、上游来源与法律归属索引以及目录职责边界；尚未声称已经实现坍缩围棋，也不构成正式发布。

## 当前状态

| 事项 | 状态 | 说明 |
| --- | --- | --- |
| 上游基线 | **FROZEN** | KataGo stable `v1.16.5`，提交 `ba938676d7f42d70950b3a535af2466fb642008c`，保留完整 Git 历史。 |
| 坍缩围棋玩法语义 | **FROZEN** | [规则文档](docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)中明确列出的玩法语义已经冻结；文件名中的 `draft` 不会重新开放这些决定。 |
| 模型与数据 ABI | **FROZEN** | Model V19、Inputs V9、Training Schema V1、Action Schema V1。 |
| 生产实现 | 尚未完成 | 启动工作只建立文档和边界，不声称 C++、Python、Gateway 或 Web 已实现新规则。 |
| 公共规则身份结构 | **FROZEN** | `rulesetId + semantic version + SHA-256(canonical semantic descriptor)`。 |
| 公共规则身份设计项 | **UNFROZEN** | `rulesetId` 字面值、规范语义描述符的字段及其规范化规则尚未分配或冻结。 |
| 公开描述符 SHA-256 | **AUDIT-BLOCKED** | 在最终描述符字节冻结并完成独立审计前保持未分配，不得发布。 |
| 正式发布 | **AUDIT-BLOCKED** | 必须先完成实现、一致性门槛以及许可证、模型和数据来源审计。 |

`collapse-go` 目前只是仓库目录 slug 和候选名称，不是已经分配的公开 `rulesetId`。不得把候选字符串、占位符、文件哈希或实现哈希写成最终规则身份。

## 冻结的权威边界

- **C++** 是生产规则与搜索的唯一权威，负责合法性、状态转移、提子、局面同形禁着、当前行动者、结算、计分、终局状态以及权威事件与回放。
- **Python** 是独立实现的慢速参考与差分预言机；它不得调用、绑定或复用 C++ 规则实现来生成预期结果。
- **Node Gateway** 只负责进程监管、会话、WebSocket 路由、消息包与 schema 形状验证、持久化编排和背压，不计算规则语义。
- **React + TypeScript Web 客户端** 只渲染 C++ 提供的权威状态、合法着掩码、分析和结算轨迹并提交用户意图，不运行本地规则引擎。
- **JSON event log** 是对局的权威记录；扩展 SGF 只用于交换，可能有损，不能作为恢复或裁决来源。

完整政策见 [AGENTS.md](AGENTS.md)，设计文档入口见 [docs/设计文档/README.md](docs/设计文档/README.md)。

## 冻结的规则与 ABI 摘要

### 动作编码

动作空间采用 kind-major 编码：

- 点编号：`p = 19*Y + X`；
- 动作编号：`a = 361*k + p`；
- `NORMAL`：`0..360`；
- `IMMORTAL`：`361..721`；
- `DOUBLE_START`：`722..1082`；
- `EIGHTWAY`：`1083..1443`；
- `PASS`：`1444`。

完整输入与动作契约见 [docs/设计文档/04-输入特征ABI-V9.md](docs/设计文档/04-输入特征ABI-V9.md)。

### 局面同形禁着历史

官方坍缩围棋采用仅含占子的 positional superko：

- `PositionalSuperkoKey` 的语义只包含黑子占位与白子占位；
- 不包含下一行动者、阶段、额度、特殊标记、账本或其他元数据；
- 每个得到稳定后状态的事件都把该稳定占位追加到 PSK 历史；
- 结算时，每弹出一个特殊事件，都在能力移除、全盘重建、提子和确定性闭包完成后追加稳定占位；
- 不稳定的重建或提子中间盘面不进入 PSK 历史。

PSK 的字段语义已经冻结；其具体编码、哈希实现和存储布局仍未冻结。初始空盘是否预先写入 PSK 历史也仍是 **UNFROZEN**，实现不得猜测。

### 身份与键空间

以下四个语义域必须严格分离：

1. 公开规则身份；
2. `PositionalSuperkoKey`；
3. `SearchKey`；
4. `NNCacheKey`。

它们用途不同，不能因为某一阶段字段碰巧相同而复用类型、命名空间或持久化身份。公开规则身份的具体字面值仍未分配；PSK 的占位语义已冻结；SearchKey 与 NNCacheKey 的必需语义组成已经由 [docs/设计文档/04-输入特征ABI-V9.md](docs/设计文档/04-输入特征ABI-V9.md) §G.3–G.4 冻结，仍未冻结的是物理编码、digest/hash 与碰撞实现、缓存层级、淘汰/生命周期、存储布局和上游集成。

## 启动脚手架的范围

当前启动工作完整覆盖的是**文档与仓库边界脚手架**，包括：

- MutaGo 项目落地页、代理治理与工具入口；
- 冻结玩法、架构、ABI、测试门槛等设计文档及其索引；
- C++、Python、Gateway、Web、schema、规则集和测试目录的职责边界说明；
- 上游基线、完整历史、不可变 README 快照及同步政策；
- 项目 notice、第三方许可证与归属路径索引。

该脚手架不新增或修改生产规则源码、包清单、依赖、schema 生成器、CI、模型、检查点、数据、构建产物、发布标签、release 或最终公开规则哈希。上游基线中已有的测试模型和数据仍是继承资产，不是 MutaGo 新训练或发布的模型。

## 仓库导航

- [docs/设计文档/README.md](docs/设计文档/README.md)：设计文档索引与决定状态。
- [docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md](docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)：玩法语义已经冻结的规范规则。
- [docs/设计文档/04-输入特征ABI-V9.md](docs/设计文档/04-输入特征ABI-V9.md)：Model V19 / Inputs V9 / Training Schema V1 / Action Schema V1。
- [docs/设计文档/06-测试与一致性门槛.md](docs/设计文档/06-测试与一致性门槛.md)：早期百万动作零差异门槛与后续生产门槛。
- [AGENTS.md](AGENTS.md)：仓库的规范性代理治理政策。
- [CLAUDE.md](CLAUDE.md)：面向 Claude Code 的实用工作入口。
- [UPSTREAM.md](UPSTREAM.md)：上游来源、冻结基线与同步政策。
- [NOTICE.md](NOTICE.md)：来源、归属与非背书说明。
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：第三方许可证与 notice 路径索引。
- [docs/upstream/README.md](docs/upstream/README.md)：不可变上游文档快照说明。
- [LICENSE](LICENSE) 与 [CONTRIBUTORS](CONTRIBUTORS)：继承的许可证和贡献者记录。

## 上游与独立性

MutaGo 是独立的下游项目，不是 KataGo 的官方发行版。KataGo 的代码、历史、作者、许可证和第三方归属按 [UPSTREAM.md](UPSTREAM.md)、[NOTICE.md](NOTICE.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 与原始许可证文件保留。MutaGo 不声称获得 KataGo、David J Wu、KataGo 贡献者、其雇主或相关组织的认可、赞助、认证或维护承诺。

## English Summary

MutaGo is an independent, full-history downstream of KataGo stable v1.16.5 at commit `ba938676d7f42d70950b3a535af2466fb642008c`. This bootstrap establishes documentation, governance, provenance, legal-attribution indexes, and repository boundaries; it does not claim a Collapse Go implementation or release. The gameplay semantics in the `0.1.0-draft` rules document are frozen despite the word `draft`. C++ is the sole production rules/search authority, Python is an independently implemented slow oracle, and Node/Web contain no rules computation. The frozen stack is Model V19, Inputs V9, Training Schema V1, and Action Schema V1 with 1,445 kind-major actions. Positional superko contains black/white occupancy only, while public rules identity, PSK, search, and NN-cache domains remain distinct. The public `rulesetId` and canonical-descriptor fields/canonicalization are **UNFROZEN / unassigned**; the final public descriptor SHA-256 is **AUDIT-BLOCKED / unassigned**; initial empty-board PSK seeding is also unresolved. `collapse-go` is only a directory slug and candidate name.