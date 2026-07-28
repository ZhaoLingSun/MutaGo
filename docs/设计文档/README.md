# MutaGo 设计文档

| 项目 | 值 |
|---|---|
| 上游基线 | KataGo stable `v1.16.5`，提交 `ba938676d7f42d70950b3a535af2466fb642008c` |
| 首个规则集 | Collapse Go / 坍缩围棋 |
| 规则版本 | `0.1.0-draft` |
| 规则集目录 / slug | `rulesets/collapse-go/` / `collapse-go`；目录 slug 不是公开 `rulesetId` 的别名 |
| 公开规则身份 | **FROZEN**：`mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899` |
| 规范描述符 | `rulesets/collapse-go/descriptor-v0.1.0-draft.json`；`rfc8785-jcs-ascii-safe-integer-v1`；14973 个规范 UTF-8 字节 |
| 当前里程碑 | M0 可执行合同与公开身份；不是完整规则引擎或产品实现 |

> **[FROZEN]** MutaGo 是基于 KataGo 完整历史继续开发的派生项目。历史首个提交只建立文档、目录边界与治理约束；后续获准里程碑可以加入源码。当前 M0 已冻结并实现可执行合同、公开身份与中立向量，但不表示完整 Collapse Go reducer、模型、服务或客户端已经可用，也不表示 KataGo 上游认可或背书本项目。`0.1.0-draft` 是冻结的语义版本字符串，不能据此重新打开玩法、身份、初始 PSK、Action V1 或 MVP 死子策略。

## 1. 本目录的职责

本目录固定 MutaGo 的设计基线、实施顺序和运行时权威边界。它回答三个问题：

1. 当前已经决定什么，哪些内容尚未决定；
2. 从 KataGo 基线演进到 MutaGo 的依赖顺序和验收闸门是什么；
3. C++、Python、Node 网关、React 客户端、事件日志、搜索和神经网络各自可以做什么，禁止做什么。

本目录是索引，不替代已经存在的规则、ABI、协议与测试规范。发生冲突时按领域裁决：冻结的游戏玩法语义以[02-坍缩围棋规则-v0.1.0-draft.md](02-坍缩围棋规则-v0.1.0-draft.md)的中文正文为准；模型输入和 Action Schema ABI 以[04-输入特征ABI-V9.md](04-输入特征ABI-V9.md)为准；协议与版本化表示以[05-协议与Schema.md](05-协议与Schema.md)为准；[06-测试与一致性门槛.md](06-测试与一致性门槛.md)和[07-路线图与未决事项.md](07-路线图与未决事项.md)只能落实前述规范，不能改写它们。架构与实施边界随后依次参考[01-系统架构与权威边界.md](01-系统架构与权威边界.md)、[00-技术路线.md](00-技术路线.md)和本文。当前规范描述符、canonicalization profile、公开三元组、初始 PSK 第零项和 Action V1 envelope 已由 M0 制品固定；任何冲突都必须阻断实现或发布。

## 2. 决策状态词

- **FROZEN**：对 `0.1.0-draft` 已作出的决定。修改必须有显式设计记录，并评估语义版本、规则哈希、模式、测试向量、模型和兼容性的影响。
- **UNFROZEN**：尚未决定。实现、协议和文档不得把某个候选方案当作既成事实。
- **AUDIT-BLOCKED**：必须先完成指定的源码、张量、许可证或数据审计；不得凭记忆、相似性或占位表补齐。

未标注状态不等于默认冻结；规范性语句应就近标注或归入明确状态的章节。

## 3. 阅读顺序

