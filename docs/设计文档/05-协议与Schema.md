# 05 — 协议、权威记录与 Schema

> **适用规则语义版本**：Collapse Go / 坍缩围棋 `0.1.0-draft`
>
> **规则语义状态**：**FROZEN**；M0 可执行合同已实现，完整生产 reducer、事件协议与产品路径尚未完成；`draft` 是冻结的语义版本字符串
>
> **上游基线**：KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`
>
> **ABI**：**Model V19 / Inputs V9 / Training Schema V1 / Action Schema V1**
>
> **公共身份状态 — FROZEN**：`rulesetId = mutago.collapse-go`，`semanticVersion = 0.1.0-draft`，规范描述符 lowercase SHA-256 为 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`
>
> **相关文档**：[规则规范](./02-坍缩围棋规则-v0.1.0-draft.md) · [输入特征 ABI V9](./04-输入特征ABI-V9.md) · [测试与一致性门槛](./06-测试与一致性门槛.md) · [路线图与未决事项](./07-路线图与未决事项.md)

本文使用以下决策状态：

- **FROZEN**：明确列出的语义或架构边界已经冻结。改变规则语义时，必须同时产生新的语义版本和新的规范描述符哈希；改变不兼容线格式时，必须提升相应 Schema 主版本。
- **UNFROZEN**：方向或责任边界已知，但字段名、物理类型、编码、封装、缓存、持久化或兼容细节尚未冻结。
- **AUDIT-BLOCKED**：必须先取得上游源码、模型、数据格式或独立规范化证据，不得凭实现便利补齐。

本文冻结协议语义边界，并记录 M0 已落地的字段级源 Schema、公开描述符与中立向量；它不宣称生产 reducer、权威事件持久化系统、网络服务或完整产品协议已经实现。内部 variant 枚举、`collapse-go` 目录 slug、运行标签、Git SHA 和模型 SHA 都不是公共规则身份。

## 1. 范围与权威边界

### 1.1 组件职责

| 组件 | 冻结职责 | 禁止事项 |
|---|---|---|
| C++ 引擎 | 唯一生产规则权威；裁决合法性、提子、自杀、位置超级劫键（`PositionalSuperkoKey` / PSK）、结算、计分、行动方、终局和搜索状态，并产生生产权威事件 | 不得把规则裁决委托给 Python、Node 或浏览器 |
| Python 参考实现 | 独立、慢速、可检查的差分 oracle；产生参考语义结果、预期事件或规范投影 | 不得调用、链接、翻译或复用 C++ 状态转移实现；不得成为生产回退引擎 |
| Node gateway | 进程、会话、WebSocket、Schema 编排、命令关联、重连与背压 | 不得计算合法性、提子、ko、结算、计分、行动方或终局 |
| React + TypeScript 客户端 | 渲染 C++ 发布的权威状态、派生合法行动、事件和结算轨迹 | 不得自行裁决规则；视觉预测必须明确非权威且可被权威状态覆盖 |

### 1.2 权威记录、精确状态与派生视图

- **FROZEN**：追加式 JSON 规则事件日志是对局的权威记录。给定相同的精确规则配置、初始条件和完整日志，C++ reducer 必须重放出相同的精确状态与结果。
- **FROZEN**：当前精确状态与事件日志是不同语义域。状态保存未来转移所需的精确信息和已提交日志位置；它不需要内嵌完整日志正文。
- **FROZEN**：快照、WebSocket 增量、搜索分析、UI 动画、legal mask 和扩展 SGF 都是派生物。派生物与权威日志重放冲突时，以 C++ 对日志的重放结果为准。
- **FROZEN**：`legalMask` 由 C++ 从精确状态确定性派生并单独输出，不是 `GameState` 的语义字段，也不是神经网络对规则的近似。若缓存，缓存必须绑定确切权威修订并在状态变化时失效。
- **FROZEN**：搜索分析、访问次数、策略概率、价值、所有权和遥测默认不进入规则事件日志；若未来保存，只能作为明确版本化的非规则附件。

## 2. 规则身份、版本和固定 ABI

### 2.1 公共规则身份

公共规则身份三元组冻结为：

```text
rulesetId:       mutago.collapse-go
semanticVersion: 0.1.0-draft
descriptorSha256: a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899
```

