# 一致性测试

本目录预留给 C++ 生产权威实现与独立 Python 参考实现之间的确定性一致性和差分测试。当前不包含测试源码、夹具、依赖、模型、报告或 CI 配置。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：Collapse Go `0.1.0-draft` 已写明的玩法语义已经冻结；测试不得把 `draft` 当作自行发明预期的理由。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **UNFROZEN / unassigned**：公共 `rulesetId` 的最终字面值，以及规范语义描述符的字段、编码和规范化方式；夹具必须显式表示未分配状态。
- **AUDIT-BLOCKED / unassigned**：依赖最终规范字节和独立审计的公开描述符 SHA-256。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一产生生产权威事件的实现。
- Python 是独立、刻意较慢的参考 oracle，只产生参考接受/拒绝结果、参考状态投影和参考事件预期。
- Python 输出不得称为“权威事件”，不得进入生产请求路径，也不得自动覆盖 C++。
- C++ 与 Python 的任何有意义差异都必须使测试失败并进入调查；C++ 的生产权威地位不允许静默忽略差异，Python 的参考地位也不允许自动裁决差异。
- 两侧不得共享 Collapse Go 状态转移实现、由同一核心生成预期，或使用会删除规则意义差异的归一化。

## 必测冻结契约

### Typed action 与 ABI

必须覆盖 Action Schema V1 的全部 1445 个 ID，并验证 encode/decode 双射与 kind-major 布局：

- `NORMAL`：`0..360`
- `IMMORTAL`：`361..721`
- `DOUBLE_START`：`722..1082`
- `EIGHTWAY`：`1083..1443`
- `PASS`：`1444`

点动作公式为 `a = 361*k + p`。测试必须证明同一点的四种动作不被折叠，D4 变换不改变动作族且 `PASS` 始终保持 `1444`。

### 位置超级劫与 settlement

官方 Collapse Go 使用 occupancy-only PSK。至少验证：

1. PSK 只比较黑白占据，不包含下一手玩家；
2. 原子动作直接后果的稳定闭包按规则进入历史；
3. settlement 每弹出一个事件并达到稳定闭包后都追加该棋盘；
4. tombstone pop 也追加稳定棋盘，允许重复历史条目；
5. settlement 内部产生的重复自动获准，但约束后续玩家动作；
6. 重建和提子的不稳定中间棋盘不进入历史；
7. 初始空盘播种在描述符分配前保持未决，测试不得擅自冻结任一答案。

### 规则、事件与回放

覆盖范围必须包括合法性、提子、自杀、三种能力、配额、Double start 与 continuation、行动方、结算顺序、终局、计分、JSON 事件回放和身份不匹配。

对每个中立用例，应比较：

- C++ 的权威接受/拒绝结果、权威事件、下一状态、行动方、终局与计分；
- Python 的对应参考预期；
- 从 C++ 权威 JSON 事件前缀重放得到的确定性结果。

比较报告必须用“C++ 权威结果”和“Python 参考预期”区分两侧，不得写成“两套权威事件”。

### 三类键域

搜索键、位置超级劫键和神经网络缓存键必须分别验证其命名空间、字段、生命周期和失效条件。测试不得只比较一个共同哈希值，也不得因当前碰撞结果相同就宣称键域等价。

## 早期硬闸门

在 Collapse Go 搜索集成、生产玩法协议、Gateway/Web 产品路径、自博弈、训练数据生产或模型训练依赖该规则之前，C++ 与 Python 的规则实现必须通过确定性夹具、边界用例和至少 `1,000,000` 个可复现的合法与非法候选原子动作比较，逐项比较完整规则语义投影，并要求零个可复现语义差异。生成器必须混入结构化非法候选，不能只使用某一实现返回的合法动作列表。后续生产者与发行准入可以增加协议、模型和端到端测试，但不得把这个早期规则闸门推迟到产品链路之后。

## 未冻结的测试设计

夹具格式、随机种子、生成器、缩减策略、允许忽略字段、报告格式、容差和失败分流流程仍为 **UNFROZEN**。任何归一化都不得删除动作类型、事件顺序、稳定 settlement 棋盘、PSK 上下文或身份状态等规则意义信息。

扩展 SGF 只测试已声明的交换能力和损失模型；不得预先要求所有特殊动作、settlement 和终局状态都能 JSON → SGF → JSON 无损往返。

## 实现准入

开始加入一致性测试代码前，至少需要：

1. 每个用例都有冻结规则依据；
2. C++ 与 Python 的实现和审查路径保持独立；
3. 中立夹具、确定性种子、比较字段和最小化策略已经明确；
4. 差异分流能够区分 C++ 缺陷、Python 缺陷、规则歧义、Schema 缺陷和夹具缺陷；
5. 测试框架、属性测试库及外部夹具完成许可证、来源、安全与再分发审计。

## 相关文档

- [测试与一致性门槛](../../docs/设计文档/06-测试与一致性门槛.md)
- [坍缩围棋规范规则](../../docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)
- [输入特征 ABI V9](../../docs/设计文档/04-输入特征ABI-V9.md)
- [坍缩围棋规则集边界](../../rulesets/collapse-go/README.md)
- [端到端测试边界](../end-to-end/README.md)

## English Summary

Conformance tests compare the sole C++ production authority with an independently implemented slow Python oracle. C++ emits authoritative events; Python emits reference expectations only. Any meaningful mismatch fails the test and requires triage. Coverage must enforce the frozen 1445-way kind-major action codec, occupancy-only PSK, and the rule that every accepted event’s stable post-state—including Pass—and every stable settlement closure enter PSK history while unstable intermediates do not. The early gate compares at least one million reproducible legal and structured-illegal candidate atomic actions with zero reproducible semantic differences before search, production gameplay protocol, product, or training-data production depends on the rules. The public `rulesetId` and descriptor canonicalization are **UNFROZEN / unassigned**; the final descriptor SHA-256 is **AUDIT-BLOCKED / unassigned**.