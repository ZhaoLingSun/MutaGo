# Gateway 服务

本目录预留给 MutaGo 的薄 Node 网关。当前只建立职责边界，不包含服务源码、包清单、依赖、生成绑定、进程包装器、模型、数据或部署产物。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：网关只负责进程、会话、WebSocket、成帧、结构校验、流量控制和错误传播，不承担规则语义。
- **FROZEN**：Collapse Go `0.1.0-draft` 已记载的玩法语义已经冻结；`draft` 不是网关补充或改变规则的授权。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式。`collapse-go` 目录名仅是候选 slug。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一产生生产权威游戏事件的组件。
- 网关可以启动、监督和关联 C++ 进程，可以验证消息结构和身份字段是否存在，但不得判断动作是否合法或状态是否符合规则。
- 网关不得生成、修补、重排或重新解释 C++ 权威事件；重试与重连也不得制造第二条规则历史。
- Python 只能在测试中产生参考预期，不得成为 Node 生产回退、状态修复器或事件生产者。
- C++ 产生的 JSON 事件序列是权威游戏记录。内存会话、数据库索引、派生快照与扩展 SGF 都不能取得更高权威性。
- 接受结果、相应权威事件、下一状态和日志位置属于同一语义提交边界；具体持久化事务、ACK 与恢复机制仍为 **UNFROZEN**。

## 传输与身份约束

网关必须无损转发 typed action。Action Schema V1 固定为 kind-major：

| 动作 | ID 范围 |
|---|---:|
| `NORMAL` | `0..360` |
| `IMMORTAL` | `361..721` |
| `DOUBLE_START` | `722..1082` |
| `EIGHTWAY` | `1083..1443` |
| `PASS` | `1444` |

点动作公式为 `a = 361*k + p`。网关不得把相同点上的四种动作折叠为一个裸位置，也不得重新映射 `PASS`。

涉及规则身份的握手、会话、事件和回放边界必须显式表达其身份状态。公共 `rulesetId`、规范描述符和公开哈希分配前，必须保留明确的 `unassigned`，不得用候选 slug、版本、Git SHA、内容摘要样例或全零值代填。

消息名称、帧格式、排序、幂等、超时、取消、重试、背压、进程重启、持久化、回放、身份协商与错误码均为 **UNFROZEN**。

## 非目标

- 不在 Node 中实现合法性、提子、自杀、位置超级劫、结算、计分、行动方或终局算法。
- 不把 Schema 有效性解释为游戏语义有效性。
- 不从扩展 SGF 推导或恢复权威状态。
- 不暴露或混用搜索键、位置超级劫键与神经网络缓存键。
- 不在本目录决定规范语义描述符、公共规则身份或模型 ABI。

## 实现准入

开始加入网关代码前，至少需要：

1. C++ 进程协议、启动握手、能力发现和身份核验已经明确；
2. WebSocket 的排序、背压、超时、取消和错误传播已经明确；
3. 进程崩溃、网关重启、断线重连、事件回放及身份不匹配的行为已经明确；
4. 输入大小、会话配额、来源校验、日志脱敏和拒绝服务防护边界已经明确；
5. 具有确定性的 C++ 夹具，能够证明网关只编排、不裁决；
6. Node 运行时及新增库完成许可证、来源、安全与再分发审计。

## 相关文档

- [系统架构与权威边界](../../docs/设计文档/01-系统架构与权威边界.md)
- [协议与 Schema](../../docs/设计文档/05-协议与Schema.md)
- [Web 客户端边界](../../apps/web/README.md)
- [Schema 边界](../../schemas/README.md)
- [端到端测试边界](../../tests/end-to-end/README.md)

## English Summary

This directory is reserved for a thin Node gateway that manages engine processes, sessions, WebSocket transport, framing, structural validation, backpressure, and error propagation. C++ alone decides production semantics and emits authoritative game events; Node must neither reinterpret them nor use Python as a production fallback. Frozen gameplay and ABI facts must pass through unchanged, including the Action Schema V1 kind-major codec. The public `rulesetId` literal and canonical-descriptor encoding/canonicalization are **UNFROZEN / unassigned**; the final public descriptor SHA-256 is **AUDIT-BLOCKED / unassigned**.