摘要输入是 [`rulesets/collapse-go/descriptor-v0.1.0-draft.json`](../../rulesets/collapse-go/descriptor-v0.1.0-draft.json) 按 `rfc8785-jcs-ascii-safe-integer-v1` profile 生成的规范 UTF-8 字节。规范字节长度固定为 `14973`，摘要编码固定为 lowercase SHA-256。

该 profile 是 RFC 8785/JCS 的受限子集，并与 descriptor validation 分层：

1. profile 只约束 JSON 词法、值域和规范字节，接受对象、数组、ASCII 字符串与键、布尔、`null` 和安全有符号整数；
2. 安全整数范围固定为 `[-9007199254740991, 9007199254740991]`；
3. 对象键按 UTF-16 code unit 字典序排序并输出 UTF-8；
4. profile 在规范化前拒绝重复键、浮点数、非 ASCII 字符串或键、不安全整数、非法 UTF-8 与非法 JSON 数字词法，但不识别 descriptor 字段语义；
5. 规范规则描述符还必须独立通过关闭式 `ruleset-descriptor-v1` Schema、描述符跨字段不变量和适用的跨制品绑定；未知描述符字段由这一层拒绝；
6. 独立 C++ 和 Python 实现必须产生完全相同的规范字节、字节长度与 lowercase digest。

身份边界冻结如下：

1. 内部 variant enum/ID、目录名 `collapse-go`、运行模式标签和棋盘/配额产品分类都不是公开 `rulesetId`，不得代替或改变公开身份。
2. 任何改变合法行动、状态转移、PSK、结算、计分、行动顺序、阈值或完整配额向量的配置，都必须产生新的语义版本、规范描述符和哈希。
3. 官方 Collapse Go 配置为 19×19、空盘、黑先、白贴 7.5 目、中国式面积计分、occupancy-only PSK、初始空盘占据为历史第零项，以及双方各 `1 Immortal / 1 Double-Move / 1 Eightway`。
4. 9×9 和 13×13 属于实验棋盘配置。任何与官方每方 `1/1/1` 不同的完整配额向量必须内嵌完整描述符并绑定其自身哈希。
5. “experimental” 只是运行或发布分类；两个语义完全相同的完整描述符不得仅因模式标签不同而获得不同哈希。
6. 公开规则身份、`PositionalSuperkoKey`、`SearchKey`、`NNCacheKey` 和 checkpoint/model-artifact identity 是不同域，不得互换。

### 2.2 冻结的 ABI 版本

| 域 | 冻结值 |
|---|---|
| 模型 ABI / 图与输出契约 | Model V19；具体权重由独立 checkpoint/model-artifact 身份标识 |
| 神经输入 | Inputs V9，38 spatial + 67 global |
| 训练/回放 | Training Schema V1 |
| 动作编码 | Action Schema V1，`actionCodecVersion=1` |
| 固定画布 | 19×19 |
| 扁平动作数 | 1445 |

精确输入、训练张量和兼容约束由[输入特征 ABI V9](./04-输入特征ABI-V9.md)定义。协议不得用自己的动作顺序、输入版本或训练版本覆盖该规范。

### 2.3 Action Schema V1

四个点动作族的 kind code 固定为：

```text
0 NORMAL
1 IMMORTAL
2 DOUBLE_START
3 EIGHTWAY
```

对 19×19 画布坐标 `(X,Y)`：

```text
p = 19*Y + X
a = 361*k + p
PASS = 1444
```

因此 kind-major 范围固定为：

| Action ID | 含义 |
|---:|---|
| `0..360` | NORMAL |
| `361..721` | IMMORTAL |
| `722..1082` | DOUBLE_START |
| `1083..1443` | EIGHTWAY |
| `1444` | PASS |

整数 codec、kind 顺序、范围和规范 JSON envelope 都是 **FROZEN**。Action V1 envelope 只包含 `schemaVersion`、`actionId` 和 `kind`；坐标由 `actionId` 唯一导出，冗余坐标字段和其他未知字段必须拒绝。9×9、13×13、19×19 分别以 `(5,5)`、`(3,3)`、`(0,0)` 居中到固定 19×19 画布，footprint 外的点行动必须拒绝。跨语言 encode/decode 必须与全部 1445 个 ID 及八种 D4 向量一致。

## 3. 权威事件模型

### 3.1 术语

