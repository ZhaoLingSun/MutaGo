# 一致性测试

本目录用于 C++ 生产权威实现与独立 Python 参考实现之间的确定性一致性和差分测试。M0 已在 `tests/contracts/` 提供可执行合同示例与测试；本目录保留明确标为 **UNFROZEN v0、仅测试排练** 的 NORMAL/PASS C++ JSONL probe 与 Python 差分驱动，并提供与旧模式严格分离的 **UNFROZEN Double Increment 1**、**UNFROZEN Immortal Increment 2** 和 **UNFROZEN Eightway Increment 3** 测试载体。四种协议都不是生产协议、百万动作夹具、门槛报告或 CI 配置。

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

## 当前 Python 完整特殊能力参考实现

`../../python/mutago/collapse_go/normal_pass_oracle.py` 是独立、仅使用 Python 标准库的慢速参考切片。当前范围包括：

- Action V1 关闭式 envelope 的严格解码，以及 9×9、13×13、19×19 居中 footprint；
- 底层 `OracleConfig` / `PlayerQuotas` 接受满足状态一致性与配额守恒的非负 JSON-safe 整数；外部测试载体刻意更窄：legacy v0 只暴露 `quotaMode=ZERO/ONE`，Double Increment 1、Immortal Increment 2 与 Eightway Increment 3 的 `initialQuotas` 每个分量分别只允许 `0..4`；这四个 carrier 范围都不能倒推为 oracle 的配额域；
- `NORMAL` 的全盘 N4 棋块/气重建、同时提走全部对方零气棋块、自杀与 occupancy-only PSK；
- `PASS` 的 PSK 拒绝豁免、重复稳定占据追加、阈值或阈值前双停着触发的空账本 settlement；
- `DOUBLE_START` 的独立 N4 起手事务、同方 `NORMAL` / `PASS` 续着、pending linkage、来源身份、逐玩家配额、append-only tombstone 账本、被提 Double source、全局 newest-to-oldest no-op settlement pop，以及 revision/log/PSK/terminal 计数公式；
- `IMMORTAL` 真眼零气落子、动态 N4 同色整组保护、普通子与 Double 接入受保护零气组、受保护对方组的提子排除、锚点来源与生命周期、全局 newest-to-oldest settlement 停用/移除和稳定闭包 PSK 追加；
- `EIGHTWAY` 锚点的 N8 气、任一端为活动 E 锚时的同色对角连接、肩点不切断、普通/敌色对角分离、气去重、通过当前混合棋块传播 Immortal 保护，以及 E 停用后的可达 split/removal；
- settlement 后两次新停着、当前稳定盘面的中国式面积计分、7.5 贴目和终局事件的重复 PSK 追加；
- 冻结的适用拒绝优先级，包括 `POINT_OFF_BOARD` 先于终局、阶段和行动者检查；零配额特殊动作的 `QUOTA_EXHAUSTED`，pending Double 禁止的续着种类，以及普通阶段特殊动作的 `INVALID_PHASE`。

该实现不复用 `python/katago/game`、`tools/contract` 的规则决定辅助函数或 C++。oracle 包自身保持无 subprocess、无 JSONL transport、无 C++ 依赖；外部测试驱动单独负责启动 probe。旧 v0/v1/v2 adapter 不扩大历史协议范围：对于 EIGHTWAY，off-board、terminal、phase、actor、pending-kind、quota、occupied 等 mechanics 前拒绝保持原错误；候选一旦到达 mechanics，接受、`SUICIDE` 或 `POSITIONAL_SUPERKO` 均映射为历史 `UNSUPPORTED_BY_SLICE`，并精确回滚。v0/v1 对 Immortal 的既有对应边界同样保持不变。

从仓库根目录运行当前切片测试：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS='error::ResourceWarning' \
PYTHONPATH=python python3 -m unittest -v \
  tests/conformance/test_python_normal_pass_oracle.py \
  tests/conformance/test_python_double_move_oracle.py \
  tests/conformance/test_python_double_integer_bounds.py \
  tests/conformance/test_python_exact_state_parity.py \
  tests/conformance/test_python_immortal_exact_state.py \
  tests/conformance/test_python_immortal_oracle.py \
  tests/conformance/test_python_eightway_oracle.py
