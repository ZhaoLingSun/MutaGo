# Collapse Go（坍缩围棋）规则集边界

本目录预留给 Collapse Go 的规则集身份材料与规则集专属交换约定。当前只建立目录和权威边界，不包含规则实现、Schema、生成物、模型、数据、标签或发布制品。

## 文档状态

- **FROZEN**：规则语义版本为 Collapse Go `0.1.0-draft`。
- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：规范规则草案中已经列出的棋盘、阈值、配额、Immortal、Double-Move、Eightway、位置超级劫、结算、终局与计分语义均已冻结。版本名中的 `draft` 不重新开放这些玩法语义。
- **FROZEN**：模型和数据接口版本为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式。目录名 `collapse-go` 只是候选 slug。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

任何实现都必须以[规范规则文档](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)为玩法依据。本 README 只说明目录责任，不覆盖或降低该文档的规范性。

## 冻结规则约束

### 位置超级劫

官方 Collapse Go 使用只比较黑白占据的 occupancy-only positional superko，即位置超级劫（`PositionalSuperkoKey` / PSK）：

- PSK 的语义字段只包含黑白占据，不包含下一手玩家、配额、事件账本或其他状态；
- 每个玩家原子动作及其直接自动后果达到稳定闭包后，其稳定占据按规则进入 PSK 历史；
- 若动作触发 settlement，则每弹出一个事件，并完成该次能力移除、重建与提子的稳定闭包后，该稳定占据也进入 PSK 历史；
- tombstone pop 即使不改变棋盘，也会追加该次稳定占据，允许重复历史条目；
- settlement 产生的重复占据自动获准，但会约束后续玩家动作；
- 重建或提子过程中的不稳定中间棋盘不进入 PSK 历史。

PSK 的字节编码、哈希实现和存储布局仍可由后续实现设计决定，但不得改变上述语义字段或稳定状态边界。初始空盘是否作为第零项播种，在公共语义描述符作出明确决定前保持 **UNFROZEN**。

### 动作 ABI

Action Schema V1 固定采用 kind-major 编码，点动作满足 `a = 361*k + p`：

| 动作 | ID 范围 |
|---|---:|
| `NORMAL` | `0..360` |
| `IMMORTAL` | `361..721` |
| `DOUBLE_START` | `722..1082` |
| `EIGHTWAY` | `1083..1443` |
| `PASS` | `1444` |

能力名称 Double-Move 与起始原子动作 `DOUBLE_START` 必须区分。相同棋盘点上的四种点动作具有不同 typed-action 身份。

## 权威边界

- C++ 是唯一生产规则与搜索权威，唯一负责在生产中接受或拒绝动作、转移状态并产生权威游戏事件。
- Python 是独立、刻意较慢的参考实现，只产生一致性测试所需的参考预期；它不是生产权威、回退实现、代码生成源或共享规则库。
- C++ 产生的 JSON 事件序列是权威游戏记录。快照是派生视图，扩展 SGF 只用于交换；不承诺扩展 SGF 对全部特殊动作、settlement 与终局信息无损往返。
- 搜索键、位置超级劫键与神经网络缓存键属于不同域，不得互换，也不得充当公共规则身份。

## 公共身份状态

公共不可变身份最终由公共 `rulesetId`、语义版本与 `SHA-256(canonicalSemanticDescriptorBytes)` 共同确定。但当前只有语义版本、摘要算法与输入关系以及玩法语义状态已明确：

- **UNFROZEN / unassigned**：公共 `rulesetId` 最终字面值；
- **UNFROZEN / unassigned**：规范语义描述符的字段、编码和规范化方式；
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256 最终值。

不得用 `collapse-go` 目录名、Git 提交、README 文本摘要、SGF 摘要、示例摘要或全零值冒充分配结果。描述符及其公开哈希必须在后续独立、可审计的身份决策中确定；玩法语义已冻结这一事实不等于公共身份已经分配。

## 实现准入

开始加入规则代码前，至少需要：

1. 把已冻结规则转化为可执行的不变量和中立测试向量；
2. 明确仍未决的公共身份、描述符编码和线协议细节，而不重开玩法语义；
3. 保证 C++ 与 Python 采用独立实现路径；
4. 覆盖 typed action、配额、Double continuation、occupancy-only PSK、逐事件稳定 settlement 状态、终局与计分；
5. 对新增库、外部规则材料、模型和数据完成许可证、来源、安全与再分发审计。

## 相关文档

- [坍缩围棋规范规则](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)
- [输入特征 ABI V9](../../docs/设计文档/04-输入特征ABI-V9.md)
- [协议与 Schema](../../docs/设计文档/05-协议与Schema.md)
- [一致性测试边界](../../tests/conformance/README.md)
- [Schema 边界](../../schemas/README.md)

## English Summary

Collapse Go `0.1.0-draft` has frozen gameplay semantics despite its draft label, including the documented board, thresholds, quotas, abilities, occupancy-only positional superko, settlement, ending, and scoring rules. Every accepted event, including Pass, appends its stable post-state; every settlement event pop contributes its stable post-closure occupancy as well, while unstable rebuild or capture intermediates do not. C++ alone is the production authority and authoritative-event producer; Python supplies independent reference expectations. Model V19, Inputs V9, Training Schema V1, and Action Schema V1 are fixed. The public `rulesetId` literal and canonical-descriptor encoding/canonicalization remain **UNFROZEN / unassigned**; the final public descriptor SHA-256 is **AUDIT-BLOCKED / unassigned**.