- **原子玩家行动**：`NORMAL`、`IMMORTAL`、`DOUBLE_START`、`EIGHTWAY` 或 `PASS` 中的一次已接受行动。Double-Move 的 start 与 continuation 是两个独立原子玩家行动。
- **规则事件**：记录已接受玩家行动、结算步骤、终局裁决或其他具有规则语义的变化。物理 JSON envelope 尚未冻结。
- **稳定状态边界**：一次玩家行动及其直接自动后果完成后，或一次 settlement event pop 的能力移除、全盘重建、同步提子和确定性闭包完成后，不存在半完成提子或半完成结算的状态。
- **特殊事件账本**：全部已使用 Immortal、Double-Move 和 Eightway 事件的有序、不可删除审计账本；被提走、consumed 或 no-op 不会删除条目。
- **结算轨迹**：按全局 newest-to-oldest 顺序处理每个账本事件的完整可重放记录，包括 tombstone/no-op、能力停用、重建、同步移除、闭包和稳定结果。

### 3.2 日志必须表达的逻辑信息

字段名与物理布局仍未冻结，但权威记录必须能无歧义表达：

1. 精确规则配置、冻结的公开身份三元组、初始棋盘和初始行动方；
2. 每个已接受原子玩家行动的 actor、typed action、全局原子行动序号和稳定结果；
3. 每个特殊事件的稳定 ID、逻辑时间戳、所有者、类型、来源点、source stone identity 和生命周期；
4. 结算触发原因、触发行动、全局倒序账本、每个 event pop、no-op、能力移除、同步提子、闭包结果和稳定状态；
5. PASS 后阶段变化、MVP 禁用死子协商移除与争议协议、两个连续 PASS 后对当前稳定盘面的计分、认输、超时和最终结果；
6. 命令关联、接受或拒绝结果、状态修订和权威日志位置之间的关联。

搜索统计、客户端光标、连接状态、UI 偏好和非权威墙钟采样不得伪装成规则事件。结算全序由稳定逻辑序位决定，不得依赖墙钟精度或容器遍历顺序。

### 3.3 接受、事件、下一状态与日志位置的语义提交边界

以下语义为 **FROZEN**：

1. Node 只执行传输、会话和已冻结 Schema 形状检查，然后把规则命令交给 C++。
2. C++ 从当前精确状态验证规则身份、修订、阶段、actor、配额、typed action 和合法性。
3. 拒绝结果不消费配额、不增加行动数、不改变 PASS 连续数、PSK、账本、状态修订或日志位置，也不产生已接受规则事件。
4. 对已接受命令，**接受结果、该转移产生的权威事件或事件组、完整下一精确状态、下一状态修订和已提交日志位置共同构成一个不可拆分的语义提交边界**。
5. 任何观察者都不得看到“状态已前进但事件未提交”或“事件已提交但下一状态仍是旧值”的可恢复权威状态。
6. 若玩家行动触发 settlement，下一可见玩家决策状态必须是完整 settlement 事务结束后的稳定状态；事务内每个 event pop 仍保留可审计轨迹和 PSK 追加。
7. 认输和游戏语义超时只在暴露的稳定命令边界接受：`COLLAPSE_PLAY`（包括 pending Double）或 `ORDINARY_PLAY`。若管理终止在候选原子行动提交前被 C++ 串行接受，则只提交立即终局事件，不提交候选行动、settlement 或面积计分，也不增加原子行动数。
8. 原子行动一旦提交，其触发的 settlement 从第一个 pop 前到最后一个 pop、PSK 追加、出口 actor/phase 更新及最终修订共同提交完成之前，不暴露管理终止、取消或其他命令边界；稍后到达的终止只能在完整 post-settlement 状态提交后再处理。
9. 请求/传输超时、背压、断线和取消与游戏语义 `TIMEOUT` 分域，不得自动生成终局事件。

数据库事务、WAL、文件追加、快照频率、`fsync` 策略、ACK 时点、崩溃恢复协议和跨进程持久化机制均为 **UNFROZEN**。实现可以选择不同物理机制，但不得破坏上述语义原子性。

### 3.4 PSK 历史边界

官方 Collapse Go 使用只含黑白占位、不含下一行动方的 occupancy-only 位置超级劫。冻结规则如下：

