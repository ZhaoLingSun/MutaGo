# AGENTS.md

本文件是 MutaGo 仓库的规范性代理治理政策。任何人工或自动化代理在分析、编辑、生成、测试、提交、同步上游或准备发行物前，都必须遵守本文件。

## 1. 适用范围、优先级与规范入口

- **FROZEN：** 本文件是仓库级代理政策的规范来源。[CLAUDE.md](CLAUDE.md) 只提供实用入口，不得放宽或替代本文件。
- **FROZEN：** [设计文档索引](docs/设计文档/README.md)列出设计决定及其状态；[坍缩围棋规则](docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)是玩法语义的规范来源；[输入特征 ABI](docs/设计文档/04-输入特征ABI-V9.md)和[测试与一致性门槛](docs/设计文档/06-测试与一致性门槛.md)分别约束 ABI 与验收顺序。
- **FROZEN：** 规则文件名中的 `draft` 不表示已列出的玩法语义仍可自由修改。那些玩法语义已经冻结；真正未决的身份、编码、协议和初始 PSK 播种事项必须明确标为 **UNFROZEN**。
- 子目录未来可以添加更严格的 `AGENTS.md`，但不能放宽这里的权威边界、测试门槛、Git 安全纪律、上游保留或法律义务。
- 如普通说明与明确标记为 **FROZEN** 的决定冲突，以冻结决定和更具体但不放宽约束的政策为准。

## 2. 决定状态词

- **FROZEN**：决定已经生效并具有约束力。变更必须经过明确设计决定、兼容性评估、必要的版本变更和相应测试。
- **UNFROZEN**：事项尚未决定。不得猜测、静默补全、用占位值伪装完成，或在公共接口和持久化数据中提前固化。
- **AUDIT-BLOCKED**：缺少许可证、来源、安全、兼容性或发布证据；审计完成前不得发行或宣称完成。

未标状态的背景说明不能覆盖带状态的决定。

## 3. 项目基线与当前范围

- **FROZEN：** MutaGo 从 KataGo stable `v1.16.5`、提交 `ba938676d7f42d70950b3a535af2466fb642008c` 的完整树与完整 Git 历史开始分化。
- **FROZEN：** 首个规则集是 Collapse Go / 坍缩围棋，规范规则文档版本为 `0.1.0-draft`，其中列出的玩法语义已经冻结。
- **FROZEN：** Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN：** 公开 `rulesetId` 字面值、规范语义描述符的字段和规范化规则，以及初始空盘是否预先加入 PSK 历史。
- **AUDIT-BLOCKED：** 公开描述符 SHA-256；在最终描述符字节冻结并完成独立审计前保持未分配。
- `collapse-go` 只是仓库目录 slug 和候选名称，不是已分配的公开 `rulesetId`。
- **AUDIT-BLOCKED：** 在实现、测试、来源和许可证证据齐备前，任何正式发布、模型或数据分发，以及“规则实现完成”“兼容完成”或“门槛已通过”的声明。

当前启动工作只建立文档和仓库边界脚手架。不得借该范围夹带生产源码、包清单、依赖、schema 生成器、CI、模型、检查点、数据、构建产物、发布标签、release 或最终公开规则哈希。

## 4. 生产权威边界

### 4.1 C++：唯一生产规则与搜索权威

- **FROZEN：** C++ 是生产环境中规则和搜索的唯一权威。
- C++ 必须决定合法性、状态转移、提子、自杀与保护、局面同形禁着、当前行动者、结算、计分、终局状态、权威事件和回放结果，并为搜索提供权威游戏状态。
- 其他语言或进程不得建立可与 C++ 竞争的生产规则路径，也不得在 C++ 返回之后“修正”其语义结果。

### 4.2 Python：独立慢速预言机

- **FROZEN：** Python 是独立实现的慢速规则参考和差分预言机，不是生产规则引擎。
- Python 不得调用、绑定或复用 C++ 规则代码、生产 reducer 或其语义决定来生成预期结果。
- C++ 与 Python 只可共享冻结的数据 schema、格式定义和测试向量；决定合法性、提子、PSK、结算、计分与终局的实现路径必须独立。
- 如果 Python 的“预期结果”来自生产实现，差分测试无效，不能计入一致性门槛。

