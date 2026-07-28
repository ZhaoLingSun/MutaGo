# Collapse Go（坍缩围棋）规则集边界

本目录保存 Collapse Go 的规则集身份材料与规则集专属交换约定。M0 在此加入公开语义描述符，以及 canonicalization、public-identity、invalid-descriptor、Action/D4 黄金向量；不包含完整 C++ 规则 reducer、完整 Python 规则 oracle、搜索、神经网络、Gateway、Web、模型、训练数据、标签或发布包。

## 文档状态

- **FROZEN**：规则语义版本为 Collapse Go `0.1.0-draft`。
- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：规范规则文档中已经列出的棋盘、阈值、配额、Immortal、Double-Move、Eightway、位置超级劫、结算、终局与计分语义均已冻结。
- **FROZEN**：模型和数据接口版本为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **FROZEN**：公共 `rulesetId` 为 `mutago.collapse-go`；内部 variant 枚举、`collapse-go` 目录名和其他 slug 均不是公开身份。
- **FROZEN**：初始空盘占据是 PSK 历史第零项；MVP 死子协商移除捷径与争议协议均延期且禁用。

任何实现都必须以[规范规则文档](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)为玩法依据。本 README 只说明目录责任和已经分配的 M0 合同，不覆盖或降低该文档的规范性。

## 冻结规则约束

### 位置超级劫

官方 Collapse Go 使用只比较黑白占据的 occupancy-only positional superko，即位置超级劫（`PositionalSuperkoKey` / PSK）：

- PSK 的语义字段只包含黑白占据，不包含下一手玩家、配额、事件账本或其他状态；
- 初始空盘占据固定为 PSK 历史第零项；
- 每个玩家原子动作及其直接自动后果达到稳定闭包后，其稳定占据进入历史；
- 若动作触发 settlement，则每弹出一个事件并完成能力移除、重建与提子的稳定闭包后，该稳定占据也进入历史；
- tombstone/no-op pop 即使不改变棋盘，也会追加稳定占据并允许重复历史条目；
- 计分、认输或游戏语义超时等具有稳定后状态的终局事件也会追加其稳定占据；管理终止追加的是未改变的当前稳定占据；
- settlement 产生的重复占据自动获准，但会约束后续玩家动作；
- 重建或提子过程中的不稳定中间棋盘不进入历史。

PSK 的运行时字节编码、哈希实现和存储布局仍可由后续实现设计决定，但不得改变上述语义字段、初始播种选择或稳定状态边界。

### 动作 ABI

Action Schema V1 固定采用 kind-major 编码，点动作满足 `a = 361*k + p`：

| 动作 | ID 范围 |
|---|---:|
| `NORMAL` | `0..360` |
| `IMMORTAL` | `361..721` |
| `DOUBLE_START` | `722..1082` |
| `EIGHTWAY` | `1083..1443` |
| `PASS` | `1444` |

能力名称 Double-Move 与起始原子动作 `DOUBLE_START` 必须区分。相同棋盘点上的四种点动作具有不同 typed-action 身份。9×9、13×13、19×19 先按 `(5,5)`、`(3,3)`、`(0,0)` 偏移居中到 19×19 画布；D4 围绕 `(9,9)`，棋盘 footprint 外的点动作必须拒绝。canonical Action V1 wire envelope 是关闭式对象，恰含 `schemaVersion`、`actionId`、`kind`；坐标由 `actionId` 唯一导出。缺失/未知字段、冗余坐标、未知版本和 kind/ID 不一致必须拒绝。

## 权威边界

- C++ 是唯一生产规则与搜索权威，唯一负责在生产中接受或拒绝动作、转移状态并产生权威游戏事件。
- Python 是独立、刻意较慢的参考实现，只产生一致性测试所需的参考预期；它不是生产权威、生产回退、代码生成源或共享规则库，M0 合同工具也不是完整规则 oracle。
- C++ 产生的 JSON 事件序列是权威游戏记录。快照是派生视图，扩展 SGF 只用于交换；不承诺扩展 SGF 对全部特殊动作、settlement 与终局信息无损往返。
- 搜索键、位置超级劫键、神经网络缓存键与公开规则身份属于不同域，不得互换，也不得彼此充当替代身份。

## 公开不可变身份

公开身份三元组为：

```text
rulesetId:       mutago.collapse-go
semanticVersion: 0.1.0-draft
descriptorSha256: a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899
```

摘要输入是 [`descriptor-v0.1.0-draft.json`](descriptor-v0.1.0-draft.json) 按 `rfc8785-jcs-ascii-safe-integer-v1` profile 产生的规范 UTF-8 字节，长度固定为 `14973`，摘要编码固定为 lowercase SHA-256。该 profile 只约束 JSON 词法、值域和规范字节：有效 UTF-8、无重复键、ASCII 字符串与键、安全有符号整数 `[-9007199254740991,9007199254740991]`、布尔、`null`、数组和对象；浮点、非 ASCII 数据、不安全整数和非法数字词法被拒绝。它不校验 descriptor 字段。规范描述符还必须独立通过关闭式 descriptor Schema、跨字段不变量和跨制品绑定；未知描述符字段由该验证层拒绝。独立 C++ 与 Python 实现必须产生完全相同的规范字节。