- `PositionalSuperkoKey` 的语义字段集合只有黑白占位。特殊标记、配额、阶段、行动号、账本和 next actor 均不属于 PSK 键。
- 每个已接受且具有稳定后状态的规则事件，都把其稳定黑白占位追加到 PSK 历史。玩家 PASS 和 no-op 可以产生重复条目。
- 普通点行动在落子、提子、自杀判定和 PSK 合法性检查完成并到达稳定闭包后追加占位。
- PASS 不落子、不提子、不进行自杀检查，也不执行 PSK 合法性检查；但 PASS 事件提交后的稳定占位仍追加到历史。
- 若原子行动触发 settlement，先按正常行动边界追加该行动的稳定占位；随后每弹出一个特殊事件并完成能力停用、重建、同步提子和闭包，都再次追加该 event pop 的稳定占位。
- tombstone 或 Double no-op pop 即使棋盘不变，也完成一个语义步骤并追加重复占位。
- settlement 生成的重复占位自动允许，不拒绝、不回滚、不提前终止；它们仍约束之后的玩家行动。
- 重建、群拆分或提子过程中的不稳定中间棋盘禁止进入 PSK 历史。
- **FROZEN**：初始化时，初始空盘的黑白占位是 PSK 历史第零项；在任何规则事件提交前，历史已经包含且仅包含这一条初始空占位。

PSK 的字节编码、增量哈希实现、碰撞处理和存储布局仍为 **UNFROZEN**；这不重新打开“只含黑白占位”的冻结语义。

### 3.5 Double-Move 与 continuation

- `DOUBLE_START` 与 continuation 是两个独立的已接受玩家行动、两个事件和两个搜索决策节点；两者之间实际 actor 保持不变。
- `DOUBLE_START` 在提交时消费 Double 配额、创建 consumed/tombstone 账本事件并记录稳定状态。
- `DOUBLE_START` 仅在 `A+2<=T` 时合法。`A=T-2` 时 start 与 continuation 分别完成第 `T-1`、`T` 个原子行动；`A=T-1` 时禁止 start。
- continuation 只允许 `NORMAL` 或 `PASS`。
- `NORMAL` continuation 执行完整落子、提子、自杀/保护和 PSK 合法性检查。
- `PASS` continuation 只验证 phase、actor 和 continuation 义务；它不放置棋子、不提子、不做自杀检查，也不做 PSK 重复拒绝检查。它仍增加 `A` 与 PASS 连计、形成独立事件、清除 pending Double、向 PSK 历史追加未改变的稳定占位，并在完整提交后把行动权交给对手。
- 任一合法 continuation 若触发 settlement，先把该对手保存为 `handoffActor`，settlement 完成后仍由该对手行动。

### 3.6 结算轨迹的物理封装

- **FROZEN**：轨迹必须完整、有序、可重放并包含 no-op；每个 event pop 的稳定后状态都进入 PSK 历史。
- **UNFROZEN**：使用一个顶层 settlement transaction 内嵌步骤，还是使用带共同事务 ID 和明确开始/结束边界的扁平事件序列。
- 任一封装都必须表达触发行动、账本事件来源、处理前后能力状态、同步移除集合、闭包结果、稳定占位、PSK 追加和事务最终状态。
- 从触发原子行动提交点到全部 settlement event pop、PSK 追加、出口 actor/phase 和最终状态修订共同提交完成，网关、客户端、搜索、玩家命令和管理终止均不得插入；禁止范围包括第一个 pop 之前、任意两个 pop 之间以及最后一个 pop 与出口提交之间。

## 4. 精确状态、快照和派生输出

### 4.1 精确状态的冻结语义

C++ 精确状态必须直接保存或能由权威日志无损恢复：

- 棋盘尺寸、当前可见占位和 stable stone/source identities；
- 实际下一 actor；
- base-Go 规则、贴目、ko、encore 和计分状态；
- 官方 occupancy-only PSK 的完整精确上下文；
- `T`、`A`、触发计数、PASS 连续数和 pre/post-settlement phase；
- pending Double owner 与关联事件；
- 初始、剩余和已用配额的精确整数；
- 完整有序特殊事件账本、原始逻辑时间戳、稳定 ID 和生命周期；
- recent atomic actor/kind/location records 与 `LegacyV7View` 所需投影；
- MVP 禁用死子协商移除捷径与争议协议、两个连续 PASS 后对当前稳定盘面计分，以及只在暴露稳定边界接受认输/游戏超时、终止先于动作提交时立即终局、动作先提交时完整 settlement 不可中断的状态；
- 当前已提交权威日志位置或与其一一对应的状态修订。