1. **本文**：项目快照、术语、文档契约和首提交边界。
2. **[00-技术路线.md](00-技术路线.md)**：实施依赖、早期规则差分硬闸门、后续生产/训练准入与发行路线。
3. **[01-系统架构与权威边界.md](01-系统架构与权威边界.md)**：`GameState + VariantReducer`、事务闭包、键空间、事件流、进程与前端边界。
4. **[02-坍缩围棋规则-v0.1.0-draft.md](02-坍缩围棋规则-v0.1.0-draft.md)**：已经冻结的 Collapse Go 玩法语义与边界案例。
5. **[03-AI模型与训练设计.md](03-AI模型与训练设计.md)**：Model V19 的搜索、模型、迁移与训练设计。
6. **[04-输入特征ABI-V9.md](04-输入特征ABI-V9.md)**：Inputs V9、Training Schema V1 与 Action Schema V1 的精确冻结 ABI。
7. **[05-协议与Schema.md](05-协议与Schema.md)**：权威记录、协议边界与版本化 Schema。
8. **[06-测试与一致性门槛.md](06-测试与一致性门槛.md)**：规则差分、生产者准入、训练准入和发行测试。
9. **[07-路线图与未决事项.md](07-路线图与未决事项.md)**：跨阶段交付物、依赖和真实未决项。
10. **上游背景资料**：KataGo 的 [C++ 源码概览](../../cpp/README.md)、[Python 源码概览](../../python/README.md)、[图搜索说明](../GraphSearch.md)、[分析引擎协议](../Analysis_Engine.md)与[自对弈训练说明](../../SelfplayTraining.md)。这些资料解释基线，不自动成为 Collapse Go 的规则或协议。

## 4. `0.1.0-draft` 冻结快照

### 4.1 游戏与阶段

**[FROZEN]** 正式 v0.1 对局为空 19×19 平手棋：黑先，白贴目 7.5，中国式数子法，使用只比较黑白占据且不包含下一手玩家的 occupancy-only 位置超级劫（`PositionalSuperkoKey` / PSK），不设让子。9×9 与 13×13 仅为实验棋盘。这里的“暂定贴目”表示未来规则版本可以重新审议，不表示同一规则身份下可任意漂移。

阈值为：

\[
T(N)=\left\lfloor\frac{150N^2+180}{361}\right\rfloor,
\quad T(9)=34,\ T(13)=70,\ T(19)=150.
\]

每次实际落子和每次 `PASS` 都是一个全局原子行动；Double-Move 的起手与强制续手分别计数。特殊能力从行动 1 起可用。Immortal 与 Eightway 可在行动 `T` 使用；Double 起手最晚为 `T-1`，保证续手可以完整发生。行动 `T` 必须先完整提交，再触发能力结算，并成为最新事件。

每位玩家正式配额向量为 Immortal、Double-Move、Eightway 各 1，即 `1/1/1`。合法特殊落子提交时永久消耗配额；被提走不返还，未用配额在能力结算后失效且无补偿。任何与官方 `1/1/1` 不同的完整配额向量都属于不同规则语义，必须进入不同规范化描述符并使用不同规则哈希；若完整语义完全相同，不能只因运行模式名为“experimental”而制造不同身份。

能力结算由达到 `T` 或 `T` 前连续两次 `PASS` 触发；后者不是终局计分。结算按全局从新到旧逐个停用特殊事件。每个事件完成能力移除、重建和提子并到达稳定闭包后，该稳定黑白占据必须追加到 occupancy-only PSK 历史；重建或提子过程中的不稳定中间棋盘不得进入 PSK。结算结束后只允许普通围棋行动，并重置停着连计；玩家需要再次连续两次 `PASS`，随后直接对当前稳定盘面计分。MVP 不启用死子协商移除或争议恢复。认输和游戏语义超时只在暴露的稳定决策边界接受：若先于候选动作提交则立即终局且不启动结算或计分；动作一旦提交，其触发的完整结算不可中断，下一命令边界在结算出口之后。请求/传输超时、背压、断线、取消和进程故障不得合成游戏 `TIMEOUT` 或胜负。

### 4.2 三种能力