该描述符显式编码官方空盘 19×19 配置、9/13/19 居中与阈值政策、双方 `1/1/1` 配额、三种能力、动作/PSK/settlement/pass/scoring/termination 行为和版本绑定。初始空盘占据固定为 PSK 历史第零项；MVP 不启用协商死子移除或死子争议协议，而是在普通行棋的两个连续 `PASS` 后对当前稳定盘面直接计分。认输和游戏语义超时只在暴露稳定边界接受：若先于候选动作提交则立即终局且不运行 settlement 或计分；动作先提交时，其触发的完整 settlement 必须原子完成，内部不暴露终止或取消边界。请求/传输超时、背压、断线、取消和进程故障不得合成游戏 `TIMEOUT` 或胜负。未来协商扩展必须使用新的语义版本、描述符与测试。

## 黄金向量

[`vectors/`](vectors/) 包含：

- `canonicalization-v1.json`：规范输入、预期规范 UTF-8 字符串、SHA-256，以及重复键、浮点、非 ASCII、unsafe integer 等拒绝案例；
- `descriptor-invalid-v1.json`：未知字段、错误公共 ID、错误初始 PSK、point-major 和错误死子策略等拒绝案例；
- `action-v1.json`：全部动作族边界、PASS、9/13/19 居中映射、棋盘 footprint 接受/拒绝摘要、非规范 typed-action 封装拒绝、显式棋盘外拒绝和八种 D4 往返；
- `public-identity-v1.json`：规范字节长度与公开身份三元组。

执行：

```bash
python3 tools/contract/contract.py canonicalize FILE
python3 tools/contract/contract.py hash FILE
python3 tools/contract/contract.py validate ruleset-descriptor-v1 FILE
python3 tools/contract/contract.py check
```

`canonicalize` 与 `hash` 只验证受限 JSON profile；成功不表示输入是有效 descriptor。`validate ruleset-descriptor-v1` 才执行关闭式 Schema 与描述符不变量；`check` 进一步验证仓库固定 Schema、描述符、向量、示例及跨制品绑定。

## 后续实现准入

开始加入规则代码前，至少需要：

1. 让 C++ 与独立 Python 实现分别消费同一描述符、Schema 和中立测试向量；
2. 覆盖 typed action、配额、Double continuation、occupancy-only PSK、逐事件稳定 settlement 状态、终局与计分；
3. 保证 C++ 与 Python 采用独立规则实现路径，且 Node/React 不建立第二套规则裁决；
4. 按治理文档完成差分、重放、撤销、D4、sanitizer 和后续生产门槛；
5. 对新增库、外部规则材料、模型和数据完成许可证、来源、安全与再分发审计。

## 相关文档

- [坍缩围棋规范规则](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)
- [输入特征 ABI V9](../../docs/设计文档/04-输入特征ABI-V9.md)
- [协议与 Schema](../../docs/设计文档/05-协议与Schema.md)
- [一致性测试边界](../../tests/conformance/README.md)
- [Schema 边界](../../schemas/README.md)

## English Summary

Collapse Go `0.1.0-draft` has frozen gameplay semantics despite its draft label. The public identity is `mutago.collapse-go`, semantic version `0.1.0-draft`, and descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`; internal variant enums, repository slugs, and runtime labels are not public identity. The restricted profile governs JSON syntax, value domain, and canonical bytes only; it rejects duplicate keys, floats, non-ASCII data, unsafe integers, invalid UTF-8, and invalid number syntax but does not validate descriptor fields. The 14,973-byte descriptor separately passes the closed schema, descriptor invariants, and cross-artifact bindings. `canonicalize`/`hash` enforce only the profile, while descriptor `validate` and repository `check` enforce Schema and applicable invariants.

The descriptor freezes the official empty 19x19 configuration, 9/13/19 centering, per-player 1/1/1 quotas, all abilities, the fixed 1445-way kind-major action ABI, occupancy-only PSK with initial empty occupancy at history index zero, stable action, terminal-event, and settlement-pop history appends, scoring, and termination. Canonical Action V1 is a closed object containing exactly `schemaVersion`, `actionId`, and `kind`; coordinates are derived, and missing/unknown fields, unknown versions, redundant coordinates, and inconsistent `kind`/ID pairs fail closed. The MVP enables neither agreed dead-stone removal nor a dispute/recovery protocol. Administrative termination is accepted only at exposed stable boundaries: termination-first ends immediately without the candidate action, settlement, or scoring and appends the unchanged stable occupancy; action-first requires any triggered settlement to complete atomically. Operational timeouts and cancellation never synthesize game `TIMEOUT`. C++ remains the sole production authority, Python remains an independent slow reference, and this M0 milestone provides executable contracts and vectors rather than a complete rules engine or product implementation.
