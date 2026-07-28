# 端到端测试

本目录预留给 MutaGo 生产链路的黑盒测试：`React 客户端 → WebSocket → Node 网关 → C++ 权威实现`，并观察 C++ 产生的权威 JSON 事件记录及其派生呈现。当前不包含测试源码、浏览器配置、夹具、依赖、模型、报告或 CI 配置。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：Collapse Go `0.1.0-draft` 已写明的玩法语义已经冻结；端到端测试只验证生产链路是否保真，不重新定义规则。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **FROZEN**：公共规则身份为 `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`；规范描述符采用 `rfc8785-jcs-ascii-safe-integer-v1`，长度为 14,973 个规范 UTF-8 字节。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一产生生产权威游戏事件的组件。
- Node 网关只编排、成帧和验证结构；React 只发送用户意图并呈现结果；测试浏览器不得重算规则结论。
- Python oracle 不进入生产端到端路径。C++/Python 规则差分、规则穷举与百万动作硬闸门属于[一致性测试](../conformance/README.md)。
- C++ 产生的 JSON 事件序列是权威记录。截图、DOM、网关内存、派生快照与扩展 SGF 都不是权威来源。
- 端到端断言中的已知游戏结果必须来自冻结的 C++ 场景夹具或 C++ 权威事件记录，而不是浏览器侧算法。

## 必测生产契约

### 动作与版本保真

生产链路必须逐跳保持 Model V19、Inputs V9、Training Schema V1 和 Action Schema V1 的版本信息。每个规范动作提交都必须逐跳携带完整关闭式 Action V1 envelope，且恰含 `schemaVersion`、`actionId`、`kind`。测试必须拒绝缺字段、冗余坐标、未知字段、未知 schema 版本、未知 kind 以及 kind/ID 不匹配，并原样保持下列 kind-major `actionId`：

| 动作 | ID 范围 |
|---|---:|
| `NORMAL` | `0..360` |
| `IMMORTAL` | `361..721` |
| `DOUBLE_START` | `722..1082` |
| `EIGHTWAY` | `1083..1443` |
| `PASS` | `1444` |

点动作满足 `a = 361*k + p`，坐标只能由 `actionId` 导出。测试应证明 Web 和 Gateway 不把 envelope 降级为裸 ID、裸位置或 `{kind,loc}`，不重新编号动作族，也不在拒绝后伪造权威事件。

### 身份与回放

所有相关握手、会话、事件和回放场景都必须逐跳保持完整公共身份三元组。测试必须接受精确匹配的已分配身份，并拒绝未知或不匹配的 `rulesetId`、语义版本、描述符摘要，以及把目录 slug `collapse-go`、Git SHA、全零摘要、模型摘要或示例值冒充公共身份的情况。

回放测试必须从 C++ 权威 JSON 事件记录恢复派生状态，并验证事件排序、日志位置、身份状态和重连结果。扩展 SGF 只验证已声明的交换行为与损失模型，不承担权威恢复。

### settlement 可观察结果

端到端层不重新计算 PSK，但必须验证协议和日志没有丢失 C++ 提供的规则意义信息。官方规则采用 occupancy-only PSK；每个事件的稳定 settlement 后棋盘进入历史，不稳定重建或提子中间棋盘不进入历史。若这些状态以事件、摘要或审计字段暴露，Gateway 和 Web 必须逐跳保真，不得合并或重排。

## 场景范围

未来场景至少覆盖：

- 建立会话、提交合法动作、提交拒绝动作和正常终局；
- `DOUBLE_START` 与 continuation 的同一行动方流程；
- settlement 前后事件、派生状态与界面呈现；
- 精确公共身份、未知身份和身份不匹配；
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

End-to-end tests cover the black-box production path from React through WebSocket and the thin Node gateway to the authoritative C++ engine. C++ alone emits authoritative game events; Python is excluded from this path and belongs to conformance testing. Tests must preserve Model V19, Inputs V9, Training Schema V1, and every closed Action V1 `{schemaVersion, actionId, kind}` envelope, including the kind-major codec and PASS at 1444; missing, redundant, unknown, version-mismatched, or kind/ID-inconsistent fields fail closed. They also preserve the exact public identity `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`, reject unknown or mismatched identities, preserve authoritative JSON replay, and transport any exposed stable-settlement information losslessly without recomputing rules in the browser or gateway.