- **Immortal**：存活锚点动态保护其当前混合连通的同色整组。受保护的零气组可以存在，也可接入普通同色棋子；保护可沿存活 Eightway 连边传播。分裂后，仅含存活 Immortal 锚点的分量继续受保护。Immortal 可以落入真眼并破坏普通双活眼结构。
- **Double-Move**：起手放置带审计身份的标记棋子，随后同一玩家恰好再执行一次 `NORMAL` 或 `PASS`。`DOUBLE_START` 起手和 `NORMAL` 续着分别执行完整落子、提子、自杀/保护与 PSK 合法性事务。`PASS` 续着只验证 phase、actor 和续着义务；它不落子、不提子、不检查自杀，也不执行 PSK 重复拒绝，但仍增加 `A` 与停着连计、产生动作事件、清除 pending Double、追加未改变的稳定占据，并在完整提交后把行动权交给对手；若触发结算，该对手保存为 `handoffActor`，结算后仍由其行动。能力在合法起手提交时消耗；标记保留到能力结算，Double 账本项在结算时为机械无操作。
- **Eightway**：只有存活 Eightway 锚点使用 N8 接口参与同色连接与气的贡献；普通棋子使用 N4。同色连接在任一端为存活 Eightway 时按无向边处理。整组气为成员接口的去重并集；对角肩位不切断连边，异色棋子永不连接，占据点不是气。

### 4.3 权威与记录

**[FROZEN]**

- C++ 是唯一生产规则与搜索权威。
- Python 规则实现是独立编写的慢速参考与差分判定器，不进入在线权威路径，也不得通过绑定或共享 reducer 伪造“独立”。
- Node 网关只负责进程、会话、WebSocket、模式校验、持久化编排和背压；它不计算合法性、提子、PSK、结算、当前行动者或终局。
- React + TypeScript 客户端只渲染 C++ 权威状态、合法行动掩码与结算轨迹；它不推导任何规则结果。
- JSON 事件日志是权威记录；扩展 SGF 只用于交换，不是恢复或裁决依据。

公共不可变规则身份固定为 `rulesetId + semanticVersion + SHA-256(canonicalSemanticDescriptor)`，当前三元组为 `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`。规范描述符是 [`rulesets/collapse-go/descriptor-v0.1.0-draft.json`](../../rulesets/collapse-go/descriptor-v0.1.0-draft.json)，采用 `rfc8785-jcs-ascii-safe-integer-v1` 并产生 14973 个规范 UTF-8 字节。目录名和内部 variant/运行标签不构成身份，也不得替代任一三元组字段。

位置超级劫键、搜索键和神经网络缓存键是三种不同投影：PSK 只看黑白占据；搜索键必须区分所有会改变未来合法行动或结果的状态；NN 缓存键绑定具体模型/checkpoint、Inputs V9、实际编码输入、对称与影响推理的配置。SearchKey 与 NNCacheKey 的必需语义字段已由[04-输入特征ABI-V9.md](04-输入特征ABI-V9.md) §G.3–G.4 冻结；仍未冻结的是物理字节编码、digest/hash 与碰撞实现、缓存层级、淘汰/生命周期、存储布局和上游集成。它们都不是公共规则身份的替代品。

### 4.4 搜索与模型目标

**[FROZEN]** 模型固定使用 19×19 画布；9×9、13×13、19×19 的嵌入偏移分别为 `(5,5)`、`(3,3)`、`(0,0)`，D4 变换围绕画布中心 `(9,9)`。Action Schema V1 使用 kind-major 编码：令 `k=0,1,2,3` 分别表示 `NORMAL`、`IMMORTAL`、`DOUBLE_START`、`EIGHTWAY`，画布点索引为 `p∈[0,360]`，则 `a=361*k+p`；对应区间为 `0..360`、`361..721`、`722..1082`、`1083..1443`，`PASS=1444`。canonical Action V1 wire envelope 恰含 `schemaVersion`、`actionId`、`kind`，坐标由 ID 导出，冗余坐标或未知字段拒绝。模型始终输出 1445 个槽位，环境另行给出精确合法掩码。

Double 使用两个 MCTS 决策节点，起手后的子节点仍由同一玩家行动，续手只开放 `NORMAL/PASS`；能力结算不产生 MCTS 节点。网络输出相对当前玩家，在叶节点只转换一次为 KataGo 白方为正的搜索值；禁止按深度奇偶翻转。白方最大化 `Q`，黑方最大化 `-Q`。

