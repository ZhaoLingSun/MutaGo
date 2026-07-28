# 一致性测试

本目录用于 C++ 生产权威实现与独立 Python 参考实现之间的确定性一致性和差分测试。M0 已在 `tests/contracts/` 提供可执行合同示例与测试；本目录现有一个仅覆盖 `NORMAL` / `PASS`、空账本 settlement 与普通计分路径的独立 Python 慢速参考切片，并加入明确标为 **UNFROZEN v0、仅测试排练** 的独立 C++ JSONL probe 与 Python 差分驱动。它们仍不是完整特殊能力 oracle、生产协议、冻结语义投影、百万动作夹具、门槛报告或 CI 配置。

## 文档状态

- **FROZEN**：固定上游基线为 KataGo stable v1.16.5，提交 `ba938676d7f42d70950b3a535af2466fb642008c`。
- **FROZEN**：Collapse Go `0.1.0-draft` 已写明的玩法语义已经冻结；测试不得把 `draft` 当作自行发明预期的理由。
- **FROZEN**：版本组合为 Model V19、Inputs V9、Training Schema V1、Action Schema V1。
- **FROZEN**：公共身份为 `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`；夹具必须精确绑定该三元组或内嵌不同配置的完整描述符。
- **FROZEN**：初始空盘占据是 PSK 历史第零项；MVP 不启用死子协商；Action V1 canonical envelope 恰含 `schemaVersion`、`actionId`、`kind`。

## 权威边界

- C++ 是唯一生产规则与搜索权威，也是唯一产生生产权威事件的实现。
- Python 是独立、刻意较慢的参考 oracle，只产生参考接受/拒绝结果、参考状态投影和参考事件预期。
- Python 输出不得称为“权威事件”，不得进入生产请求路径，也不得自动覆盖 C++。
- C++ 与 Python 的任何有意义差异都必须使测试失败并进入调查；C++ 的生产权威地位不允许静默忽略差异，Python 的参考地位也不允许自动裁决差异。
- 两侧不得共享 Collapse Go 状态转移实现、由同一核心生成预期，或使用会删除规则意义差异的归一化。

## 当前 Python NORMAL/PASS 参考切片

`../../python/mutago/collapse_go/normal_pass_oracle.py` 是独立、仅使用 Python 标准库的慢速参考切片。当前范围包括：

- Action V1 关闭式 envelope 的严格解码，以及 9×9、13×13、19×19 居中 footprint；
- 每方各能力 0 或 1 的可配置配额；
- `NORMAL` 的全盘 N4 棋块/气重建、同时提走全部对方零气棋块、自杀与 occupancy-only PSK；
- `PASS` 的 PSK 拒绝豁免、重复稳定占据追加、阈值或阈值前双停着触发的空账本 settlement；
- settlement 后两次新停着、当前稳定盘面的中国式面积计分、7.5 贴目和终局事件的重复 PSK 追加；
- 冻结的适用拒绝优先级，包括 `POINT_OFF_BOARD` 先于终局、阶段和行动者检查；零配额特殊动作的 `QUOTA_EXHAUSTED`，以及普通阶段特殊动作的 `INVALID_PHASE`。

该切片不复用 `python/katago/game`、`tools/contract` 的规则决定辅助函数或 C++。非零配额且通过前置检查的潜在合法特殊动作会显式抛出 `UnsupportedSliceAction`，而不会伪造语义拒绝。Immortal、Double、Eightway 的实际能力语义、非空特殊事件账本与 Double continuation 仍未实现。oracle 包自身保持无 subprocess、无 JSONL transport、无 C++ 依赖；下节的外部测试驱动单独负责启动 probe。

从仓库根目录运行当前切片测试：

```bash
PYTHONPATH=python python3 -m unittest -v tests/conformance/test_python_normal_pass_oracle.py
```

这些测试证明的是上述受限切片的本地行为，不表示完整 Python oracle、完整 C++ reducer、一致性驱动、`GATE-RULE-1M` 或 `GATE-PROD` 已完成或通过。

## NORMAL/PASS 差分排练：UNFROZEN v0，仅测试

`../../cpp/tests/collapsereducerprobe.cpp` 与 `normal_pass_differential.py` 构成一个明确隔离的排练载体：

