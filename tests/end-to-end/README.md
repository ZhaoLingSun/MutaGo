# 端到端测试

本目录预留给 MutaGo 生产链路的黑盒测试：`React 客户端 → WebSocket → Node 网关 → C++ 权威实现`，并观察 C++ 产生的权威 JSON 事件记录及其派生呈现。当前不包含测试源码、浏览器配置、夹具、依赖、模型、报告或 CI 配置。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：Collapse Go `0.1.0-draft` 已写明的玩法语义已经冻结；端到端测试只验证生产链路是否保真，不重新定义规则。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式；所有跨组件场景必须保留明确的未分配状态。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一产生生产权威游戏事件的组件。
- Node 网关只编排、成帧和验证结构；React 只发送用户意图并呈现结果；测试浏览器不得重算规则结论。
- Python oracle 不进入生产端到端路径。C++/Python 规则差分、规则穷举与百万动作硬闸门属于[一致性测试](../conformance/README.md)。
- C++ 产生的 JSON 事件序列是权威记录。截图、DOM、网关内存、派生快照与扩展 SGF 都不是权威来源。
- 端到端断言中的已知游戏结果必须来自冻结的 C++ 场景夹具或 C++ 权威事件记录，而不是浏览器侧算法。

## 必测生产契约

### 动作与版本保真

生产链路必须逐跳保持 Model V19、Inputs V9、Training Schema V1 和 Action Schema V1 的版本信息。若协议传输整数动作 ID，必须原样保持 kind-major 编码：

| 动作 | ID 范围 |
|---|---:|
| `NORMAL` | `0..360` |
| `IMMORTAL` | `361..721` |
| `DOUBLE_START` | `722..1082` |
| `EIGHTWAY` | `1083..1443` |
| `PASS` | `1444` |

点动作满足 `a = 361*k + p`。测试应证明 Web 和 Gateway 不把 typed action 降级为裸位置、不重新编号动作族，也不在拒绝后伪造权威事件。

### 身份与回放

在公共身份分配前，每个相关握手、会话、事件和回放场景都必须保留 `unassigned` 状态。测试必须拒绝把候选 slug `collapse-go`、Git SHA、全零摘要或示例值冒充公共 `rulesetId`、规范描述符或规则哈希。

回放测试必须从 C++ 权威 JSON 事件记录恢复派生状态，并验证事件排序、日志位置、身份状态和重连结果。扩展 SGF 只验证已声明的交换行为与损失模型，不承担权威恢复。

### settlement 可观察结果

端到端层不重新计算 PSK，但必须验证协议和日志没有丢失 C++ 提供的规则意义信息。官方规则采用 occupancy-only PSK；每个事件的稳定 settlement 后棋盘进入历史，不稳定重建或提子中间棋盘不进入历史。若这些状态以事件、摘要或审计字段暴露，Gateway 和 Web 必须逐跳保真，不得合并或重排。

## 场景范围

未来场景至少覆盖：

- 建立会话、提交合法动作、提交拒绝动作和正常终局；
- `DOUBLE_START` 与 continuation 的同一行动方流程；
- settlement 前后事件、派生状态与界面呈现；
- 身份未分配和身份不匹配；
- 断线重连、Gateway 重启、C++ 进程故障、背压和超时；
- 权威事件日志回放及确定性派生；
- 多会话隔离、资源清理和错误脱敏。

## 非目标

- 不用浏览器测试替代规则级边界覆盖或 C++/Python 差分。
- 不在 Node、React 或测试代码中复制合法性、提子、自杀、PSK、结算、计分或终局算法。
- 不把搜索键、位置超级劫键与神经网络缓存键当作端到端会话身份。
- 不要求扩展 SGF 对全部特殊事件无损往返。
- 不在尚无可运行入口时宣称系统已具备端到端能力。

## 未冻结的测试设计

场景 DSL、选择器、超时、重试、并发、端口分配、浏览器矩阵、截图政策、可观测性、失败材料保留和 CI 拓扑均为 **UNFROZEN**。

## 实现准入

开始加入端到端测试代码前，至少需要：

1. Web、Gateway 与 C++ 均有可运行入口且责任边界已审查；
2. WebSocket Schema、C++ 进程协议、排序、错误、回放与重连语义已经明确；
3. 具有 hermetic、确定性的 C++ 场景夹具；
4. 会话隔离、资源清理、超时、重试和并发政策已经明确；
5. 浏览器运行时、测试框架、Node 工具链、模型及外部数据完成许可证、来源、安全与再分发审计。

## 相关文档

- [测试与一致性门槛](../../docs/设计文档/06-测试与一致性门槛.md)
- [系统架构与权威边界](../../docs/设计文档/01-系统架构与权威边界.md)
- [Web 客户端边界](../../apps/web/README.md)
- [Gateway 边界](../../services/gateway/README.md)
- [Schema 边界](../../schemas/README.md)
- [一致性测试边界](../conformance/README.md)

## English Summary

End-to-end tests cover the black-box production path from React through WebSocket and the thin Node gateway to the authoritative C++ engine. C++ alone emits authoritative game events; Python is excluded from this path and belongs to conformance testing. Tests must preserve the fixed Model V19, Inputs V9, Training Schema V1, and kind-major Action Schema V1 identifiers, including PASS at 1444. They also verify that the public `rulesetId` and descriptor canonicalization remain **UNFROZEN / unassigned**, the final descriptor SHA-256 remains **AUDIT-BLOCKED / unassigned**, authoritative JSON replay is preserved, and any exposed stable-settlement information is transported losslessly without recomputing rules in the browser or gateway.