目标契约为 Model V19、Inputs V9（恰好 38 个空间特征和 67 个全局特征）、Training Schema V1、Action Schema V1。精确输入索引、动作布局、合法掩码、训练数组和迁移不变量已经由[04-输入特征ABI-V9.md](04-输入特征ABI-V9.md)冻结；实现必须逐项遵守，不能在概览或代码中另造布局。上游 22 个空间特征、19 个全局特征及 `G18` 必须按该 ABI 显式保留和映射。

## 5. 仓库边界

以下路径表示长期所有权，不表示首提交已有实现：

| 路径 | 责任 |
|---|---|
| `cpp/` | 生产规则、搜索、特征生成、推理和权威事件生成；保留 KataGo 源码布局 |
| `python/` | 独立规则 oracle，以及训练、迁移、验证工具；不拥有在线规则权威 |
| `rulesets/collapse-go/` | 规范化描述符、规则文本、示例和版本身份 |
| `schemas/` | 行动、事件、状态、轨迹、协议和训练模式的版本化定义 |
| `services/gateway/` | 薄 Node 网关 |
| `apps/web/` | React + TypeScript 权威状态客户端 |
| `tests/conformance/` | C++/Python 黄金向量与差分一致性 |
| `tests/end-to-end/` | 进程、会话、恢复、WebSocket 和客户端端到端验证 |

必须保留上游完整 Git 历史、[许可证](../../LICENSE)、[贡献者记录](../../CONTRIBUTORS)、`cpp/external/` 内的第三方声明和现有源码布局。任何 MutaGo 发布都必须清楚说明派生关系且不得暗示上游背书。

## 6. 仓库阶段摘要

历史 bootstrap 首提交只建立文档与边界；当前及后续源码按以下 M0–M10 顺序进入：

1. **M0：可执行合同与公开身份。** 规范描述符、源 Schema、向量、合同工具、C++ 合同类型和测试；不包含完整规则或产品实现。
2. **M1：上游集成审计。** 审计 KataGo 规则、搜索、NN、数据、撤销、缓存、来源和许可证接缝。
3. **M2：精确状态与生产 Schema 决策。** 冻结规则核心所需状态所有权，以及 M0 之外的命令、事件、快照、恢复和 SGF 合同。
4. **M3：C++ 规则核心与独立 Python oracle。** 分别实现同一冻结语义，尚不接入生产搜索、产品协议或数据 producer。
5. **M4：`GATE-RULE-1M`。** 至少一百万个可复现合法/非法候选原子行动零语义差异，并通过规则、重放、撤销和 sanitizer 门槛。
6. **M5：搜索集成。** 接入 typed action、实际 actor、精确 legal mask、settlement 原子后继和独立键域。
7. **M6：生产协议、Gateway 与 Web。** 建立最薄、可恢复且不复制规则的产品路径。
8. **M7：Model V19、Inputs V9、Training Schema V1 与数据 producer。** 实现模型/数据通路；M8 前样本仍隔离。
9. **M8：`GATE-PROD`。** 完成搜索、协议、持久化恢复、NN、D4、SGF、E2E、来源和发行准入。
10. **M9：分阶段训练与验证。** 只使用通过 M8 的生产者逐步扩大训练。
11. **M10：稳定 Beta 与社区发布。** 通过长期回归、兼容、恢复、负载和发布审计后才允许广泛分发。

完整依赖、退出条件和权威里程碑编号见[路线图与未决事项](07-路线图与未决事项.md)；[技术路线](00-技术路线.md)提供补充背景。

## 7. 历史首提交边界与当前 M0

**[FROZEN / HISTORICAL]** 仓库首个 bootstrap 提交只能包含文档与边界脚手架，当时不得包含：