### 4.3 Node Gateway：薄编排层

- **FROZEN：** Node Gateway 仅负责进程监管、会话、WebSocket 路由、消息 envelope/schema 形状验证、持久化编排和背压。
- Gateway 不得计算、推断或修正规则合法性、提子、自杀与保护、PSK、结算、计分、当前行动者或终局状态。
- Gateway 可以拒绝结构错误或未知版本的消息，但语义合法性必须由 C++ 权威判断。

### 4.4 React + TypeScript Web：薄呈现层

- **FROZEN：** Web 客户端只渲染 C++ 提供的权威状态、合法着掩码、分析和结算轨迹，并提交用户意图。
- 客户端不得包含本地规则引擎，不得计算或推断合法性、提子、PSK、结算、计分、当前行动者或终局状态，也不得把预测 UI 状态提升为权威状态。
- 坐标布局、动画、格式化等纯展示变换可以本地执行，但不能改变语义。

## 5. 冻结的规则与 ABI 不变量

### 5.1 动作空间

动作 codec 是 kind-major：

- `p = 19*Y + X`；
- `a = 361*k + p`；
- `NORMAL`：`0..360`；
- `IMMORTAL`：`361..721`；
- `DOUBLE_START`：`722..1082`；
- `EIGHTWAY`：`1083..1443`；
- `PASS`：`1444`。

任何语言、schema、日志、模型输入管线、数据生成器或客户端映射都不得改用 point-major 或另一套编号。未知动作种类或 schema 版本必须 fail closed。

### 5.2 仅占子的 positional superko

- **FROZEN：** 官方坍缩围棋 PSK 语义只包含黑子占位和白子占位。
- PSK 不包含下一行动者、阶段、额度、特殊标记、账本或其他元数据。
- 每个得到稳定后状态的事件都把该稳定占位追加到 PSK 历史。
- 结算按全局从新到旧顺序每次弹出一个特殊事件；在能力移除、全盘重建、提子和确定性闭包完成后，追加该次稳定占位。
- tombstone/no-op 事件仍须保持可审计，并追加其稳定占位。
- 不稳定的重建或提子中间盘面不得进入 PSK 历史。
- **UNFROZEN：** 初始空盘是否预先写入 PSK 历史。任何实现或 fixture 都不得猜测该决定。
- PSK 的字段语义已经冻结；具体编码、哈希算法和存储布局仍可由后续设计决定，不得把“编码未定”误写成“PSK 包含哪些语义字段未定”。

## 6. 记录、公共身份与键空间必须分离

### 6.1 权威记录

- **FROZEN：** JSON event log 是对局的权威记录。
- **FROZEN：** 扩展 SGF 仅用于导入、导出和生态交换，可能有损，不是恢复数据库或规则裁决来源。
- 两者冲突时以 JSON event log 为准，并把冲突视为导入、导出或实现缺陷。
- 事件 schema、版本迁移和规范 JSON 编码的未决细节必须先形成设计决定；未知版本必须 fail closed。

### 6.2 四个独立语义域

必须严格区分以下四个域，分别命名、类型化、版本化和测试：

1. **公开规则身份**：冻结的结构为 `rulesetId + semantic version + SHA-256(canonical semantic descriptor)`；`rulesetId` 最终字面值与描述符字段/规范化为 **UNFROZEN / unassigned**，最终公开描述符 SHA-256 为 **AUDIT-BLOCKED / unassigned**。
2. **`PositionalSuperkoKey`**：只表达黑白占位，用于重复局面合法性；不能包含行动者或规则元数据。其二进制编码、哈希、碰撞处理和存储布局尚未冻结。
3. **`SearchKey`**：用于搜索节点复用，必须覆盖所有会改变搜索语义的状态；必需语义字段已由[输入特征 ABI](docs/设计文档/04-输入特征ABI-V9.md) §G.3 冻结，物理字节编码、digest/碰撞实现、生命周期、存储布局和上游集成仍待实现决策与审计。
4. **`NNCacheKey`**：用于神经网络结果缓存，必须与具体模型/checkpoint、Inputs V9、对称变换及影响网络输入或后处理的配置保持正确关联；必需语义字段已由[输入特征 ABI](docs/设计文档/04-输入特征ABI-V9.md) §G.4 冻结，缓存层级、物理编码、digest/碰撞实现、淘汰/生命周期、存储布局和上游集成仍未冻结。

