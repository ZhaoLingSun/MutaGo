# MutaGo

MutaGo 是从 KataGo 完整历史演进的独立下游项目，目标是构建具有明确规则身份、可审计事件记录、独立差分预言机和薄平台边界的变体围棋引擎与平台。首个规则集是 **Collapse Go / 坍缩围棋**，规则文档版本为 `0.1.0-draft`。

> **当前阶段：M0 可执行契约。** 本仓库已经建立项目入口、治理政策、设计文档、上游来源与法律归属索引、目录职责边界，以及 Action V1、规则描述符、语义投影与一致性夹具的可执行 Schema、黄金向量和 C++/Python 合同测试；尚未实现完整坍缩围棋 reducer、搜索、产品或训练流水线，也不构成正式发布。

## 当前状态

| 事项 | 状态 | 说明 |
| --- | --- | --- |
| 上游基线 | **FROZEN** | KataGo stable `v1.16.5`，提交 `ba938676d7f42d70950b3a535af2466fb642008c`，保留完整 Git 历史。 |
| 坍缩围棋玩法语义 | **FROZEN** | [规则文档](docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)中明确列出的玩法语义已经冻结；文件名中的 `draft` 不会重新开放这些决定。 |
| 模型与数据 ABI | **FROZEN** | Model V19、Inputs V9、Training Schema V1、Action Schema V1。 |
| 生产实现 | 尚未完成 | M0 仅提供可执行契约、黄金向量和合同测试，不声称完整 C++ reducer、Python oracle、Gateway 或 Web 已经实现新规则。 |
| 公共规则身份 | **FROZEN** | `mutago.collapse-go + 0.1.0-draft + a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`。 |
| 规范语义描述符 | **FROZEN** | 使用 `rfc8785-jcs-ascii-safe-integer-v1` 产生 14,973 个规范 UTF-8 字节；字段、关闭式 Schema 和规范化约束由 M0 可执行合同固定。 |
| 正式发布 | **AUDIT-BLOCKED** | 必须先完成实现、一致性门槛以及许可证、模型和数据来源审计。 |

`collapse-go` 仍只是仓库目录 slug，不是公共身份；已分配的公共 `rulesetId` 是 `mutago.collapse-go`。内部 variant 枚举、目录名、Git SHA、模型 SHA、运行模式标签和示例值都不得替代上述公开身份三元组。

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

PSK 的字段语义已经冻结；初始空盘占据固定为历史第零项。仍未冻结的是运行时字节编码、哈希实现、碰撞处理和存储布局。

### 身份与键空间

以下四个语义域必须严格分离：

1. 公开规则身份；
2. `PositionalSuperkoKey`；
3. `SearchKey`；
4. `NNCacheKey`。

它们用途不同，不能因为某一阶段字段碰巧相同而复用类型、命名空间或持久化身份。公开规则身份已经冻结为 `mutago.collapse-go / 0.1.0-draft / a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`；PSK 的占位语义与初始空盘第零项已经冻结；SearchKey 与 NNCacheKey 的必需语义组成已经由 [docs/设计文档/04-输入特征ABI-V9.md](docs/设计文档/04-输入特征ABI-V9.md) §G.3–G.4 冻结。仍未冻结的是后三者的物理编码、digest/hash 与碰撞实现、缓存层级、淘汰/生命周期、存储布局和上游集成。

## 当前 M0 范围

当前里程碑在首个纯文档脚手架提交之上，新增并验证：

- MutaGo 项目落地页、代理治理、工具入口和冻结设计文档；
- Action V1、规则描述符、语义投影、一致性夹具与 mismatch bundle 的关闭式源 Schema；
- 公开规则描述符、规范化/动作/身份黄金向量和合同示例；
- 独立 Python 合同解析、受限 JCS、摘要与跨工件检查工具；
- C++ `GameAction`、`RulesetIdentity` 及接入上游 `runtests` 的跨语言合同测试；
- 上游基线、完整历史、不可变 README 快照、notice 与许可证索引。

M0 不包含完整规则 reducer、Python 慢速规则 oracle、typed-action 搜索、生产协议、Gateway/Web、Model V19 实现、自博弈、训练流水线、模型、检查点、训练数据、CI、发布标签或 release。上游基线中已有的测试模型和数据仍是继承资产，不是 MutaGo 新训练或发布的模型。

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

MutaGo is an independent, full-history downstream of KataGo stable v1.16.5 at commit `ba938676d7f42d70950b3a535af2466fb642008c`. M0 now provides executable source schemas, public descriptor and golden vectors, Python contract tooling, C++ Action/RulesetIdentity contracts, and cross-language tests; it does not claim a complete Collapse Go reducer, search/product stack, training pipeline, or release. C++ remains the sole production rules/search authority, Python will provide an independently implemented slow oracle, and Node/Web contain no rules computation. Model V19, Inputs V9, Training Schema V1, and the 1,445-way kind-major Action Schema V1 are frozen. The public identity is `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`; its restricted-JCS descriptor is 14,973 canonical UTF-8 bytes. Initial empty occupancy is PSK history entry zero. Public identity, PSK, SearchKey, and NNCacheKey remain strictly separate domains.