```

这些测试证明的是共享 Python oracle 的本地完整特殊能力行为；它们不提供完整 runtime legal-mask、管理终止、持久化、搜索或产品路径证据，也不表示 `GATE-RULE-1M` 或 `GATE-PROD` 已完成或通过。

## NORMAL/PASS 差分排练：UNFROZEN v0，仅测试

`../../cpp/tests/collapsereducerprobe.cpp` 与 `normal_pass_differential.py` 构成一个明确隔离的排练载体：

- CMake 目标名为 `mutago-collapse-slice-probe`，使用 `EXCLUDE_FROM_ALL`，不进入默认构建，也不是生产 gameplay 入口；
- 请求协议版本字面值为 `normal-pass-diff-v0-unfrozen`。每行是一个完整 episode，关闭式字段为 `protocolVersion`、`episodeId`、`boardSize`、`quotaMode`、`steps`；每步恰含 `candidateActor` 与冻结的 Action V1 envelope；
- `boardSize` 仅允许 `9`、`13`、`19`，`quotaMode` 仅允许 `ZERO` 或 `ONE`。`episodeId` 是 1–128 字符的 ASCII 测试标识符；每个 episode 最多 160 步，canonical 请求与原始输入行均不得超过 1 MiB，canonical 响应行不得超过 16 MiB；
- probe 使用现有 `RulesetIdentity::parseRestrictedJson`、`GameAction::ofJson` 和受限 profile canonicalizer，并以预分配的有界 reader 读取每一行；Windows 上显式把 stdin/stdout 切换为二进制模式。结构错误、未知字段、错误版本、重复键、非规范 Action V1、超长行、缺少最终换行或资源上限错误均使当前完整 frame fail closed；不输出部分 episode，诊断仅写 stderr；
- 每步响应精确包含接受、拒绝或 `UNSUPPORTED` 状态、错误码、按颜色拆分的 board-local 捕获点、settlement 原因、终局计分事件标志、黑白占据、actor、phase、`A`、连续停着、剩余配额、完整有序 occupancy-only PSK 历史及半目整数计分投影；
- Python 驱动强制并核验 oracle 模块来自当前 checkout 的 `python/`，先构造完整有界语料，再用独立 writer 与有界 reader 线程启动外部 probe；stdout 总量限制为 64 MiB，stderr 限制为 1 MiB。支持的平台上 probe 在独立 session/process group 中运行；超限或 deadline 到达时终止并强制结束整个组，关闭本地管道，所有线程 join 都受 deadline 约束，因此直接子进程退出但继承管道的孙进程不能造成无界等待。Windows 路径仍以关闭管道和有界 join fail closed。独立 oracle 包本身仍不调用 subprocess；驱动校验响应行数、16 MiB 单行上限、canonical JSON、所有关闭式嵌套类型/枚举、逐字段值和逐列表顺序，并在首个差异停止比较；
- 随机语料只使用零配额，随机源是版本化的 SHA-256 counter 字节流。随机固定结构覆盖 9/13/19、全部 1445 个 Action V1 ID、当前行动者 `NORMAL` / `PASS`、错误行动者、footprint 外 ID、已占点、settlement 后和终局后候选；全 ID episode 按 160 步边界拆帧。额外人工 episode 保证三个棋盘都恰在 `A=T` 比较 threshold settlement；`ONE` 配额仅用于人工用例中的前置拒绝与明确 `UNSUPPORTED`；
- CLI 的必需 `--probe`、`--seed`、`--candidate-count` 分别控制显式可执行文件路径、确定性种子与零配额随机候选数；当前随机语料边界把候选数限制为 1478–10000。失败诊断携带 seed、生成器版本、候选数、canonical 请求和截至首个差异的动作前缀；成功时只打印一行确定性 canonical JSON 摘要和 transcript SHA-256。集成回归另外固定 `opt-in-integration` / `1600` 的完整 legacy 摘要与历史 digest `297e38b15aae76e507d71e7bda1fb38b0d320ed102fd6f99644c6ed758051cf1`，并以一个原本会提子的合法 `DOUBLE_START` 证明 v0 adapter 返回 `UNSUPPORTED` 且丢弃试探占位、提子和配额变化；新增的合法交替包围中心 E 自杀与 E-ko/PSK 回归只验证历史 mechanics-boundary 映射和完整回滚，不进入固定默认 corpus，因而不改变该摘要或 digest；

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

## Double Increment 1 一致性载体：UNFROZEN，仅测试

`collapsereducerprobe.cpp` 在不改变旧 `normal-pass-diff-v0-unfrozen` 请求/响应的前提下，另行接受 `double-move-diff-v1-unfrozen`。新模式仍复用同一个 `EXCLUDE_FROM_ALL` 测试目标 `mutago-collapse-slice-probe`，不是新增生产入口，也不需要新的 CMake target。

新模式的关闭式 episode 字段为 `protocolVersion`、`episodeId`、`boardSize`、`initialQuotas`、`steps`；每步仍恰含 `candidateActor` 与冻结 Action V1 envelope。它明确限制：每帧请求最多 1 MiB、每帧响应最多 32 MiB、每 episode 最多 160 步、测试配额分量为 `0..4`、子进程 stdout 总量最多 256 MiB、stderr 最多 1 MiB、完整 corpus deadline 为 180 秒。`run_differential` 入口只创建一个绝对 monotonic deadline，并把该原始绝对时间点直接传入 probe supervisor，不根据 handoff 时的 remaining duration 重新起算；同一 deadline 贯穿受限夹具加载/Schema 与不变量验证、语料生成、Python oracle、probe pre-launch/supervision/termination/管道关闭/wait/join、响应解析、精确比较、D4，以及确定性动作重执行和不可变前缀检查；任何阶段耗尽预算都 fail closed。Python 驱动继续强制 oracle 与合同工具从当前 checkout 导入，并使用版本化 SHA-256 counter seed；首个逐值差异以及 invalid-UTF-8 stdout、malformed/non-newline/响应行数错误都报告 manifest、response index、canonical request 与已知完整动作前缀。Double digest manifest 使用 `randomCandidateCount` 表示请求的纯随机候选数；成功摘要中的 `candidateCount` 才表示 curated 与 random 的总和。当前默认 `mutago-double-increment-1` / `512` 回归固定 digest 为 `644a4401cbc3adb7a09b787b84fb3ce54d60f6f63c8692a4e04192ab592eed15`。

每步比较的规范化测试投影包括：

- 接受、拒绝或显式 `UNSUPPORTED`，稳定错误码、candidate actor、Action V1、捕获和 PSK append 数；
- actor、phase、`A`、PASS 连计、pending Double、revision、log position、settled-ledger 与 stable-terminal 计数；
- 双方 initial/remaining/used/expired 完整配额；
- source-aware stones、N4 groups/liberties、append-only Double ledger 的 identity/lifecycle/tombstone/captured/settled 状态；
- 完整有序 occupancy-only PSK，包括 PASS、settlement tombstone/no-op 与 terminal 产生的重复；
- settlement 原因、handoff actor、全局 newest-to-oldest pop、每步 no-op/removal trace 与连续 PSK index；
- 当前 terminal state 与计分事件。

`double_move_differential.py` 以 checkout-pinned `tools.contract.contract.parse_json_bytes` 严格读取 `../contracts/examples/conformance-fixture-double-settlement-v1.example.json`；重复键及转义别名、浮点/非有限常量、unsafe integer、非 ASCII/孤立 surrogate 字符串或键、非法 UTF-8 均在进入夹具验证前拒绝。现有合同工具随后验证完整 Schema、语义不变量与 debug groups；外部驱动再逐字绑定 checked-in `derived.legalActionRanges`，防止合法范围被缩窄或漂移。合同 helper 只负责语法、Schema 与合同不变量，不参与 Python oracle 的玩法决定。两种实现只把 Increment 1 实际可执行字段归一化并逐项精确比较；夹具 envelope 不进入 reducer，也不被当作生产格式。额外语料覆盖 9/13/19 的八种 D4、source/action/capture/PASS/settlement/terminal 变换及 inverse round-trip、pending/settlement 边界的确定性动作重执行与不可变精确前缀、错误 actor、禁止续着种类、阈值边界、配额耗尽、占用、自杀、PSK、被提 Double source、多账本项、PASS continuation、阈值和双 PASS settlement。这里的“重执行/前缀”不是 JSON 权威事件日志重放、serialized checkpoint recovery、生产持久化恢复或公共 undo/redo 证据。

从仓库根目录运行：

```bash
cmake -S cpp -B build/collapse-increment1 -DUSE_BACKEND= -DUSE_AVX2=1
cmake --build build/collapse-increment1 \
  --target mutago-collapse-slice-probe --config RelWithDebInfo -j4

PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS='error::ResourceWarning' \
PYTHONPATH=python python3 -m unittest -v \
  tests/conformance/test_double_move_differential.py

MUTAGO_COLLAPSE_SLICE_PROBE="$PWD/build/collapse-increment1/mutago-collapse-slice-probe" \
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS='error::ResourceWarning' \
PYTHONPATH=python python3 -m unittest -v \
  tests/conformance/test_double_move_differential.py

PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS='error::ResourceWarning' \
PYTHONPATH=python python3 tests/conformance/double_move_differential.py \
  --probe build/collapse-increment1/mutago-collapse-slice-probe \
  --seed mutago-double-increment-1 --candidate-count 512
```

该载体只覆盖 NORMAL/PASS/DOUBLE_START 的 Increment 1。Immortal/Eightway 保持历史 unsupported 边界；两种活动锚候选到达 mechanics 后的接受、`SUICIDE`、`POSITIONAL_SUPERKO` 都必须映射为 `UNSUPPORTED_BY_SLICE` 并回滚，mechanics 前错误保持原优先级。专门的 E 自杀与 E-ko/PSK adapter/probe 回归不进入默认 corpus，因此固定 digest `644a4401cbc3adb7a09b787b84fb3ce54d60f6f63c8692a4e04192ab592eed15` 不变。夹具的 `derived.legalActionRanges` 只作为 checked-in 合同字面量被绑定和防漂移，不构成运行时完整 1,445 位 legal mask 等价证明。随机候选数和摘要格式均为 **UNFROZEN**。不得据此声明完整 reducer/oracle、生产协议、JSON 事件日志重放、checkpoint/持久化恢复、公共 undo/redo、`semantic-projection-v1` runtime、`GATE-RULE-1M` 或 `GATE-PROD` 已通过。

## Immortal Increment 2 一致性载体：UNFROZEN，仅测试

`collapsereducerprobe.cpp` 的第三个独立模式使用协议字面值 `immortal-diff-v2-unfrozen`。它不扩大 `normal-pass-diff-v0-unfrozen` 或 `double-move-diff-v1-unfrozen`：v0/v1 的请求/响应、unsupported 分类、固定摘要和 digest 均保持原样。v2 只对外承诺 `NORMAL`、`PASS`、`DOUBLE_START`、`IMMORTAL`；EIGHTWAY 的 mechanics 前错误保持历史错误码，候选到达 mechanics 后无论接受、因 `SUICIDE` 拒绝还是因 `POSITIONAL_SUPERKO` 拒绝，都映射为 `UNSUPPORTED_BY_SLICE` 并精确回滚。合法交替包围中心 E 自杀和 E-ko/PSK adapter/probe 回归专门固定该边界，但不加入默认 corpus，因此 v2 固定摘要和 digest 不变。官方夹具仍按冻结 N8 语义从 action 16 后的字面 legal ranges 中排除中心 `EIGHTWAY#1263`。