不得因为当前实现的若干字节碰巧相同而复用类型、命名空间、哈希身份、持久化字段或碰撞假设。公开规则身份也不得被任何运行时缓存键替代。

## 7. Schema 与生成物纪律

对任何公共 schema 或生成代码，必须遵守：

1. 先确定并编辑声明为权威来源的 schema；生成文件不是规范来源。
2. 只通过仓库声明的生成器重新生成输出，禁止手工编辑生成文件。
3. schema 版本、生成器版本和兼容策略必须可审计；未知版本在 C++、Python、Gateway 和 Web 边界一律 fail closed。
4. schema 源与受影响的生成输出必须在同一变更中更新和验证，不能只提交一侧。
5. 如果任务要求暂存，必须用明确列出的路径同时暂存 schema 源和对应生成物；禁止宽泛暂存。
6. 尚未存在或尚未冻结的生成器、schema 字段和规范化规则不得由代理自行发明。

当前文档启动任务不新增 package manifest、依赖或 schema 生成器。

## 8. 测试门槛与顺序

### 8.1 早期规则门槛：`GATE-RULE-1M`

在接入 MutaGo 搜索、生产玩法协议、Gateway/Web 产品路径、自博弈或训练数据生产者之前，必须完成：

- 至少 **1,000,000** 个可复现的合法与非法原子动作比较；
- C++ 生产规则实现与独立 Python 预言机逐步比较合法性、稳定后状态、提子、PSK、行动者、事件、结算和终局结果；
- **零个可复现的语义差异**。

发现差异时必须保存最小复现、随机种子、动作前缀和双方输出；在差异解释并修复前，门槛保持失败。不得降低比较范围、过滤非法动作或用生产实现生成预期值来制造“零差异”。

### 8.2 必需测试族

规则与状态实现至少必须覆盖：

- 冻结规则和动作 codec 的 golden fixtures；
- 合法与非法动作的随机差分测试及属性测试；
- 每个原子动作和结算步骤的 undo/redo，要求状态、历史、四个身份/键域及权威事件精确恢复；
- JSON event log 的重放、恢复与确定性检查；
- D4 旋转/反射变换下动作、状态、合法着掩码、PSK 和结果的 metamorphic 测试；
- occupancy-only PSK、稳定后状态追加、重复局面和未决初始播种边界的专项测试；
- 结算的全局从新到旧顺序、逐事件 pop、全盘重建、同时移除所有零气且无保护棋块、确定性闭包、tombstone/no-op 和稳定状态历史追加测试；
- C++ 规则、回放、undo/redo 和结算路径的 ASan 与 UBSan 运行；
- 搜索接入后的搜索一致性与状态恢复测试；
- Model V19、Inputs V9、Training Schema V1、Action Schema V1、D4、推理和训练数据 ABI 测试；
- Gateway/Web 端到端测试，证明它们只消费权威结果而不包含第二套规则计算。

不稳定重建或提子中间盘面进入 PSK、D4 映射越界、undo 后 key/history 不一致、sanitizer 报错或可复现差分都属于阻断问题。

### 8.3 后续生产门槛：`GATE-PROD`

`GATE-RULE-1M` 通过后，仍需单独完成搜索、协议、持久化恢复、Model V19、Inputs V9、Training Schema V1、D4、回放、自博弈、推理、Gateway/Web、来源、许可证和发布审计。早期规则门槛不能替代后续生产/训练门槛。

只有在证据实际生成、可重放并经审阅后，才可声明相应门槛通过。

## 9. 变更与 Git 安全纪律

进行任何工作时：