- CMake 目标名为 `mutago-collapse-slice-probe`，使用 `EXCLUDE_FROM_ALL`，不进入默认构建，也不是生产 gameplay 入口；
- 请求协议版本字面值为 `normal-pass-diff-v0-unfrozen`。每行是一个完整 episode，关闭式字段为 `protocolVersion`、`episodeId`、`boardSize`、`quotaMode`、`steps`；每步恰含 `candidateActor` 与冻结的 Action V1 envelope；
- `boardSize` 仅允许 `9`、`13`、`19`，`quotaMode` 仅允许 `ZERO` 或 `ONE`。`episodeId` 是 1–128 字符的 ASCII 测试标识符；每个 episode 最多 160 步，canonical 请求与原始输入行均不得超过 1 MiB，canonical 响应行不得超过 16 MiB；
- probe 使用现有 `RulesetIdentity::parseRestrictedJson`、`GameAction::ofJson` 和受限 profile canonicalizer，并以预分配的有界 reader 读取每一行；Windows 上显式把 stdin/stdout 切换为二进制模式。结构错误、未知字段、错误版本、重复键、非规范 Action V1、超长行、缺少最终换行或资源上限错误均使当前完整 frame fail closed；不输出部分 episode，诊断仅写 stderr；
- 每步响应精确包含接受、拒绝或 `UNSUPPORTED` 状态、错误码、按颜色拆分的 board-local 捕获点、settlement 原因、终局计分事件标志、黑白占据、actor、phase、`A`、连续停着、剩余配额、完整有序 occupancy-only PSK 历史及半目整数计分投影；
- Python 驱动强制并核验 oracle 模块来自当前 checkout 的 `python/`，先构造完整有界语料，再用独立 writer 与有界 reader 线程启动外部 probe；stdout 总量限制为 64 MiB，stderr 限制为 1 MiB，超限或 deadline 到达即终止子进程。独立 oracle 包本身仍不调用 subprocess；驱动校验响应行数、16 MiB 单行上限、canonical JSON、所有关闭式嵌套类型/枚举、逐字段值和逐列表顺序，并在首个差异停止比较；
- 随机语料只使用零配额，随机源是版本化的 SHA-256 counter 字节流。随机固定结构覆盖 9/13/19、全部 1445 个 Action V1 ID、当前行动者 `NORMAL` / `PASS`、错误行动者、footprint 外 ID、已占点、settlement 后和终局后候选；全 ID episode 按 160 步边界拆帧。额外人工 episode 保证三个棋盘都恰在 `A=T` 比较 threshold settlement；`ONE` 配额仅用于人工用例中的前置拒绝与明确 `UNSUPPORTED`；
- CLI 的必需 `--probe`、`--seed`、`--candidate-count` 分别控制显式可执行文件路径、确定性种子与零配额随机候选数；当前随机语料边界把候选数限制为 1478–10000。失败诊断携带 seed、生成器版本、候选数、canonical 请求和截至首个差异的动作前缀；成功时只打印一行确定性 canonical JSON 摘要和 transcript SHA-256；

从仓库根目录构建和运行：

```bash
cmake -S cpp -B build/collapse-slice -DUSE_BACKEND=EIGEN -DUSE_AVX2=1
cmake --build build/collapse-slice \
  --target mutago-collapse-slice-probe --config RelWithDebInfo -j4
PYTHONPATH=python python3 tests/conformance/normal_pass_differential.py \
  --probe build/collapse-slice/mutago-collapse-slice-probe \
  --seed mutago-normal-pass-rehearsal \
  --candidate-count 10000
```

多配置生成器通常把可执行文件放在 `build/collapse-slice/RelWithDebInfo/` 等配置子目录；此时必须把该实际路径显式传给 `--probe`，Windows 文件名还包含 `.exe`。

标准库单元测试默认不启动可执行文件；设置环境变量后会额外运行 opt-in 集成测试和 malformed-frame 检查：

```bash
PYTHONPATH=python python3 -m unittest -v \
  tests/conformance/test_normal_pass_differential.py

MUTAGO_COLLAPSE_SLICE_PROBE="$PWD/build/collapse-slice/mutago-collapse-slice-probe" \
PYTHONPATH=python python3 -m unittest -v \
  tests/conformance/test_normal_pass_differential.py
```

该载体只是当前受限切片的排练。其 frame 字段与摘要格式保持 **UNFROZEN**，不得称为 `semantic-projection-v1`、生产协议、完整 C++ reducer、完整 Python oracle、完整特殊能力差分、`GATE-RULE-1M` 或 `GATE-PROD` 证据。`10000` 只是本排练的随机候选数，不是百万动作门槛，也不能与未来影响语义的修改前后计数合并。

## 必测冻结契约

### Typed action 与 ABI

必须覆盖 Action Schema V1 的全部 1445 个 ID，并验证 encode/decode 双射与 kind-major 布局：

- `NORMAL`：`0..360`
- `IMMORTAL`：`361..721`
- `DOUBLE_START`：`722..1082`
- `EIGHTWAY`：`1083..1443`
- `PASS`：`1444`

