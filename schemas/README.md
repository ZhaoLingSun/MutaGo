# Schema 边界

本目录保存 MutaGo 的版本化跨进程、跨语言和持久记录数据契约。M0 只加入权威 JSON Schema 源、规则描述符校验入口、黄金向量和合同示例；不包含规则归约器、生成绑定、包清单、CI、模型、数据或构建产物。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：玩法语义由规范规则文档定义，Schema 只能表达数据契约，不能取代生产规则裁决。
- **FROZEN**：Collapse Go 规则语义版本为 `0.1.0-draft`，公共 `rulesetId` 为 `mutago.collapse-go`。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **FROZEN**：规范描述符采用受限 RFC 8785/JCS profile，只接受 ASCII 字符串与键、安全有符号整数、布尔、`null`、数组和对象。
- **FROZEN**：初始空盘占据是 PSK 历史第零项；公开摘要是规范 UTF-8 字节的 lowercase SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一能够产生生产权威游戏事件的组件。
- Python 只产生独立参考预期；Node 只编排和执行结构校验；React 只发送意图并呈现权威状态。
- Schema 校验成功只表示数据满足结构合同，不表示动作合法、状态正确、计分有效或事件已经获得生产权威。
- C++ 产生的 JSON 事件序列是权威记录。快照、网关会话与扩展 SGF 均是派生或交换表示。
- Schema 不得把公开规则身份、搜索键、位置超级劫键与神经网络缓存键合并或互换。

## 已冻结的 ABI 合同

### 版本与尺寸

Schema 与描述符无歧义表达并校验以下固定版本：

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

任何语言绑定都必须保持 typed-action 身份，禁止只序列化裸位置或把四个动作块改成 point-major。canonical envelope 只包含 `schemaVersion`、`actionId` 和 `kind`；坐标由 `actionId` 唯一导出，冗余坐标和未知字段必须拒绝。9×9、13×13、19×19 均先映射到居中的 19×19 画布；棋盘 footprint 外的点动作必须拒绝。

### PSK 与 settlement 记录

官方规则采用 occupancy-only PSK。Schema 若承载 PSK 重放材料或 settlement trace，必须保留以下边界：

- 初始空盘占据固定为历史第零项；
- 每个玩家原子动作的稳定后盘面进入 PSK 历史；
- 每个 settlement event pop 的稳定闭包盘面也进入历史；
- tombstone/no-op pop 仍追加稳定盘面，并允许重复条目；
- 不稳定的重建、提子中间盘面不进入历史；
- PSK 不包含下一手玩家或其他规则元数据。

PSK 的运行时字节编码、哈希实现和存储布局不由本 M0 Schema 固定，但不得改变上述语义投影。

### MVP 终局与死子策略

描述符 Schema 固定当前 MVP 的确定性路径：不启用双方协商死子移除捷径，也不启用死子争议/恢复协议。post-settlement `ORDINARY_PLAY` 持续到两个连续 `PASS`，随后直接对当前稳定盘面计分。任何启用捷径或争议协议的描述符都必须拒绝；未来若增加该能力，必须使用新的语义版本、描述符和协议测试。

认输和游戏语义超时只在暴露的 `COLLAPSE_PLAY`（包括 pending Double）或 `ORDINARY_PLAY` 稳定边界接受。若管理终止先于候选动作提交，则立即终局，不提交候选动作、不运行 settlement 或面积计分；若动作先提交并触发 settlement，则完整闭包、PSK 追加和出口状态必须原子完成，内部不暴露终止或取消边界。终局事件追加未改变的稳定占据。请求/传输超时、断线和取消不是游戏 `TIMEOUT`。

## M0 权威源

`schemas/source/` 中的五个文件均使用 JSON Schema Draft 2020-12，并对未知字段采用关闭策略：

- `action-v1.schema.json`：Action Schema V1 的规范 typed-action 封装；
- `ruleset-descriptor-v1.schema.json`：Collapse Go 语义描述符与身份引用；
- `semantic-projection-v1.schema.json`：稳定状态、转移、PSK、账本、结算和合法动作投影；
- `conformance-fixture-v1.schema.json`：黄金、回归和合同示例夹具；
- `mismatch-bundle-v1.schema.json`：可复现差分前缀、双方观察、差异和最小化状态。

夹具或 mismatch bundle 使用 `descriptor: null` 时，Schema 会同时绑定当前公开身份和官方 19×19、双方 `1/1/1` 配置。非官方棋盘或配额必须内嵌完整描述符，并使用该描述符自身的规范摘要。

## 公开身份与规范化

当前公开身份三元组为：