v2 沿用关闭式 episode 请求和 Action V1，限制为每请求 1 MiB、每响应 64 MiB、每 episode 160 步、测试配额分量 `0..4`、子进程 stdout/stderr 256 MiB/1 MiB，以及覆盖整个运行的一次 180 秒绝对 monotonic deadline。严格解析拒绝重复/转义别名键、浮点和非有限数、unsafe integer、非 ASCII/孤立 surrogate、非法 UTF-8、非 canonical 响应、未知字段和未知错误分类。进程监管复用 v1 的独立进程组、有界 reader/writer、deadline 内终止/kill/close/wait/join；失败上下文包含 manifest、response index、canonical request 和已知完整动作前缀。

每个接受步骤精确投影当前/最终状态和内部 atomic-stable 测试快照：source-aware stones、N4 groups/liberties、`protected`、完整 `immortalAnchors`、pending Double、双方四类 quota bucket、append-only ledger identity/lifecycle、捕获、actor/phase/PASS、完整有序 occupancy-only PSK、terminal/score 及 revision/atomic/event-log 计数。settlement 逐步包含事件 owner/kind/source、`abilityDeactivated`、`noOp`、按颜色 removal batches、稳定占据和连续 PSK index。若接受动作随后还会自动运行 settlement 或终局计分，reducer 会在该自动事件之前把已提交的完整 action-state 捕获到 typed `CollapseGoApplyResult::atomicStateSnapshot`；无后续自动事件时，最终 state 本身就是该 action-state。probe 直接序列化这份权威 C++ 状态，不再根据前态机械重建来源、账本、配额或拓扑。该 typed 测试证据不是 serialized checkpoint、生产持久化格式或已冻结的产品协议。

官方正向夹具 `../contracts/examples/conformance-fixture-immortal-true-eye-settlement-v1.example.json` 固定 19×19 的 19 个动作，包括 action 17 的 `IMMORTAL#541`、action 19 的 atomic 中心占据、随后 pop 的黑点 180 removal batch、最终 `A/revision/logPosition=19/19/20`（其中 `logPosition` 是该 Schema 的 event-log-length 计数）、PSK 长度 21、WHITE/ordinary、inactive/captured/settled/tombstone 账本及完整 quota bucket。v2 carrier 同时把该计数显式命名为 `eventLogLength=20`。夹具保持 `descriptor: null`、公共摘要不变；其 checked-in `derived.legalActionRanges` 字面量 digest 固定为 `e2e1681d2a80320a5ea8addbb95d786dd669614ee0a472bb6871c61a36877271`。其中 action 8/10/12/14 后的 `EIGHTWAY#1263` 是依据冻结 N8 对角气规则手工绑定的 fixture-only 期望，action 16 后则明确不合法；这是夹具防漂移绑定，不是 carrier 运行时计算或比较完整 1,445 位 legal mask 的证据。

curated corpus 覆盖：真眼零气落子和自身 pop 移除；普通/Double 接入受保护零气组；受保护对方组不被普通全盘提子扫描移除；occupancy-only PSK；actor、pending kind、quota、occupied 优先级；action `T`；双锚点 newest pop 停用但不移除且 `noOp=false`、最后 pop 移除整组；Double+Immortal 全局逆序；settlement 后 source 被提且不返还；拒绝后的逐字段回滚；阈值和双 PASS settlement。它不把 captured-pending Immortal、Immortal-only connectivity split、multi-wave nonempty closure 或 simultaneous both-color removal 写成可达合法覆盖。