精确状态不内嵌完整权威日志，也不把 `legalMask` 当作语义字段。搜索状态只需携带未来相关的精确状态、PSK 上下文、账本和日志位置；不得用有限神经输入或事件日志全文替代精确状态。

### 4.2 legal mask 的派生契约

- `legalMask` 的规范形状为 `[1445]`，批量训练/推理形状为 `[B,1445]`。
- 它必须由权威 reducer 从确切状态和 Action Schema V1 生成，覆盖棋盘边界、占用、提子、自杀、ko/PSK、配额、phase、pending Double、threshold 和 PASS。
- 普通围棋模式仅开放 NORMAL/PASS；pending Double 仅开放 NORMAL/PASS；棋盘外四个点动作族均为 false。
- 快照或事件结果可以携带 legal mask 作为派生读模型，但必须绑定产生它的权威状态修订。旧修订 mask 不得用于新状态。
- legal mask 不得混入 PSK 键，也不得作为神经近似状态的一部分。若缓存后处理结果，NN-cache key 必须显式包含精确 mask 身份；缓存层级本身仍为 **UNFROZEN**。

### 4.3 尚未冻结的布局

- C++ 内部类边界、值对象划分、所有权、copy/undo 机制和缓存布局；
- 快照是全量状态、日志检查点、事件派生读模型还是这些形式的组合；
- 是否在外部快照中携带完整 PSK 历史，或携带可验证的持久化检查点；
- 颜色、坐标、生产 phase、终局、未来死子协商扩展、稳定 ID 和错误码在 M0 源 Schema 之外的具体 JSON 表示；
- 持久化、压缩、校验和、分片和保留策略。

任何不足以恢复隐藏 PSK、账本、pending Double 或日志位置的快照都不得宣称可独立续局。

## 5. Schema 家族

每个家族独立版本化；不存在一个可隐式覆盖全部格式的“全局 API 版本”。M0 的五个权威源位于 [`schemas/source/`](../../schemas/source/)，均使用 JSON Schema Draft 2020-12、关闭未知字段并通过自包含本地 `$ref` 校验。它们是可执行数据合同，不是生产规则实现。

| Schema 家族 | 用途与权威性 | 当前状态 |
|---|---|---|
| 规则语义描述符 | 绑定公开规则语义、官方配置、初始 PSK、动作、settlement、计分与终局政策 | `ruleset-descriptor-v1.schema.json`、规范描述符、受限 JCS profile 和公开身份三元组 **FROZEN** |
| Action Schema V1 | 1445 个 kind-major typed action ID | `action-v1.schema.json` 的 codec、顺序、范围与 canonical envelope **FROZEN** |
| 语义投影 | 表达稳定状态、转移、PSK、账本、settlement 与 legal-action 投影，供跨语言一致性比较 | `semantic-projection-v1.schema.json` **FROZEN**；不是生产事件 envelope 或 reducer |
| Conformance fixture | 组合身份、描述符、动作、前后投影与预期接受/拒绝，承载黄金和回归夹具 | `conformance-fixture-v1.schema.json` **FROZEN** |
| Mismatch bundle | 保存可复现差分前缀、双方观察、差异和最小化状态 | `mismatch-bundle-v1.schema.json` **FROZEN** |
| 权威事件日志 | 初始化、玩家行动、settlement event pop、终局与审计重放 | 事件语义及提交边界 **FROZEN**；生产字段布局 **UNFROZEN** |
| 引擎命令/结果 | 提交命令、返回接受/拒绝、关联修订 | 职责与无副作用拒绝 **FROZEN**；生产封装 **UNFROZEN** |
| 精确状态快照/检查点 | 恢复、调试和重连 | 必需语义 **FROZEN**；物理布局和持久化 **UNFROZEN** |
| legal-mask 派生读模型 | 输出与某权威修订绑定的精确合法动作 | 派生语义 **FROZEN**；生产传输与缓存 **UNFROZEN** |
| 搜索/分析流 | 候选、价值、策略、访问次数和所有权 | 非规则权威；版本和流式封装 **UNFROZEN** |
| Gateway 会话/WebSocket | 订阅、背压、重试、断档恢复 | 薄编排边界 **FROZEN**；消息 envelope **UNFROZEN** |
| 扩展 SGF | 人类交换、编辑器展示和有限互操作 | 非权威角色 **FROZEN**；属性与损失模型 **UNFROZEN** |
| Model V19 / Inputs V9 / Training Schema V1 | 神经输入、动作、输出和训练/回放 ABI | 以 [04](./04-输入特征ABI-V9.md) 为规范，版本、形状和明确列出的布局 **FROZEN** |