```text
rulesetId:       mutago.collapse-go
semanticVersion: 0.1.0-draft
descriptorSha256: a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899
```

规范描述符采用 `rfc8785-jcs-ascii-safe-integer-v1`，规范 UTF-8 长度固定为 `14973` 字节；对象键按 UTF-16 code unit 字典序排序，公开摘要使用 lowercase SHA-256。内部 variant 枚举、仓库目录 slug、Git SHA、模型 SHA 和运行模式标签均不是公开规则身份。

受限 profile 只检查 JSON 词法、值域和规范字节：有效 UTF-8、无重复键、ASCII 字符串与键、安全有符号整数、布尔、`null`、数组和对象；浮点、非 ASCII 与超出 `[-9007199254740991,9007199254740991]` 的整数被拒绝。它不识别 descriptor 字段，也不拒绝任意 profile-valid 未知对象键。规范规则描述符还必须独立通过关闭式 `ruleset-descriptor-v1` Schema、描述符跨字段不变量和跨制品绑定；未知描述符字段由该验证层拒绝。独立 C++ 与 Python 实现必须产生完全相同的规范字节。

## 非目标

- 不在 JSON Schema、TypeScript 类型、C++ 结构体或 Python 数据类中实现生产规则算法。
- 不把任何 C++、Python、TypeScript 或生成语言绑定提升为规范语义描述符；权威来源仍是声明的 descriptor JSON 与源 Schema。
- 不把 Python 合同工具提升为生产规则权威或完整规则 oracle。
- 不让生成代码反向修改手写权威 Schema。
- 不在本目录定义网络拓扑、进程管理或客户端状态管理。

## 验证

使用仓库现有 Python 与已安装的 `jsonschema`：

```bash
python3 tools/contract/contract.py canonicalize FILE
python3 tools/contract/contract.py hash FILE
python3 tools/contract/contract.py validate ruleset-descriptor-v1 FILE
python3 tools/contract/contract.py check
python3 -m unittest discover -s tests/contracts -p 'test_*.py'
```

`canonicalize` 与 `hash` 只验证受限 JSON profile；成功不表示输入是有效规则描述符。`validate ruleset-descriptor-v1` 执行 profile、关闭式 descriptor Schema、公开描述符要求和跨字段不变量。`check` 会验证五个 Schema、自包含的本地 `$ref`、仓库规范描述符、规范化/identity/invalid-descriptor/action/D4 向量、全部合同示例和跨制品绑定，并输出公开哈希。

## 相关文档

- [输入特征 ABI V9](../docs/设计文档/04-输入特征ABI-V9.md)
- [协议与 Schema](../docs/设计文档/05-协议与Schema.md)
- [坍缩围棋规则集边界](../rulesets/collapse-go/README.md)
- [网关边界](../services/gateway/README.md)
- [一致性测试边界](../tests/conformance/README.md)

## English Summary

This directory owns the M0 executable data contracts, not a production reducer, search system, neural network, Gateway, or Web implementation. Five closed Draft 2020-12 source schemas define Action V1, the ruleset descriptor, semantic projections, conformance fixtures, and mismatch bundles. C++ remains the sole production rules authority; Python contract tooling validates structure and cross-artifact invariants only.

The public identity is `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`. The restricted profile governs JSON syntax, value domain, and canonical bytes only, accepting ASCII strings/keys, safe signed integers, booleans, null, arrays, and objects while rejecting floats, duplicate keys, non-ASCII data, unsafe integers, invalid UTF-8, and invalid number syntax. It does not validate descriptor fields. The 14,973-byte rules descriptor separately passes the closed descriptor schema, descriptor invariants, and cross-artifact bindings, which reject unknown fields and semantic mismatches. `canonicalize`/`hash` enforce only the profile; descriptor `validate` and repository `check` enforce Schema and applicable invariants.

Initial empty occupancy is PSK history entry zero. Action V1 is fixed at 1,445 kind-major actions; its canonical wire object contains exactly `schemaVersion`, `actionId`, and `kind`, with coordinates derived from the ID. Missing/unknown fields, unknown versions, redundant coordinates, and inconsistent `kind`/ID pairs fail closed. The MVP enables neither agreed dead-stone removal nor a dispute protocol. Administrative termination is accepted only at exposed stable boundaries: termination-first ends immediately without the candidate action, settlement, or scoring; action-first requires any triggered settlement to complete atomically before a later termination is considered. Operational timeouts and cancellation never synthesize game `TIMEOUT`. A null descriptor binding is valid only for the exact public identity and official 19x19, per-player 1/1/1 configuration; non-public configurations must embed and bind their own complete descriptor.