D4 覆盖在 9×9、13×13、19×19 各执行同一个合法保护/移除 episode 的全部八种变换和 inverse；比较 action、stone source point、group stones/liberties、group/global anchors、captures、ledger source point、settlement source/removal batches/stable occupancies、atomic snapshot 与完整 PSK。确定性重执行分别固定 action 17 armed state、action 18 pre-trigger、完整 settlement result 和 action 19 后 ordinary suffix 的不可变前缀。这些证据明确不是生产 JSON event-log/checkpoint recovery、持久化恢复或公共 undo/redo。

本次固定默认 manifest 为 `mutago-immortal-increment-2` / 256 个纯随机候选；curated 为 671，合计 927 个候选、46 个 episode，结果为 745 accepted、175 rejected、7 unsupported，transcript SHA-256 为 `a2f7cb99bcbbb4c3d9d17e79aa7796ea4bc247cad049a515770f7c24f65e6d0b`。其中 settlement 计数为 37 次 `PRE_THRESHOLD_TWO_PASSES`、1 次 `THRESHOLD`。这些计数只描述这一确定性测试语料，不能与其他运行累加成 gate。

从仓库根目录运行，构建输出应放在仓库外的临时目录：

```bash
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/mutago-collapse-immortal-v2.XXXXXX")"
cmake -S cpp -B "$BUILD_DIR" \
  -DUSE_BACKEND= -DUSE_AVX2=1 -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build "$BUILD_DIR" \
  --target mutago-collapse-slice-probe -j4

PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error PYTHONPATH=python \
python3 -m unittest -v tests/conformance/test_immortal_differential.py

MUTAGO_COLLAPSE_IMMORTAL_PROBE="$BUILD_DIR/mutago-collapse-slice-probe" \
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error PYTHONPATH=python \
python3 -m unittest -v tests/conformance/test_immortal_differential.py

PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error PYTHONPATH=python \
python3 tests/conformance/immortal_differential.py \
  --probe "$BUILD_DIR/mutago-collapse-slice-probe" \
  --seed mutago-immortal-increment-2 --candidate-count 256
```

该载体不证明完整 Eightway、完整运行时 legal mask、完整 reducer/oracle、生产协议、权威 JSON event-log replay、checkpoint/持久化恢复、产品接入、`GATE-RULE-1M` 或 `GATE-PROD`。当前证据也不解除项目的 **AUDIT-BLOCKED** 状态。

## Eightway Increment 3 一致性载体：UNFROZEN，仅测试

第四个独立模式使用协议字面值 `eightway-diff-v3-unfrozen`，支持 `NORMAL`、`PASS`、`DOUBLE_START`、`IMMORTAL`、`EIGHTWAY`。只要关闭式 Action V1 和冻结前置条件可判定，v3 不产生 `UNSUPPORTED`；接受和拒绝都由 C++ reducer 与独立 Python oracle 分别执行。v0/v1/v2 的 frame、状态投影、分类、固定摘要和 digest 不随 v3 扩大，旧 adapter 的 E mechanics-boundary 规则见前述各节。

v3 请求仍恰含 `protocolVersion`、`episodeId`、`boardSize`、`initialQuotas`、`steps`，每步恰含 `candidateActor` 与 Action V1。限制为每请求 1 MiB、每响应 96 MiB、每 episode 160 步、测试配额分量 `0..4`、总 stdout/stderr 256 MiB/1 MiB，以及贯穿 fixture load、严格解析、语料生成、Python 执行、进程树监管、响应解析、精确比较、D4 和重执行检查的一次 180 秒绝对 monotonic deadline。未知/冗余字段、重复或转义别名键、非 ASCII、浮点、unsafe integer、非法 UTF-8、未知版本、未知错误分类、非 canonical JSON、输出超限、缺少换行、frame 数错误和超时均 fail closed。所有 probe 启动、终止、kill、pipe close、wait 和 thread join 都受同一 deadline 约束；所有 `ProbeError` 路径携带 manifest、response index、completed response count、canonical request 和完整已知动作前缀。

每个 v3 状态同时投影活动 `immortalAnchors` 与 `eightwayAnchors`、精确混合棋块、去重气、保护、source-aware stones、完整 ledger/quota 生命周期、捕获、pending Double、actor/phase/PASS、revision/log、完整有序 occupancy-only PSK 和 terminal/score。接受动作另外包含 action-before-settlement 的 atomic snapshot；settlement 包含全局 newest-to-oldest 的每次 pop、来源、停用、no-op、全部 removal batch、每个稳定占据和连续 PSK index。Python 驱动不调用 C++ replay/checkpoint/undo，也不使用生产 legal mask；它从响应的 occupancy 与 ledger 独立重建混合连接、N4/N8 气、Immortal 保护和每次停用后的固定点 removal，并独立重算计分、触发条件、handoff、原子/PSK/source/ledger/quota/counter 闭包。

