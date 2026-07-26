# Web 客户端

本目录预留给 MutaGo 的 React 与 TypeScript Web 客户端。当前只建立职责边界，不包含客户端源码、包清单、依赖、生成绑定、模型、数据或构建产物。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：客户端只负责用户交互与权威状态的呈现，不承担任何游戏规则裁决。
- **FROZEN**：Collapse Go `0.1.0-draft` 中已经写明的玩法语义是冻结语义；版本名中的 `draft` 不表示客户端可以自行补充或改变规则。
- **FROZEN**：模型与数据 ABI 版本为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式。目录名 `collapse-go` 只是候选 slug，不是已分配的公共 `rulesetId`。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一能够产生生产权威游戏事件的组件。
- 浏览器只发送用户意图，并呈现由 C++ 接受后产生、经 Node 网关转发的事件、快照、会话状态和错误。
- 本地状态、乐观更新、缓存、动画、URL 与浏览器存储都不是权威游戏状态，不得覆盖或修补 C++ 事件流。
- 客户端不得独立判断合法性、提子、自杀、位置超级劫、结算、计分、行动方或终局。
- Python 参考实现不进入浏览器生产路径；它只能在一致性测试中产生参考预期。
- 由 C++ 产生的 JSON 事件序列是权威游戏记录。派生快照与扩展 SGF 不得取代该记录，客户端也不得从 SGF 恢复权威状态。

## 接口约束

客户端未来可以发送建局、动作、回放、重连和终止等意图。若协议暴露整数动作 ID，必须原样使用 Action Schema V1 的 kind-major 编码，不得在前端重新编号：

- `NORMAL`：`0..360`
- `IMMORTAL`：`361..721`
- `DOUBLE_START`：`722..1082`
- `EIGHTWAY`：`1083..1443`
- `PASS`：`1444`

点动作满足 `a = 361*k + p`。动作是否可用必须由 C++ 权威状态决定；按钮禁用、候选提示或预测结果只能视为呈现信息。

规则身份字段必须端到端无损转发。在公共身份尚未分配期间，客户端必须显示或保留明确的 `unassigned` 状态，不得把目录名、Git SHA、全零摘要或示例值伪装成公共身份。

消息名、字段布局、WebSocket 帧、重连策略、缓存、状态管理、页面结构、无障碍要求和部署方式均为 **UNFROZEN**。

## 非目标

- 不在浏览器中建立第二套规则引擎或 C++ 故障时的规则回退。
- 不把模式校验成功解释为动作合法。
- 不生成、比较或混用搜索键、位置超级劫键与神经网络缓存键。
- 不在本目录定义规则语义、公共规则身份、进程协议或持久化策略。

## 实现准入

开始加入客户端代码前，至少需要：

1. 版本化客户端协议、错误模型与兼容政策已经明确；
2. 网关的排序、回放、重连、背压和失败语义已经明确；
3. 具有由 C++ 权威实现产生的确定性事件与快照夹具；
4. 能验证身份未分配、身份不匹配、拒绝动作、断线和终局等界面状态；
5. React、TypeScript、浏览器工具链及新增依赖完成许可证、来源、安全与再分发审计。

## 相关文档

- [系统架构与权威边界](../../docs/设计文档/01-系统架构与权威边界.md)
- [坍缩围棋规则](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)
- [协议与 Schema](../../docs/设计文档/05-协议与Schema.md)
- [Web 网关边界](../../services/gateway/README.md)
- [Schema 边界](../../schemas/README.md)
- [端到端测试边界](../../tests/end-to-end/README.md)

## English Summary

This directory is reserved for the future React and TypeScript client. The browser only sends user intent and renders events and derived views forwarded from the sole production authority, the C++ engine; it never decides rules or emits authoritative game events. Collapse Go gameplay semantics documented for `0.1.0-draft` are frozen despite the draft label. Model V19, Inputs V9, Training Schema V1, and Action Schema V1 are fixed. The public `rulesetId` literal and canonical-descriptor encoding/canonicalization are **UNFROZEN / unassigned**, while the final public descriptor SHA-256 is **AUDIT-BLOCKED / unassigned**. Any exposed action IDs must preserve the kind-major `0..1444` codec exactly.