1. 先查看工作树状态和现有 diff，识别用户或其他任务的未提交变更。
2. 阅读本文件及与任务相关的冻结设计文档，明确允许路径、权威层和决定状态。
3. 只修改任务明确授权的路径；不得覆盖、清理或顺手修复无关变更。
4. 对 **UNFROZEN** 事项先补获授权的设计决定，不得直接编码猜测。
5. 先运行最小相关测试，再按影响范围运行更广门槛；未运行的测试必须如实说明。
6. 结束前检查实际 diff、路径范围、链接、生成物和测试结果。

Git 操作必须遵守：

- 默认不暂存、不提交、不推送；只有任务明确要求时才执行相应操作。
- 暂存时必须使用明确命名的路径，例如 `git add -- path/to/a path/to/b`。
- 禁止使用 `git add -A`、`git add .`、`git add -u` 或其他可能夹带无关内容的宽泛暂存方式。
- 暂存后必须检查 `git diff --cached --stat` 和 `git diff --cached -- <明确路径>`。
- 不得把用户、其他代理或并行任务的变更纳入提交。
- 禁止 force push、强制更新远端分支、改写共享历史、重置或变基掉他人提交。不得用历史重写掩盖错误；应通过新的可审计提交修正。

## 10. 上游、许可证、notice 与非背书

- 保留 KataGo 的完整祖先历史、[LICENSE](LICENSE)、[CONTRIBUTORS](CONTRIBUTORS)、vendored notice、文件内嵌版权头和可审计来源。
- 上游同步必须遵守 [UPSTREAM.md](UPSTREAM.md)：merge 可以保留原始提交的祖先关系；cherry-pick 会创建新提交，必须记录原始 SHA，不能声称保留原提交祖先关系。
- 不得删除、合并、改写或“清理”第三方许可证、NOTICE、COPYING 或文件内嵌归属声明。
- 归属说明见 [NOTICE.md](NOTICE.md)，第三方权威路径索引见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。这些索引不替代原许可证文本，也不得被解释为新增许可证条件。
- 新依赖、vendored 代码、模型、检查点、数据集或重新打包内容在进入发行物前，必须完成实际范围的来源和许可证审计；证据缺失时保持 **AUDIT-BLOCKED**。
- 不得暗示 KataGo、David J Wu、KataGo 贡献者、其雇主或任何相关组织认可、赞助、认证、支持或维护 MutaGo。

## 11. 文档与完成声明

- 项目治理和设计文档必须有完整中文正文，并以 `## English Summary` 提供英文摘要。
- 仓库内部链接使用仓库相对路径。
- 明确区分 **FROZEN**、**UNFROZEN** 和 **AUDIT-BLOCKED**；不得把未决事项写成既定事实，也不得把冻结玩法重新写成未决。
- 每个文件应自包含，不能依赖聊天记录解释目的、权威性或限制。
- 不得声称不存在的实现、测试结果、模型、schema、生成器、公共哈希、标签、release 或审计结论。
- 只有在代码、测试、diff 和审计证据与声明一致时，任务才可报告完成。

## English Summary

This is the canonical repository agent policy. MutaGo preserves the full-history KataGo v1.16.5 baseline at `ba938676d7f42d70950b3a535af2466fb642008c`. Gameplay semantics in the `0.1.0-draft` rules document are frozen. C++ is the sole production rules/search authority; Python is an independently implemented slow oracle; Node Gateway and React/TypeScript perform no rules computation. The frozen ABI is Model V19, Inputs V9, Training Schema V1, and Action Schema V1 with kind-major action encoding. Public rules identity, occupancy-only PSK, search keys, and NN-cache keys are four separate domains. Every stable post-state enters PSK history, including each settlement event pop after deterministic closure; unstable intermediate boards do not. The initial empty-board PSK seed remains unresolved. Before MutaGo search or product integration, at least one million reproducible legal/illegal atomic actions must produce zero C++/Python semantic differences, with sanitizer, undo/redo, D4, PSK, settlement, and replay coverage. Generated files must come from canonical schemas and declared generators. Stage only explicit named paths; never force-push or rewrite shared history. Preserve upstream attribution, licenses, notices, auditability, and non-endorsement.