官方正向夹具 `../contracts/examples/conformance-fixture-eightway-immortal-split-v1.example.json` 是 `descriptor: null` 的 19×19 `contract-eightway-immortal-split`。十个动作依次使用 `IMMORTAL#521`、普通包围与非对称 filler、`EIGHTWAY#1263`、两次 PASS；它绑定 I/E 混合组与保护传播、action 10 atomic snapshot、先 pop `special-5` 后 pop `special-1`、点 180 split/removal、最终 ledger/source/quota、`A/revision/logPosition=10/10/12`、PSK 长度 13 和 BLACK ordinary handoff。fixture-only `derived.legalActionRanges` 由独立 oracle 对该有限前缀穷举并固定 digest `c644dd9c6fb65cc3472f1f6764b168d4d0aaac5f8af37691a2cc7e5b90929182`；合同测试对 anchor、保护、atomic occupancy、pop 顺序、removal、source、quota 和 PSK 漂移实施 hostile mutation。该字面量不是生产或 carrier 的完整 1,445 位 runtime legal-mask API。

curated 证据覆盖 N8-only 气与同点 NORMAL 自杀对照、任一端 E 对角连接、肩点占用不切断、普通/敌色对角分离、气去重、经 E 传播 Immortal 保护、E 停用 split、captured-pending E no-op、action `T` atomic 后 pop、E placement capture 的 PSK 回滚、I/D/E 全局交错顺序、较新 Immortal pop 捕获较旧 E source 后旧事件 no-op、配额大于一和精确拒绝优先级。`test_python_eightway_oracle.py` 另以明确标记的 constructor-valid synthetic robustness checkpoint 覆盖较新 E pop 移除较旧 Double source、全局交错以及 simultaneous both-color closure；它们不冒充可达对局。当前证据不声称存在可达的 nonempty multi-wave closure 或可达的 both-color removal。

丰富的非对称 I/E split episode 在 9×9、13×13、19×19 上执行八种 D4 和 inverse，逐项变换 action、source、两类全局/组内 anchor、mixed groups/liberties/protection、captures、ledger、removal batch、atomic/stable snapshot 和完整 PSK。确定性重执行固定 E placement、mixed protection、pre-trigger、完整 settlement 和 ordinary suffix 的不可变前缀。这不是生产 event-log replay、serialized checkpoint recovery、持久化恢复或公共 undo/redo。

默认 manifest 为 `mutago-eightway-increment-3` / 256 个纯随机候选；curated 为 504，合计 760 个候选、55 个 episode，结果为 582 accepted、178 rejected、0 unsupported，transcript SHA-256 为 `fa3ffd3afb4cec03c855d23d9f27ae0e16081fc1c4bc3eb101085fb7dbc0e6f1`。这些计数只描述该确定性测试语料，不可累加或外推为门槛。

从仓库根目录运行：

```bash
BUILD_DIR="${TMPDIR:-/tmp}/mutago-collapse-eightway-v3"
cmake -S cpp -B "$BUILD_DIR" -DUSE_BACKEND= -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build "$BUILD_DIR" --target mutago-collapse-slice-probe -j4

MUTAGO_COLLAPSE_EIGHTWAY_PROBE="$BUILD_DIR/mutago-collapse-slice-probe" \
PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error PYTHONPATH=python \
python3 -m unittest -v tests/conformance/test_eightway_differential.py

PYTHONDONTWRITEBYTECODE=1 PYTHONWARNINGS=error PYTHONPATH=python \
python3 tests/conformance/eightway_differential.py \
  --probe "$BUILD_DIR/mutago-collapse-slice-probe" \
  --seed mutago-eightway-increment-3 --candidate-count 256
```

该载体没有完整 runtime legal-mask API、管理终止、权威 JSON event-log replay、生产持久化、搜索、自博弈、训练、Gateway/Web 或其他产品接入证据；也不声称 `GATE-RULE-1M`、`GATE-PROD`、发布审计或任何正式发布条件已经通过。项目保持 **AUDIT-BLOCKED**。

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