点动作公式为 `a = 361*k + p`。测试必须证明同一点的四种动作不被折叠，D4 变换不改变动作族且 `PASS` 始终保持 `1444`。canonical Action V1 envelope 必须恰含 `schemaVersion`、`actionId`、`kind`；缺字段、冗余坐标、未知字段、未知版本和 kind/ID 不匹配均须拒绝。

### 位置超级劫与 settlement

官方 Collapse Go 使用 occupancy-only PSK。至少验证：

1. PSK 只比较黑白占据，不包含下一手玩家；
2. 原子动作直接后果的稳定闭包按规则进入历史；
3. settlement 每弹出一个事件并达到稳定闭包后都追加该棋盘；
4. tombstone pop 也追加稳定棋盘，允许重复历史条目；
5. settlement 内部产生的重复自动获准，但约束后续玩家动作；
6. 重建和提子的不稳定中间棋盘不进入历史；
7. 初始化时初始空盘占据恰为历史第零项且是唯一条目；测试必须拒绝省略、关闭或改变该播种的实现与夹具。

### 规则、事件与回放

覆盖范围必须包括合法性、提子、自杀、三种能力、配额、Double start 与 continuation、行动方、结算顺序、MVP 禁用死子协商、终局、计分、JSON 事件回放和身份不匹配。管理终止须覆盖两种串行顺序：若认输/游戏超时先于候选动作提交，则只提交立即终局，不提交动作、settlement 或计分；若动作先提交并触发 settlement，则完整闭包和出口状态先提交，settlement 内任何位置都不得接受终止或取消。请求/传输超时、断线和取消不得合成游戏 `TIMEOUT`。

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

M0 `conformance-fixture-v1`、`semantic-projection-v1` 和 `mismatch-bundle-v1` 的关闭式字段布局已经冻结。后续 reducer/oracle 随机生成器、种子分层、缩减调度、报告格式、浮点容差和失败分流流程仍为 **UNFROZEN**。任何归一化都不得删除动作类型、事件顺序、管理终止顺序、稳定 settlement 棋盘、PSK 上下文或身份状态等规则意义信息。

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

Conformance tests compare the sole C++ production authority with an independently implemented slow Python oracle. The directory contains a standard-library-only Python reference slice for strict Action V1 decoding, NORMAL/PASS play, full-scan N4 capture and suicide, ordered occupancy-only PSK, empty-ledger settlement, and exact ordinary-play Chinese area scoring. It also contains an explicitly test-only, **UNFROZEN v0** rehearsal: the `mutago-collapse-slice-probe` target is excluded from the default build and exchanges complete-episode canonical JSONL frames with an external Python driver under protocol literal `normal-pass-diff-v0-unfrozen`. The probe reuses the existing restricted JSON and Action V1 parsers, fails closed without a partial frame on malformed input, keeps diagnostics on stderr, and uses binary stdin/stdout on Windows. The driver forces and verifies that oracle modules come from this checkout, uses a versioned SHA-256 counter stream, covers all 1,445 action IDs plus structured legal and illegal candidates and explicit `A=T` settlement on centered 9×9, 13×13, and 19×19 zero-quota states, validates every closed nested response shape, compares every projected field and ordered PSK entry exactly, and stops at the first comparison mismatch with reproducible manifest, request, and action-prefix context. Requests are bounded to 160 steps and 1 MiB; canonical response lines are bounded to 16 MiB; aggregate subprocess stdout and stderr are bounded to 64 MiB and 1 MiB respectively and are consumed by bounded reader threads under a corpus deadline. Subprocess use is confined to this external harness; the independent oracle package remains subprocess-free. Nonzero potentially legal specials remain explicit `UnsupportedSliceAction` / `UNSUPPORTED`, while special-ability mechanics, nonempty ledgers, Double continuation, per-special settlement pops, and unstable settlement reconstruction states are not implemented or claimed as covered. The frozen identity is `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`. Current coverage enforces the closed `schemaVersion`/`actionId`/`kind` Action V1 envelope, the 1,445-way kind-major codec, initial empty occupancy as PSK entry zero, stable NORMAL/PASS and scored-terminal appends, and no synthetic PSK append for empty-ledger settlement. The MVP has no dead-stone negotiation. Future complete tests must arbitrate termination-first versus action-first ordering: immediate administrative termination is valid only at exposed stable boundaries before an action commits, while a committed action’s triggered settlement completes atomically and exposes no internal command boundary. Operational timeouts and cancellation never synthesize game `TIMEOUT`. The early gate compares at least one million reproducible legal and structured-illegal candidate atomic actions with zero reproducible semantic differences before search, product, or training-data production depends on the rules. This rehearsal is not `semantic-projection-v1`, a production protocol, a full reducer or oracle, or evidence for `GATE-RULE-1M` or `GATE-PROD`; a 10,000-candidate run is not the million-action gate.