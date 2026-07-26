# Schema 边界

本目录预留给 MutaGo 的版本化跨进程、跨语言和持久记录数据契约。当前不包含实际 Schema、生成器、生成绑定、包清单、依赖、CI、模型、数据或构建产物。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：玩法语义由规范规则文档定义，Schema 只能表达数据契约，不能定义或裁决规则。
- **FROZEN**：Collapse Go `0.1.0-draft` 已写明的玩法语义已经冻结，不能因 Schema 尚未实现而重开。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式。`collapse-go` 只是目录候选 slug。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一能够产生生产权威游戏事件的组件。
- Python 只产生独立参考预期；Node 只编排和执行结构校验；React 只发送意图并呈现权威状态。
- Schema 校验成功只表示数据满足结构契约，不表示动作合法、状态正确、计分有效或事件具有规则意义。
- C++ 产生的 JSON 事件序列是权威记录。快照、网关会话与扩展 SGF 均是派生或交换表示。
- Schema 不得把搜索键、位置超级劫键与神经网络缓存键合并为一个字段或暗示它们可以互换。

## 已冻结的 ABI 契约

### 版本与尺寸

未来 Schema 必须能够无歧义表达并校验以下固定版本：

- `modelVersion = 19`
- `inputsVersion = 9`
- `trainingSchemaVersion = 1`
- `actionCodecVersion = 1`
- 19×19 画布
- 38 个空间输入 S0–S37
- 67 个全局输入 G0–G66
- 1445 个扁平动作

### Action Schema V1

点动作采用 kind-major 编码 `a = 361*k + p`：

| kind | 动作 | ID 范围 |
|---:|---|---:|
| `0` | `NORMAL` | `0..360` |
| `1` | `IMMORTAL` | `361..721` |
| `2` | `DOUBLE_START` | `722..1082` |
| `3` | `EIGHTWAY` | `1083..1443` |
| — | `PASS` | `1444` |

任何语言绑定都必须保持 typed action 身份，禁止只序列化裸位置或把四个动作块改成 point-major。

### PSK 与 settlement 记录

官方规则采用 occupancy-only PSK。Schema 若承载 PSK 重放材料或 settlement trace，必须保留以下边界：

- 每个事件的稳定 settlement 后棋盘进入 PSK 历史；
- tombstone pop 的稳定棋盘也进入历史，可产生重复项；
- 不稳定的重建、提子中间棋盘不进入历史；
- PSK 不包含下一手玩家。

PSK 的线编码、摘要算法和存储布局尚未冻结，但 Schema 不得改变其 occupancy-only 语义。初始空盘是否播种仍为 **UNFROZEN**。

## 身份表达

未来需要公共规则身份的信封必须为身份各部分保留明确、可验证的位置，并能够表示尚未分配的状态。当前不得把候选目录 slug、Git SHA、全零摘要或示例值写成公共 `rulesetId` 或规则哈希。

规范语义描述符的字段、规范 JSON/字节编码、数字与 Unicode 规范化及字段顺序仍为 **UNFROZEN / unassigned**；摘要算法及输入关系 `SHA-256(canonicalSemanticDescriptorBytes)` 为 **FROZEN**；最终公开摘要值的分配为 **AUDIT-BLOCKED / unassigned**。玩法语义已经冻结不意味着这些身份编码细节或最终摘要值已经分配。

## 未冻结的 Schema 设计

文件名、消息族、字段名、空值与数字规则、未知字段政策、兼容窗口、版本协商、错误码、代码生成工具和持久化编码均待后续决定。任何决定都必须服从已经冻结的规则与 ABI，不得反向改变其语义。

## 非目标

- 不在 JSON Schema、TypeScript 类型、C++ 结构体或 Python 数据类中实现规则算法。
- 不把某一种语言绑定提升为规范语义描述符。
- 不让生成代码反向修改手写数据契约。
- 不在本目录定义网络拓扑、进程管理或客户端状态管理。

## 实现准入

开始加入 Schema 前，至少需要：

1. 明确每个消息族的拥有者、方向、排序和生命周期；
2. 明确未分配身份的表示以及后续身份分配后的迁移规则；
3. 冻结兼容、未知字段、弃用、版本协商与错误传播政策；
4. 准备跨 C++、Python、Node 与 TypeScript 的有效和无效黄金样例；
5. 对 Schema 库、生成器、验证器及传递依赖完成许可证、来源、安全、确定性与再分发审计。

## 相关文档

- [输入特征 ABI V9](../docs/设计文档/04-输入特征ABI-V9.md)
- [协议与 Schema](../docs/设计文档/05-协议与Schema.md)
- [坍缩围棋规则集边界](../rulesets/collapse-go/README.md)
- [网关边界](../services/gateway/README.md)
- [一致性测试边界](../tests/conformance/README.md)

## English Summary

This directory is reserved for versioned interchange schemas. Schemas validate structure but never decide gameplay; C++ alone emits production authoritative events, while Python supplies reference expectations. Frozen identifiers are Model V19, Inputs V9, Training Schema V1, and Action Schema V1. The action codec is kind-major with four 361-point blocks and PASS at 1444. Official Collapse Go PSK is occupancy-only, records every accepted event’s stable post-state and every stable settlement board, and excludes unstable intermediates. The descriptor fields and canonicalization remain **UNFROZEN / unassigned**; `SHA-256(canonicalSemanticDescriptorBytes)` is frozen; assignment of the final public digest remains **AUDIT-BLOCKED / unassigned**.