- 任何 C++、Python、Node 或 React 源码变更；
- 包清单、锁文件、新依赖或模式生成器；
- CI 工作流或发布自动化；
- 模型、检查点、训练数据、自对弈数据或生成物；
- 编译产物、缓存或性能结果；
- 当时尚未分配的最终规则哈希、Git 标签、发行包或“已支持”声明。

当前 M0 已越过该历史 bootstrap：允许任务明确授权的规范描述符、源 Schema、合同工具、C++ 合同类型、向量、示例和测试源码。M0 仍不允许完整 C++ reducer、完整 Python oracle、搜索、神经网络、Gateway/Web 产品实现、模型、训练数据、标签或 release；后续源码按路线图与门槛进入。

## 8. 显式未决项

### UNFROZEN

- PSK、SearchKey 与 NNCacheKey 的物理字节编码、digest/碰撞实现和存储集成；
- M0 之外的事件/状态/轨迹/命令 envelope、帧格式、持久化后端与并发确认机制；Action V1 自身的 `schemaVersion`/`actionId`/`kind` envelope 已冻结；
- 扩展 SGF 的自定义属性映射；
- 未来语义版本是否增加死子提议/同意/争议恢复，以及时间控制和证据协议；当前 MVP 不启用该流程；
- 模型块内的归一化、激活、FFN、注意力偏置公式、损失权重和“低偏置”的数值；
- 部署、认证、限流、包管理器与日期承诺。

### AUDIT-BLOCKED

- 三个 donor 的逐张量清单及其与[04-输入特征ABI-V9.md](04-输入特征ABI-V9.md)迁移不变量的一致性证明；
- 在完成上游源码、导出格式和后端兼容审计前，任何 Model V19 已实现或跨后端兼容的声明。

## English Summary

MutaGo is a derivative project built from the full KataGo `v1.16.5` history at commit `ba938676d7f42d70950b3a535af2466fb642008c`. Its first ruleset is Collapse Go `0.1.0-draft`. The current M0 milestone provides executable contracts and a frozen public identity, not a complete playable engine, model, gateway, or release, and it does not imply upstream endorsement. Authorized source work is permitted after the historical bootstrap, subject to milestone scope and gates.

The frozen architecture has one production authority: C++. Python provides an independently implemented slow differential oracle. The Node gateway only orchestrates processes, sessions, schemas, persistence, and WebSockets. The React/TypeScript client only renders authoritative state, legal masks, and traces. The JSON event log is authoritative; extended SGF is interchange only.

The public immutable rules identity is `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`, computed from the 14,973-byte canonical descriptor. `collapse-go` is only a repository slug. Initial empty occupancy is ordered PSK history entry zero; every stable action/terminal state and every settlement-event closure is appended, while unstable intermediates are excluded. The MVP enables neither agreed dead-stone removal nor a dispute/recovery protocol. Resignation or game timeout terminates without settlement or scoring only when accepted at an exposed stable boundary before a candidate action commits; a committed action’s triggered settlement completes atomically before another command boundary is exposed. Operational timeouts and cancellation never synthesize game `TIMEOUT`.

Collapse Go uses a fixed 19×19 neural canvas with exactly 1445 kind-major actions: `NORMAL` 0–360, `IMMORTAL` 361–721, `DOUBLE_START` 722–1082, `EIGHTWAY` 1083–1443, and `PASS` 1444. Canonical Action V1 is a closed wire object containing exactly `schemaVersion`, `actionId`, and `kind`; coordinates are derived, and missing/unknown fields, unknown versions, redundant coordinates, and inconsistent `kind`/ID pairs fail closed. The target contracts are Model V19, Inputs V9 with exactly 38 spatial and 67 global features, Training Schema V1, and Action Schema V1.

The one-million-action zero-difference rule gate is an early prerequisite for search, protocol, gateway, and training-data producers. It is separate from the later production/training-readiness gate for feature parity, replay and self-play producers, inference backends, end-to-end recovery, and formal training-pool admission.

The original bootstrap commit had a documentation-only boundary. Current M0 may contain authorized contract source, schemas, tooling, vectors, examples, and tests, while full rules/product implementations, models, data, tags, and releases remain outside M0.