### 5.1 M0 合同 CLI 的验证层级

- `python3 tools/contract/contract.py canonicalize FILE`：只验证受限 JSON profile，并原样输出规范 UTF-8 字节；不执行 descriptor Schema。
- `python3 tools/contract/contract.py hash FILE`：只验证受限 JSON profile，并输出规范字节的 lowercase SHA-256；hash 成功不表示输入是有效规则描述符。
- `python3 tools/contract/contract.py validate ruleset-descriptor-v1 FILE`：执行受限 profile、关闭式 descriptor Schema、公开描述符要求和跨字段不变量；其他 schema 选择还执行各自适用的语义/跨制品检查。
- `python3 tools/contract/contract.py check`：验证固定 Schema 集与本地引用、仓库规范描述符、canonicalization/invalid-descriptor/action/D4/identity 向量、示例和跨制品绑定。

## 6. 版本与兼容规则

1. 每个 Schema 家族必须显式携带版本，或由不可歧义且可验证的上下文绑定版本。
2. 字段删除、必需字段新增、枚举重解释、事件排序改变或语义改变必须提升对应主版本。
3. 只增加明确可选、非权威、可忽略且不影响重放的字段，才可能是兼容小版本变化。
4. 规则语义变化必须同时产生新的 semantic version 和新的规范描述符哈希；线格式不变不能豁免该要求。
5. 仅改变传输封装、压缩或持久化而不改变规则语义，不得伪造新的规则哈希。
6. 权威日志不得原地重新解释。迁移必须生成新工件、记录源版本并保留原始日志。
7. 未知主版本、未知权威事件、未知必需枚举、不匹配的 Action Schema、Inputs 或 Training Schema 必须明确拒绝；不得静默降级为普通围棋。
8. 只有对应 Schema 明确声明字段为可选、非权威且可忽略时，读取器才可忽略未知字段。
9. 所有公开工件必须绑定完整且精确匹配的 `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899` 三元组；任一字段缺失或不匹配都必须拒绝。

## 7. 错误、幂等与恢复

### 7.1 错误类别

错误响应必须提供稳定的机器类别、人类可读说明、命令关联信息，并在可用时提供当前权威修订。确切字段和错误码注册表仍为 **UNFROZEN**。

| 类别 | 例子 | 必须行为 |
|---|---|---|
| 语法/Schema 错误 | 非法 JSON、缺字段、类型错误、越界坐标 | 拒绝；无事件、无状态和日志位置变化 |
| 不支持 | 未知规则身份、Schema 主版本、事件类型或能力 | 明确拒绝；不得猜测或降级 |
| 修订冲突 | 命令基于旧状态、事件断档 | 拒绝并要求重同步；不得在新状态上暗中重试 |
| 规则非法 | 非 actor、占点、无配额、Double 阶段错误、自杀、PSK | 由 C++ 裁决；原子拒绝且全部规则字段不变 |
| 会话/资源错误 | 会话不存在、队列关闭、引擎不可用 | 不伪造规则结果；只从最后完整语义提交边界恢复 |
| 内部不变量失败 | 状态、事件、日志位置或重放不一致 | 停止或隔离会话并输出诊断；不得继续发布推测状态 |

### 7.2 幂等与断线恢复

- 客户端重发同一命令不能生成重复玩家行动；命令关联 ID 与稳定规则事件 ID 是不同概念。
- 已完成语义提交的命令重发时，应返回或重新投递同一结果；同一关联 ID 携带不同命令内容必须报冲突。
- 崩溃恢复只能恢复到完整语义提交边界。不得恢复出“下一状态存在但对应日志位置不存在”的组合。
- 客户端按权威日志位置或修订检测重复、乱序和缺口；缺口通过日志或快照重同步解决，不由客户端重算。
- **UNFROZEN**：关联字段、保留窗口、持久化介质、事务协议、ACK 时点、快照频率和背压上限。