Conformance tests compare the sole C++ production authority with an independently implemented slow Python oracle. The directory contains a standard-library-only Python reference implementation for strict Action V1 decoding, NORMAL/PASS/Double/Immortal/Eightway play, mixed N4/N8 topology, Immortal protection through E links, full-scan capture and suicide, ordered occupancy-only PSK, ledger settlement, and exact ordinary-play Chinese area scoring. The underlying oracle accepts nonnegative JSON-safe quota integers subject to state consistency and conservation. The external carriers are intentionally narrower: legacy v0 exposes only `quotaMode=ZERO/ONE`, while later carriers allow every `initialQuotas` component only in `0..4`. It also contains an explicitly test-only, **UNFROZEN v0** rehearsal: the `mutago-collapse-slice-probe` target is excluded from the default build and exchanges complete-episode canonical JSONL frames with an external Python driver under protocol literal `normal-pass-diff-v0-unfrozen`. The probe reuses the existing restricted JSON and Action V1 parsers, fails closed without a partial frame on malformed input, keeps diagnostics on stderr, and uses binary stdin/stdout on Windows. The driver forces and verifies that oracle modules come from this checkout, uses a versioned SHA-256 counter stream, covers all 1,445 action IDs plus structured legal and illegal candidates and explicit `A=T` settlement on centered 9×9, 13×13, and 19×19 zero-quota states, validates every closed nested response shape, compares every projected field and ordered PSK entry exactly, and stops at the first comparison mismatch with reproducible manifest, request, and action-prefix context. Requests are bounded to 160 steps and 1 MiB; canonical response lines are bounded to 16 MiB; aggregate subprocess stdout and stderr are bounded to 64 MiB and 1 MiB respectively. Where supported, the probe runs in a new session/process group; timeout or overflow terminates and kills the group, closes local pipes, and joins reader/writer threads only within the deadline, including when an exited child leaves a grandchild holding inherited pipes. Windows remains fail-closed with bounded local pipe closure and joins. Subprocess use is confined to this external harness; the independent oracle package remains subprocess-free. Legacy v0/v1/v2 deliberately retain their historical unsupported special boundaries even as the shared reducer/oracle gains later increments: Eightway pre-mechanics errors stay visible, while accepted, SUICIDE, or POSITIONAL_SUPERKO mechanics outcomes map to `UNSUPPORTED_BY_SLICE` with exact rollback. A fixed `opt-in-integration` / 1,600-random-candidate regression pins the complete historical v0 summary and digest `297e38b15aae76e507d71e7bda1fb38b0d320ed102fd6f99644c6ed758051cf1`; the new boundary regressions do not enter that corpus. The frozen identity is `mutago.collapse-go` / `0.1.0-draft` / descriptor SHA-256 `a21c67d7962b71a3a53b895de824dc6312502362de5341103c0265c2c81d0899`. Current coverage enforces the closed `schemaVersion`/`actionId`/`kind` Action V1 envelope, the 1,445-way kind-major codec, initial empty occupancy as PSK entry zero, stable action/settlement/terminal appends, and the MVP's absence of dead-stone negotiation. This rehearsal is not `semantic-projection-v1`, a production protocol, or evidence for `GATE-RULE-1M` or `GATE-PROD`; bounded candidate counts are not the million-action gate.

A separate test-only protocol literal, `double-move-diff-v1-unfrozen`, provides the bounded Double Increment 1 carrier without changing the old v0 shape or labels. It projects exact source-aware stones and N4 groups, actor/phase/action/pass state, pending Double linkage, all quota buckets, append-only ledger identity and lifecycle, revision/log/settled/terminal counters, captures, ordered occupancy-only PSK, no-op settlement traces, and terminal state. The checked-in Double settlement fixture is parsed with the checkout-pinned restricted-profile parser, which rejects duplicate and escaped-alias keys, floats/non-finite constants, unsafe integers, non-ASCII/surrogate strings or keys, and malformed UTF-8. The existing contract checker then validates full Schema invariants and debug groups, while the external driver binds every checked-in `derived.legalActionRanges` literal exactly; this is drift evidence, not runtime full-mask equivalence. Both implementations independently execute the fixture's three actions and match the normalized Increment 1 projection exactly. Curated tests add captured sources, multiple ledger entries, forbidden continuations, threshold boundaries, quota exhaustion, occupied/suicide/PSK failures, PASS continuation, both settlement reasons, terminal scoring, deterministic action re-execution with exact immutable pending/settlement prefixes, and all eight D4 transforms plus inverse round-trips on 9×9, 13×13, and 19×19. Requests are bounded to 1 MiB and 160 steps, response lines to 32 MiB, Double test quota components to `0..4`, aggregate stdout/stderr to 256 MiB/1 MiB, and the corpus to one absolute 180-second monotonic deadline. The original absolute timestamp is passed directly into child pre-launch checks, supervision, termination, pipe closure, waits, and joins; no fresh deadline is created from a handoff-time remaining duration. The same deadline also spans fixture load/validation, generation, Python execution, parsing/comparison, D4, and deterministic re-execution/prefix checks. Invalid-UTF-8 stdout, malformed JSON, non-newline output, and response-count failures include the manifest, response index, canonical request, and known full action prefix rather than falling back to invocation-only diagnostics. The Double digest manifest calls the requested random-only quantity `randomCandidateCount`; only the success summary uses total `candidateCount` alongside curated/random counts. The current default `mutago-double-increment-1` / 512 regression pins digest `644a4401cbc3adb7a09b787b84fb3ce54d60f6f63c8692a4e04192ab592eed15`. Immortal and Eightway mechanics remain unsupported within that historical carrier, and full runtime 1,445-bit legal-mask equivalence is intentionally not claimed. The re-execution evidence is not JSON event-log replay, serialized checkpoint recovery, production persistence, or public undo/redo. This carrier is not a fixture envelope consumer in production, a frozen runtime protocol, or a claim that `GATE-RULE-1M` passed.

