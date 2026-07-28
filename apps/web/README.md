# Web 客户端

本目录预留给 MutaGo 的 React 与 TypeScript Web 客户端。当前只建立职责边界，不包含客户端源码、包清单、依赖、生成绑定、模型、数据或构建产物。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：客户端只负责用户交互与权威状态的呈现，不承担任何游戏规则裁决。
- **FROZEN**：Collapse Go `0.1.0-draft` 中已经写明的玩法语义是冻结语义；版本名中的 `draft` 不表示客户端可以自行补充或改变规则。
- **FROZEN**：模型与数据 ABI 版本为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **FROZEN**：公共规则身份为 `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`；规范描述符采用 `rfc8785-jcs-ascii-safe-integer-v1`，长度为 14,973 个规范 UTF-8 字节。目录名 `collapse-go` 仍只是仓库 slug，不是公共 `rulesetId`。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一能够产生生产权威游戏事件的组件。
- 浏览器只发送用户意图，并呈现由 C++ 接受后产生、经 Node 网关转发的事件、快照、会话状态和错误。
- 本地状态、乐观更新、缓存、动画、URL 与浏览器存储都不是权威游戏状态，不得覆盖或修补 C++ 事件流。
- 客户端不得独立判断合法性、提子、自杀、位置超级劫、结算、计分、行动方或终局。
- Python 参考实现不进入浏览器生产路径；它只能在一致性测试中产生参考预期。
- 由 C++ 产生的 JSON 事件序列是权威游戏记录。派生快照与扩展 SGF 不得取代该记录，客户端也不得从 SGF 恢复权威状态。

## 接口约束

客户端未来可以发送建局、动作、回放、重连和终止等意图。每个规范动作意图必须携带完整关闭式 Action V1 envelope，且恰含 `schemaVersion`、`actionId`、`kind`；坐标由 `actionId` 导出，缺字段、冗余坐标、未知字段或 `kind`/ID 不匹配必须失败关闭。`actionId` 原样使用 kind-major 编码，不得在前端重新编号：

- `NORMAL`：`0..360`
- `IMMORTAL`：`361..721`
- `DOUBLE_START`：`722..1082`
- `EIGHTWAY`：`1083..1443`
- `PASS`：`1444`

点动作满足 `a = 361*k + p`。动作是否可用必须由 C++ 权威状态决定；按钮禁用、候选提示或预测结果只能视为呈现信息。

规则身份字段必须端到端无损转发并与权威会话绑定。客户端必须拒绝未知或不匹配的三元组，不得把目录名、Git SHA、全零摘要、模型摘要或示例值伪装成公共身份，也不得用本地默认值替换 C++ 返回的身份。

包裹 Action V1 的产品/WebSocket 消息名、外层字段布局、帧、重连策略、缓存、状态管理、页面结构、无障碍要求和部署方式均为 **UNFROZEN**；这不重新开放其内部 Action V1 payload，后者固定且仅含 `schemaVersion`、`actionId`、`kind`。

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
4. 能验证身份匹配、未知身份、身份不匹配、拒绝动作、断线和终局等界面状态；
5. React、TypeScript、浏览器工具链及新增依赖完成许可证、来源、安全与再分发审计。

## 相关文档

- [系统架构与权威边界](../../docs/设计文档/01-系统架构与权威边界.md)
- [坍缩围棋规则](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)
- [协议与 Schema](../../docs/设计文档/05-协议与Schema.md)
- [Web 网关边界](../../services/gateway/README.md)
- [Schema 边界](../../schemas/README.md)
- [端到端测试边界](../../tests/end-to-end/README.md)

## English Summary

This directory is reserved for the future React and TypeScript client. The browser only sends user intent and renders events and derived views forwarded from the sole production authority, the C++ engine; it never decides rules or emits authoritative game events. Model V19, Inputs V9, Training Schema V1, and Action Schema V1 are fixed. Every canonical action payload is the closed `{schemaVersion, actionId, kind}` envelope; only its surrounding product/WebSocket envelope remains unfrozen. The assigned public identity is `mutago.collapse-go` / `0.1.0-draft` / `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`; the restricted-JCS descriptor is 14,973 canonical UTF-8 bytes. The client must preserve this identity and the kind-major `0..1444` action codec exactly, reject missing/redundant/unknown action fields and unknown or mismatched identities, and never substitute a slug, Git SHA, model digest, or local default.