## 8. 扩展 SGF 的角色与损失模型

- **FROZEN**：扩展 SGF 仅是交换和展示格式，不能取代权威 JSON 事件日志。
- 扩展 SGF 规范必须声明自己的损失模型：哪些规则身份、typed action、Double linkage、settlement trace、PSK 相关信息、终局原因、变化树和注释能够保留，哪些会丢失或必须拒绝。
- 测试不得预先假设 JSON → SGF → JSON 对全部 Collapse Go 语义无损。测试只验证最终规范明确承诺的保真范围。
- 若某 profile 声称对一组事件无损，必须通过该声明范围内的语义重放等价测试；若声明有损，导出器必须产生可判定的损失报告或拒绝不能安全表示的内容。
- 不识别 Collapse 扩展的导入器不得把特殊行动静默当作 NORMAL，也不得把缺失的 settlement 或 post-settlement history 猜测补齐。
- SGF 评论、标记、变化树和分析默认非权威，不能改变主线规则结果。
- **UNFROZEN**：属性名、版本属性、转义规则、变化树限制、损失 profile 和与现有 KataGo SGF 读写器的接口。

## 9. 决策状态与关闭证据

| ID | 状态 | 内容 | 证据或关闭条件 |
|---|---|---|---|
| IDENT-01 | **FROZEN** | 公共 `rulesetId = mutago.collapse-go`；内部 variant enum/ID、目录 slug 与运行标签不属于公开身份 | 规范描述符、关闭式 Schema、`public-identity-v1.json` 与跨制品校验 |
| DESC-01 | **FROZEN** | `rfc8785-jcs-ascii-safe-integer-v1` 与 14973 字节规范描述符 | `canonicalization-v1.json` 固定 profile 正反例；`public-identity-v1.json` 固定规范字节长度；独立实现逐字节复核 |
| HASH-01 | **FROZEN** | lowercase SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899` | `public-identity-v1.json` 与合同检查器复核 |
| PSK-INIT-01 | **FROZEN** | 初始空盘占位是 PSK 历史第零项 | 描述符、Schema、无效变体和后续 reducer/oracle 边界夹具 |
| ACTION-ENV-01 | **FROZEN** | canonical Action V1 envelope 为 `schemaVersion`、`actionId`、`kind`，坐标由 ID 导出 | `action-v1.schema.json` 与 `action-v1.json` 全动作/D4 向量 |
| DEAD-MVP-01 | **FROZEN** | MVP 不启用协商死子移除捷径或争议协议；普通行棋持续到两个连续 PASS 后对当前稳定盘面计分 | 描述符、Schema、无效策略变体和后续终局夹具 |
| TERM-ADMIN-01 | **FROZEN** | 管理终止只在暴露稳定边界接受；终止先于动作提交则立即终局且无 settlement/计分，动作先提交则其触发的完整 settlement 不可中断；运维超时/取消不等于游戏 `TIMEOUT` | 描述符、语义投影、顺序竞争夹具和 Gateway/E2E 故障测试 |
| PROTO-01 | **UNFROZEN** | M0 源 Schema 尚未覆盖的生产命令、结果、权威事件、快照和 legal-mask 读模型精确字段 | 字段级生产 Schema、正反例、版本拒绝和跨语言 round-trip |
| COMMIT-01 | **UNFROZEN** | 语义提交边界的物理持久化、WAL、ACK 与恢复机制 | 崩溃注入证明不会产生状态/日志撕裂 |
| SETTLE-01 | **UNFROZEN** | settlement 轨迹采用内嵌步骤还是扁平事务事件 | 截断、流式发布、原子恢复和重放评审 |
| STATE-01 | **AUDIT-BLOCKED** | 精确状态与 KataGo `Board`、`BoardHistory`、undo 和缓存的所有权边界 | 上游调用图、不变量和生命周期审计 |
| KEY-PHYS-01 | **UNFROZEN** | SearchKey 与 NNCacheKey 的物理字节编码、digest/碰撞策略、生命周期、缓存层级、淘汰和存储布局；必需语义组成已由 [04](./04-输入特征ABI-V9.md) §G.3–G.4 冻结 | 版本化物理设计、语义等价、碰撞安全、命中等价和失效测试 |
| KEY-INTEG-01 | **AUDIT-BLOCKED** | SearchKey、NNCacheKey 及 occupancy-only PSK 与上游搜索、历史和缓存路径的集成与兼容证据 | 上游调用图、独立变更敏感性、缓存失效及集成审计 |
| DEAD-FUTURE-01 | **UNFROZEN** | 未来版本是否增加死子提案、协商移除或争议恢复协议 | 新语义版本、描述符、状态机、迁移影响与一致性夹具；不影响当前 MVP |
| SGF-01 | **UNFROZEN** | 扩展 SGF 属性与声明的损失模型 | profile 规范、拒绝行为和按声明保真度执行的测试 |

字段冻结与实现顺序见[路线图与未决事项](./07-路线图与未决事项.md)，所有准入条件见[测试与一致性门槛](./06-测试与一致性门槛.md)。

## English Summary

This document defines protocol and schema boundaries for frozen Collapse Go `0.1.0-draft` semantics on the pinned KataGo stable v1.16.5 baseline at `ba938676d7f42d70950b3a535af2466fb642008c`. The public identity is `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`. Internal variant IDs, repository slugs, runtime labels, Git SHAs, and model SHAs are separate domains and are not public rules identity.

The restricted `rfc8785-jcs-ascii-safe-integer-v1` profile governs JSON syntax, value domain, and canonical bytes only. It accepts ASCII strings and keys, safe signed integers in `[-9007199254740991,9007199254740991]`, booleans, null, arrays, and objects, while rejecting duplicate keys, floats, non-ASCII data, unsafe integers, invalid UTF-8, and invalid JSON number syntax. It does not validate descriptor fields or reject arbitrary profile-valid object keys. The 14,973-byte canonical rules descriptor separately passes the closed descriptor schema, descriptor invariants, and cross-artifact bindings. `canonicalize` and `hash` enforce only the profile; descriptor `validate` and repository `check` enforce Schema and applicable invariants.

C++ is the sole production rules authority, Python is an independently implemented differential oracle, Node is a thin process/session/WebSocket layer, and the client only renders authoritative results. M0 provides five closed Draft 2020-12 source schemas for Action V1, the ruleset descriptor, semantic projections, conformance fixtures, and mismatch bundles. These executable data contracts do not implement the production reducer, the full Python oracle, the authoritative event protocol, search, Gateway, or Web.

For every accepted command, the acceptance result, emitted authoritative event or event group, complete next exact state, next revision, and committed log position form one indivisible semantic commit boundary. Administrative termination is accepted only at exposed stable decision boundaries: if accepted before a candidate action commits, it ends immediately without that action, settlement, or scoring; once an action commits, any settlement it triggers completes atomically and exposes no internal command boundary. Operational timeouts and cancellation never synthesize game `TIMEOUT`. Concrete production envelopes, persistence, WAL, transaction, snapshot, ACK, and crash-recovery mechanics remain unfrozen, but no implementation may expose or recover a torn state/log pair.

Official Collapse Go uses occupancy-only positional superko. Initial empty occupancy is the sole history entry at initialization and has index zero. Every accepted rule event with a stable post-state appends that occupancy. If an action triggers settlement, its stable closure is appended first, followed by every newest-to-oldest event pop’s stable closure; tombstone/no-op pops may append duplicates, and unstable intermediates never enter history.

Action Schema V1 is kind-major with `a=361*k+p`: NORMAL `0..360`, IMMORTAL `361..721`, DOUBLE_START `722..1082`, EIGHTWAY `1083..1443`, and PASS `1444`. Canonical Action V1 is a closed object containing exactly `schemaVersion`, `actionId`, and `kind`; coordinates are derived from the action ID, and missing/unknown fields, unknown versions, redundant coordinates, and inconsistent `kind`/ID pairs fail closed. The 9x9, 13x13, and 19x19 footprints are centered at offsets `(5,5)`, `(3,3)`, and `(0,0)`.

The MVP enables neither agreed dead-stone removal nor a dead-stone dispute protocol. Ordinary play continues until two consecutive passes, then the current stable board is scored. Any future negotiation extension requires a new semantic version, descriptor, and protocol tests. Remaining open work concerns production protocol envelopes, persistence, exact-state integration, physical search/cache keys, and the SGF loss profile, not the frozen M0 identity or PSK seed.