A third, separately versioned test-only protocol literal, `immortal-diff-v2-unfrozen`, adds NORMAL/PASS/DOUBLE_START/IMMORTAL without widening v0 or v1. Eightway pre-mechanics errors retain their historical codes, while accepted, SUICIDE, and POSITIONAL_SUPERKO mechanics outcomes map to `UNSUPPORTED_BY_SLICE` with exact rollback. The v2 projection includes source-aware atomic snapshots, current/final states, dynamic protected N4 groups and anchors, all quota buckets, append-only ledger lifecycle, captures, complete ordered PSK, full settlement source/disposition/removal traces, terminal/score, and exact counters. Its official 19x19 true-eye fixture binds action 17 protection, action 19 atomic occupancy, the point-180 removal pop, final `19/19/20` counters, PSK length 21, WHITE ordinary handoff, and settled tombstone lifecycle while keeping `descriptor: null` and the public hash unchanged. The literal fixture legal ranges are drift-pinned by SHA-256 `e2e1681d2a80320a5ea8addbb95d786dd669614ee0a472bb6871c61a36877271`, including fixture-only frozen-N8 evidence for `EIGHTWAY#1263` after actions 8/10/12/14, and are not compared as a runtime 1,445-bit mask. All eight D4 transforms and inverses run on the same legal protection/removal episode at 9x9, 13x13, and 19x19, including actions, source/group/anchor/capture/ledger/removal/stable occupancy/complete-PSK fields. Deterministic re-execution fixes armed, pre-trigger, settlement, and ordinary suffix prefixes; it is not production event-log replay, checkpoint recovery, persistence, or public undo/redo. The pinned default manifest has 671 curated plus 256 random candidates (927 total across 46 episodes), with 745 accepted, 175 rejected, 7 unsupported, and transcript SHA-256 `a2f7cb99bcbbb4c3d9d17e79aa7796ea4bc247cad049a515770f7c24f65e6d0b`. Exact error counts are `NONE=745`, `WRONG_ACTOR=20`, `INVALID_PHASE=14`, `POINT_OFF_BOARD=81`, `POINT_OCCUPIED=9`, `QUOTA_EXHAUSTED=14`, `DOUBLE_CONTINUATION_KIND_FORBIDDEN=9`, `POSITIONAL_SUPERKO=1`, `TERMINAL_STATE=27`, and `UNSUPPORTED_BY_SLICE=7`; settlement counts are `NONE=889`, `PRE_THRESHOLD_TWO_PASSES=37`, and `THRESHOLD=1`. This evidence makes no full legal-mask, Eightway, product, persistence, `GATE-RULE-1M`, `GATE-PROD`, or release claim, and does not remove the repository's audit block.

A fourth independent test-only protocol, `eightway-diff-v3-unfrozen`, supports NORMAL/PASS/DOUBLE_START/IMMORTAL/EIGHTWAY and forbids `UNSUPPORTED` once the closed request is decidable. Its state and atomic snapshots project both anchor sets, exact mixed groups/liberties/protection, sources, ledger/quota lifecycle, captures, complete PSK, counters, settlement pops/removal batches, handoff, and terminal scoring. The Python driver independently reconstructs mixed connectivity, N4/N8 liberty unions, protection, fixed-point closure, score, triggers, atomic lineage, and PSK/source/ledger/quota progression without calling C++ replay, checkpoints, undo, or a production legal-mask API. The official descriptor-null 19x19 fixture `contract-eightway-immortal-split` binds a mixed I/E group, action-before-settlement state, reverse E/I pops, point-180 split/removal, final `10/10/12` counters, PSK length 13, and BLACK ordinary handoff; its fixture-only legal-range digest is `c644dd9c6fb65cc3472f1f6764b168d4d0aaac5f8af37691a2cc7e5b90929182`. Rich asymmetric D4 and inverse checks cover actions, sources, both anchor sets, mixed groups, captures, ledger, batches, stable snapshots, and complete PSK on 9x9, 13x13, and 19x19. Reachable cases cover N8-only liberty, endpoint/shoulder/color separation, liberty deduplication, Immortal propagation through E, E split, captured-pending no-op, action T, E capture/PSK rollback, global I/D/E order, newer Immortal capture of an older E source, quotas above one, and rejection precedence. Constructor-valid synthetic robustness cases are labeled separately and do not claim reachable nonempty multi-wave or both-color removal. The default 504 curated plus 256 random candidates produce 582 accepted, 178 rejected, zero unsupported, and transcript SHA-256 `fa3ffd3afb4cec03c855d23d9f27ae0e16081fc1c4bc3eb101085fb7dbc0e6f1`. The carrier has no full runtime legal-mask API, management termination, authoritative event-log replay, persistence, search, self-play, training, Gateway/Web, or product evidence, and makes no `GATE-RULE-1M`, `GATE-PROD`, release, or audit-completion claim.
