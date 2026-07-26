# MutaGo Collapse Go 输入特征 ABI V9 / 训练模式 V1

> 本文是规范性设计文档。除代码标识符、数学符号、固定枚举名和末尾英文摘要外，正文以中文表述。
>
> 规范关键词“必须（MUST）”“禁止（MUST NOT）”“应（SHOULD）”按其通常的强制等级解释。

## 文档元数据

| 字段 | 冻结值 |
|---|---|
| 状态 | **FROZEN DESIGN / NOT YET IMPLEMENTED** |
| 规则 | **Collapse Go 0.1.0-draft** |
| 公开规则哈希 | **AUDIT-BLOCKED / unassigned** |
| 仓库/上游基线 | KataGo stable **v1.16.5**, SHA `ba938676d7f42d70950b3a535af2466fb642008c` |
| MutaGo 模型版本 | **MutaGo Model V19** |
| 神经网络输入版本 | **Inputs V9** |
| 训练/回放模式 | **Training Schema V1** |
| 动作编码模式 | **Action Schema V1**（`actionCodecVersion=1`） |
| 画布 | `19 × 19` |
| 空间输入 | `38`，S0–S37 |
| 全局输入 | `67`，G0–G66 |
| 扁平动作数 | `1445` |

本文冻结 ABI 设计，不宣称相关代码已经实现，也不分配或暗示任何公开规则哈希。任何实现、模型描述符或发布清单在公开规则哈希正式分配前，必须把该字段保持为 `unassigned`（或语义等价的显式未分配状态），不得自行生成替代值。

---

## A. 绑定决策与术语

### A.1 冻结版本标识

| 字段 | 冻结值 |
|---|---:|
| Upstream baseline | KataGo stable v1.16.5, `ba938676d7f42d70950b3a535af2466fb642008c` |
| MutaGo model version | `19` |
| Neural input version | `9` |
| Action codec version | `1` |
| Replay schema version | `1` |
| Canvas | `19 × 19` |
| Spatial inputs | `38`, S0–S37 |
| Global inputs | `67`, G0–G66 |
| Flat action count | `1445` |

Model V19 继承项目既有 Model V17 架构及后处理语义，除非本文明确改变输入、策略、动作、描述符或兼容性 ABI。**Model V18 保留且未发布（reserved/unpublished）**，不得把本设计重新编号为 Model V18。Inputs V8 同样保留且不受支持。

每个模型描述符、导出器、写入器、加载器和推理后端都必须显式编码并校验：

- `modelVersion=19`；
- `inputsVersion=9`；
- `numSpatialFeatures=38`；
- `numGlobalFeatures=67`；
- `canvasX=canvasY=19`；
- `actionCodecVersion=1`；
- 四个点动作族；
- kind-major 扁平动作顺序；
- policy 子头角色；
- 与 policy logits 分离的 Q 子头角色；
- 普通围棋模式的兼容路由与小棋盘适配器设置；
- score-belief 奇偶波全局索引 **G18**，即索引 `18`；
- 规则版本 `Collapse Go 0.1.0-draft`；
- 公开规则哈希的显式状态 `unassigned`，直至另行分配。

### A.2 玩家与视角

- `P` 是执行下一次原子玩家动作的权威玩家。
- `O` 是另一名玩家。
- self/own 表示 `P`，opponent 表示 `O`。
- `P` 存储在 `GameState` 中，禁止根据动作数、树深度或奇偶性推导。
- 在 `DOUBLE_START` 与其 continuation 之间，`P` 保持不变。
- 所有相对 `P` 的 value、score、ownership、policy 和 Q 目标都使用实际 `P`。搜索代码不得仅因跨过一条边就对这些目标取反或交换。

### A.3 原子动作与时钟

原子玩家动作种类按固定顺序为：

1. `NORMAL`
2. `IMMORTAL`
3. `DOUBLE_START`
4. `EIGHTWAY`
5. `PASS`

自动 settlement pop、能力移除、重建和提子都不是原子动作。

定义：

- `A`：已完成原子玩家动作的精确数量；
- `T`：配置的正 settlement threshold；
- `R=T-A`：暴露的 settlement 前状态中，距阈值剩余的动作数；
- `a(e)`：创建事件 `e` 的零基原子动作索引，等于执行该动作前的 `A`。

每个特殊动作恰好创建一个事件，因此事件时间戳唯一。

### A.4 暴露阶段

Collapse `GameState` 包含：

- `PRE_SETTLEMENT`；
- 内部事务式 settlement；
- `POST_SETTLEMENT`。

内部 settlement 期间禁止神经网络求值。部分 settlement 状态没有 policy 行、搜索节点或神经网络 phase bit。

每个非终局 Collapse 决策状态中，pre-settlement 与 post-settlement 必须恰有一个为真。

### A.5 事件生命周期

每个事件在神经张量之外保留：

- 稳定事件 ID；
- 精确时间戳；
- 绝对所有者；
- 类型；
- 原始动作点/锚点；
- 稳定源棋子 ID；
- armed、consumed、captured、tombstone、settled disposition。

**armed event** 是尚未解决、仍在棋盘上的 `IMMORTAL` 或 `EIGHTWAY` 事件，其能力能够影响任何未来转移或 settlement 结果。

“armed” 是生命周期状态，不是战术反事实测试。安静或当前未受威胁的能力仍是 armed。暂时休眠但能够重新激活的能力仍是 armed。

仅当事件不可逆地无法影响任何未来转移时，事件才成为 tombstone：

- 每个 `DOUBLE_START` 事件立即成为 tombstone；
- 被提走的 Immortal/Eightway 事件仅在不可能重新激活时才可成为 tombstone；
- settlement 中弹出 tombstone，在棋盘变换意义上是恒等操作。

在所有玩家和所有类型合计后，每个棋盘点至多锚定一个 armed event。

### A.6 Collapse 状态中的 Legacy V7 投影

普通围棋模式下，在进入兼容适配器前先采用规范居中放置；经适配器转换后，S0–S21 和 G0–G18 必须逐字节等于固定上游 Inputs V7 值。

Collapse-only 状态使用显式 `LegacyV7View`：

1. 可见颜色网格是最近一次原子动作及其全部自动后果完成后的当前棋盘。
2. S1–S5 使用该原始网格、普通正交连通和普通气。忽略特殊免疫与 Eightway 连通。
3. 原始零气链不获得 S3–S5 中的任何平面。
4. 定义 `sanitize(B)`：同时删除每个普通正交零气链。删除棋子只会增加气，因此一次同时删除即可。
5. 需要普通合法棋盘的 V7 征子和地域例程使用 `sanitize(B)`，并使用固定上游修订版的精确算法；忽略特殊能力。
6. 原子特殊点动作以其 actor 和 point 进入 legacy move history，其类型对 V7 前缀不可见；PASS 以 PASS 进入。
7. 令 `B_j` 为原子动作 `j` 及其全部自动后果完成后的棋盘；若该动作触发 settlement，则 `B_j` 是完整事务结束后的最终可见棋盘。settlement 中间棋盘永不进入 V7 recent-board 槽。
8. settlement 完成后，legacy valid-history count 与普通 pass-ending 状态重置为零。因此第一条 post-settlement 行不包含 V7 move history，而 S28–S37/G42–G66 仍保留真实原子历史。
9. G14 仍是 base-Go/V7 的 pass-ending 投影，不是 Collapse 的两次 PASS 触发器。
10. S6 仍是当前 base-Go `NORMAL` 动作的 ko/superko 禁点投影，不能替代 typed-action legality。

必须严格区分 **V7 recent-board 历史** 与 **官方 Collapse positional-superko 历史**：

- 官方 Collapse Go 采用只看黑白占位、不包含下一手玩家的 **occupancy-only positional superko（PSK）**。
- 对不触发 settlement 的合法原子动作，在该动作及其直接自动提子达到稳定闭包后，把稳定黑白占位加入 PSK 历史。
- 若原子动作触发 settlement，则动作本身达到稳定闭包后的占位按正常动作历史规则加入 PSK；随后，**每弹出一个特殊事件并完成该次能力移除、重建及提子的稳定闭包后，都必须再次把该稳定黑白占位追加到 PSK 历史**。
- tombstone pop 即使不改变棋盘，也仍完成一次 pop，并追加其稳定占位；重复历史条目是允许的。
- settlement 自动生成的重复占位自动获准，不得中止或回滚 settlement；但这些占位都约束之后的玩家动作。
- 重建或提子过程中的不稳定中间棋盘不是 PSK 历史状态。
- 无论 settlement 内部追加多少个 PSK 状态，一个原子动作仍只占一个 atomic-history 槽和一个最终 V7 recent-board 槽。
- situational superko 仅可作为 base-Go/通用 KataGo 兼容实现的说明；它不是官方 Collapse Go 规则。

---

## B. 精确 S0–S37 空间 ABI

### B.1 通用空间规则

- 规范张量：`float32[B,38,19,19]`，NCHW。
- 加载器侧不做 normalization 或 standardization。
- 所有棋盘外单元严格为 `0`。
- 二值平面严格取 `{0,1}`。
- S26 是连续值。
- D4 只置换点，绝不交换通道身份或 self/opponent 含义。
- 普通围棋模式中，S22–S37 严格全零。

逻辑 `N×N` 棋盘上的点 `(x,y)` 映射为：

\[
C_N(x,y)=(x+o_N,y+o_N),\qquad o_N=\frac{19-N}{2}.
\]

因此 9、13、19 路棋盘的偏移分别是 `(5,5)`、`(3,3)`、`(0,0)`。

### B.2 保留的 Inputs V7 通道

| Index | Frozen name | 精确语义 |
|---:|---|---|
| S0 | `V7_ON_BOARD` | 居中可落子矩形内为 `1`。 |
| S1 | `V7_PLA_STONE` | 当前 `P` 所有的棋子。 |
| S2 | `V7_OPP_STONE` | `O` 所有的棋子。 |
| S3 | `V7_LIBERTIES_1` | 普通正交链恰有一口气的每颗棋子。 |
| S4 | `V7_LIBERTIES_2` | 恰有两口气。 |
| S5 | `V7_LIBERTIES_3` | 恰有三口气。 |
| S6 | `V7_KO_BAN` | Phase 0：simple-ko 点加当前 `superKoBanned`；encore：当前 `superKoBanned`。 |
| S7 | `V7_KO_RECAP_BLOCKED` | encore 中为 `koRecapBlocked`；否则为零。 |
| S8 | `V7_UNUSED_ZERO` | 始终为零。 |
| S9 | `V7_PREV1_MOVE` | 最近一个纳入的落子点，仅当 actor 为 `O`；PASS 由 G0 表示。 |
| S10 | `V7_PREV2_MOVE` | 第二个纳入的落子点，仅在 S9 成功且 actor 为 `P` 时。 |
| S11 | `V7_PREV3_MOVE` | 期望 actor 为 `O`。 |
| S12 | `V7_PREV4_MOVE` | 期望 actor 为 `P`。 |
| S13 | `V7_PREV5_MOVE` | 期望 actor 为 `O`。 |
| S14 | `V7_LADDER_CAPTURED_CURRENT` | 由上游 V7 征子例程判断为可征吃的一气或二气链中的每颗棋子。 |
| S15 | `V7_LADDER_CAPTURED_PREV1` | 在一个已纳入 legacy 回合之前的棋盘上计算 S14；没有纳入回合时复制当前值。 |
| S16 | `V7_LADDER_CAPTURED_PREV2` | 在两个已纳入 legacy 回合之前的棋盘上计算 S14；必要时复制最近可用的征子棋盘。 |
| S17 | `V7_LADDER_WORKING_MOVES` | 当前可被征吃的二气 `O` 链之进攻方有效着点。 |
| S18 | `V7_AREA_PLA` | V7 当前分配给 `P` 的 area/territory。 |
| S19 | `V7_AREA_OPP` | V7 当前分配给 `O` 的 area/territory。 |
| S20 | `V7_SECOND_ENCORE_START_PLA` | encore phase 2+ 中，第二 encore 开始时由 `P` 占据的点。 |
| S21 | `V7_SECOND_ENCORE_START_OPP` | 对手对应平面。 |

legacy history encoder：

1. 按 `5`、`maxHistory` 和 `numApproxValidTurnsThisPhase` 共同限制历史长度。
2. 应用上游 game-end/pass-hack suppression。
3. 要求嵌套 actor 序列 `O,P,O,P,O`。
4. 遇到第一次不匹配即停止。
5. 通过 G0–G4 表示 PASS。
6. S15/S16 绑定于最终纳入的回合数。

在 Double continuation 节点，最近 actor 是当前 `P`，因此 S9 失败，S9–S13 全零。

S18/S19 的精确情形为：

- Area scoring、无 tax：完整 `calculateArea`，保留棋子、安全大地域及不安全大地域。
- Area scoring、seki/all tax：independent-life area，保留棋子但不保留地域。
- Territory scoring、第二 encore 之前：两者全零。
- Territory scoring、第二 encore 中：
  - 无 tax：保留地域，不保留棋子；
  - seki/all tax：地域和棋子均不保留；
  - 恢复与 `secondEncoreStartColors` 匹配的存活棋子。
- group-tax 的分数调整不改变二值平面的幅值。

### B.3 Armed-event 排名

令 `E` 包含双方所有仍在棋盘上的 armed Immortal 和 Eightway 事件。

按精确原始时间戳从最旧到最新排列 `E`。定义：

\[
L=|E|,\qquad r(e)\in\{1,\ldots,L\},
\qquad \tau(e)=\frac{r(e)}{L+1}.
\]

性质：

- `0` 表示不存在。
- 值越大表示全局越新。
- 所有者与类型不影响排名。
- 有意丢弃时间戳间隔。
- 由每点最多一个 armed event 的不变量可知 `L≤361`。
- 事件不再 armed 后重新计算排名，同时保持其余 armed event 的精确相对顺序。

### B.4 新空间通道

| Index | Frozen name | 精确语义 |
|---:|---|---|
| S22 | `ARMED_IMMORTAL_SELF` | `P` 所有 armed Immortal 锚点的 multi-hot mask。 |
| S23 | `ARMED_IMMORTAL_OPP` | 对手对应平面。 |
| S24 | `ARMED_EIGHTWAY_SELF` | `P` 所有 armed Eightway 锚点的 multi-hot mask。 |
| S25 | `ARMED_EIGHTWAY_OPP` | 对手对应平面。 |
| S26 | `ARMED_EVENT_GLOBAL_RANK` | 在每个 S22–S25 标记点写入共享的 `τ(e)`；其余位置为零。 |
| S27 | `NEXT_ARMED_SETTLEMENT_ANCHOR` | 在全局最新 armed event，即 S26 最大值处写 `1`；`L=0` 时全零。 |
| S28 | `ATOMIC_LAG1_SELF_POINT` | lag-1 actor 等于当前 `P` 且动作不是 PASS 时的点。 |
| S29 | `ATOMIC_LAG1_OPP_POINT` | lag-1 actor 等于 `O` 且动作不是 PASS 时的点。 |
| S30 | `ATOMIC_LAG2_SELF_POINT` | lag-2 self 点。 |
| S31 | `ATOMIC_LAG2_OPP_POINT` | lag-2 opponent 点。 |
| S32 | `ATOMIC_LAG3_SELF_POINT` | lag-3 self 点。 |
| S33 | `ATOMIC_LAG3_OPP_POINT` | lag-3 opponent 点。 |
| S34 | `ATOMIC_LAG4_SELF_POINT` | lag-4 self 点。 |
| S35 | `ATOMIC_LAG4_OPP_POINT` | lag-4 opponent 点。 |
| S36 | `ATOMIC_LAG5_SELF_POINT` | lag-5 self 点。 |
| S37 | `ATOMIC_LAG5_OPP_POINT` | lag-5 opponent 点。 |

对每个 lag，其 self/opponent 对中至多一个非零。

`DOUBLE_START` 在这些平面中是点动作。PASS 和不可用历史没有点。

S22–S27 在 post-settlement 中为零。S28–S37 在 post-settlement Collapse 状态中继续编码真实原子历史。

S26 的规范存储类型是 float32。在首次 learned projection 之前，实现只能采用已证明对每个 `L≤361` 都严格保序的表示：

- 允许 IEEE float32；
- 允许 IEEE binary16；穷举测试确认对每个 `L≤361` 都严格有序；
- 禁止 bfloat16 和 FP8，除非未来 ABI 证明其对完整排名集合是单射；
- bfloat16 模型必须让 S26 经过独立的 float32 或 binary16 首次投影。

---

## C. 精确 G0–G66 全局 ABI

所有全局量均为规范 float32、D4 不变量，且不做标准化。

### C.1 保留的 Inputs V7 全局量

| Index | Frozen name | 精确语义 |
|---:|---|---|
| G0 | `V7_PREV1_IS_PASS` | 纳入的 lag 1 存在且为 PASS。 |
| G1 | `V7_PREV2_IS_PASS` | 纳入的 lag 2 为 PASS。 |
| G2 | `V7_PREV3_IS_PASS` | 纳入的 lag 3 为 PASS。 |
| G3 | `V7_PREV4_IS_PASS` | 纳入的 lag 4 为 PASS。 |
| G4 | `V7_PREV5_IS_PASS` | 纳入的 lag 5 为 PASS。 |
| G5 | `V7_SELF_KOMI_DIV20` | 从 `P` 视角计算的 V7 当前 self-komi，裁剪到 `[-N²-20,N²+20]` 后除以 20。 |
| G6 | `V7_KO_RULE_A` | 与 G7 共同编码：simple `(0,0)`；positional/Spight `(1,+0.5)`；situational `(1,-0.5)`。 |
| G7 | `V7_KO_RULE_B` | ko-rule 第二分量。 |
| G8 | `V7_MULTI_STONE_SUICIDE_LEGAL` | 启用时为 `1`。 |
| G9 | `V7_TERRITORY_SCORING` | territory 为 `1`；area 为 `0`。 |
| G10 | `V7_TAX_RULE_A` | 与 G11 共同编码：none `(0,0)`；seki `(1,0)`；all `(1,1)`。 |
| G11 | `V7_TAX_RULE_B` | tax 第二分量。 |
| G12 | `V7_ENCORE_PHASE_A` | 与 G13 共同编码：phase 0 `(0,0)`；phase 1 `(1,0)`；phase 2 `(1,1)`。 |
| G13 | `V7_ENCORE_PHASE_B` | encore 第二分量。 |
| G14 | `V7_PASS_WOULD_END_PHASE` | 上游 base-Go pass-ending 投影，受上游 suppression 约束。 |
| G15 | `V7_PDA_PRESENT` | signed playout-doubling advantage 非零时为 `1`。 |
| G16 | `V7_PDA_SIGNED_HALF` | `0.5 ×` signed playout-doubling advantage。 |
| G17 | `V7_BUTTON_AVAILABLE` | button 可用时为 `1`。 |
| G18 | `V7_KOMI_PARITY_WAVE` | 精确 V7 三角奇偶波。 |

G6/G7 中 situational 编码只用于保留 base-Go/V7 通用兼容语义。官方 Collapse Go 固定使用 occupancy-only positional superko。

对 G18，令 `k` 为 G5 使用的已裁剪 self-komi，并令：

\[
d=
\begin{cases}
0,&N^2\text{ 为偶数}\\
1,&N^2\text{ 为奇数}
\end{cases},
\quad
k_0=2\left\lfloor\frac{k-d}{2}\right\rfloor+d,
\quad
\delta=\operatorname{clamp}(k-k_0,0,2).
\]

则：

\[
G18=
\begin{cases}
\delta,&\delta<0.5\\
1-\delta,&0.5\le\delta<1.5\\
\delta-2,&1.5\le\delta\le2.
\end{cases}
\]

除 area scoring 或 territory scoring 的第二 encore 外，G18 为零。

**每条 score-belief 路径都必须读取 G18，即 `input_global[:,18:19]`。禁止读取最后一个全局通道来代替 G18。**

### C.2 扩展计数变换

对每个非负整数计数：

\[
\Lambda(n)=\log_2(1+n).
\]

不做 clipping 或 saturation。

定义：

- `q⁰[p,t]`：初始配额；
- `q[p,t]`：剩余配额；
- `U[p,t]=q⁰[p,t]-q[p,t]`：已用数量；
- 类型顺序：Immortal、Double、Eightway。

### C.3 新全局量

| Index | Frozen name | 精确值 |
|---:|---|---|
| G19 | `COLLAPSE_ENABLED` | 每个 Collapse 状态（包括 post-settlement）为 `1`；否则为 `0`。 |
| G20 | `SETTLEMENT_THRESHOLD_LOG` | `Λ(T)`。 |
| G21 | `ATOMIC_ACTION_COUNT_LOG` | `Λ(A)`；post-settlement 中继续增长。 |
| G22 | `ACTIONS_TO_THRESHOLD_LOG` | pre-settlement 为 `Λ(T-A)`；否则为 `0`。 |
| G23 | `SETTLEMENT_PROGRESS` | pre-settlement 为 `A/T`；否则为 `0`。 |
| G24 | `PHASE_PRE_SETTLEMENT` | 仅在暴露的 pre-settlement Collapse 状态中为 `1`。 |
| G25 | `PHASE_POST_SETTLEMENT` | 仅在 post-settlement Collapse 状态中为 `1`。 |
| G26 | `PRE_THRESHOLD_PASS_STREAK` | 暴露的 pre-settlement 决策中精确为 `0` 或 `1`；否则为 `0`。 |
| G27 | `PENDING_DOUBLE_CONTINUATION` | 仅在 Double start 与 continuation 之间为 `1`。 |
| G28 | `COUNTDOWN_EQ_1` | pre-settlement 中当且仅当 `T-A=1` 时为 `1`。 |
| G29 | `COUNTDOWN_EQ_2` | pre-settlement 中当且仅当 `T-A=2` 时为 `1`。 |
| G30 | `REMAINING_IMMORTAL_SELF_LOG` | `Λ(q[P,I])`。 |
| G31 | `REMAINING_IMMORTAL_OPP_LOG` | `Λ(q[O,I])`。 |
| G32 | `REMAINING_DOUBLE_SELF_LOG` | `Λ(q[P,D])`。 |
| G33 | `REMAINING_DOUBLE_OPP_LOG` | `Λ(q[O,D])`。 |
| G34 | `REMAINING_EIGHTWAY_SELF_LOG` | `Λ(q[P,E])`。 |
| G35 | `REMAINING_EIGHTWAY_OPP_LOG` | `Λ(q[O,E])`。 |
| G36 | `USED_IMMORTAL_SELF_LOG` | `Λ(U[P,I])`。 |
| G37 | `USED_IMMORTAL_OPP_LOG` | `Λ(U[O,I])`。 |
| G38 | `USED_DOUBLE_SELF_LOG` | `Λ(U[P,D])`。 |
| G39 | `USED_DOUBLE_OPP_LOG` | `Λ(U[O,D])`。 |
| G40 | `USED_EIGHTWAY_SELF_LOG` | `Λ(U[P,E])`。 |
| G41 | `USED_EIGHTWAY_OPP_LOG` | `Λ(U[O,E])`。 |
| G42 | `ATOMIC_LAG1_ACTOR` | lag-1 actor 是当前 `P` 时为 `+1`，是 `O` 时为 `-1`，不存在时为 `0`。 |
| G43 | `ATOMIC_LAG2_ACTOR` | lag 2 同上。 |
| G44 | `ATOMIC_LAG3_ACTOR` | lag 3 同上。 |
| G45 | `ATOMIC_LAG4_ACTOR` | lag 4 同上。 |
| G46 | `ATOMIC_LAG5_ACTOR` | lag 5 同上。 |
| G47 | `ATOMIC_LAG1_IS_PASS` | lag 1 kind 为 PASS。 |
| G48 | `ATOMIC_LAG1_IS_IMMORTAL` | lag 1 kind 为 IMMORTAL。 |
| G49 | `ATOMIC_LAG1_IS_DOUBLE_START` | lag 1 kind 为 DOUBLE_START。 |
| G50 | `ATOMIC_LAG1_IS_EIGHTWAY` | lag 1 kind 为 EIGHTWAY。 |
| G51 | `ATOMIC_LAG2_IS_PASS` | lag 2 kind 为 PASS。 |
| G52 | `ATOMIC_LAG2_IS_IMMORTAL` | lag 2 kind 为 IMMORTAL。 |
| G53 | `ATOMIC_LAG2_IS_DOUBLE_START` | lag 2 kind 为 DOUBLE_START。 |
| G54 | `ATOMIC_LAG2_IS_EIGHTWAY` | lag 2 kind 为 EIGHTWAY。 |
| G55 | `ATOMIC_LAG3_IS_PASS` | lag 3 kind 为 PASS。 |
| G56 | `ATOMIC_LAG3_IS_IMMORTAL` | lag 3 kind 为 IMMORTAL。 |
| G57 | `ATOMIC_LAG3_IS_DOUBLE_START` | lag 3 kind 为 DOUBLE_START。 |
| G58 | `ATOMIC_LAG3_IS_EIGHTWAY` | lag 3 kind 为 EIGHTWAY。 |
| G59 | `ATOMIC_LAG4_IS_PASS` | lag 4 kind 为 PASS。 |
| G60 | `ATOMIC_LAG4_IS_IMMORTAL` | lag 4 kind 为 IMMORTAL。 |
| G61 | `ATOMIC_LAG4_IS_DOUBLE_START` | lag 4 kind 为 DOUBLE_START。 |
| G62 | `ATOMIC_LAG4_IS_EIGHTWAY` | lag 4 kind 为 EIGHTWAY。 |
| G63 | `ATOMIC_LAG5_IS_PASS` | lag 5 kind 为 PASS。 |
| G64 | `ATOMIC_LAG5_IS_IMMORTAL` | lag 5 kind 为 IMMORTAL。 |
| G65 | `ATOMIC_LAG5_IS_DOUBLE_START` | lag 5 kind 为 DOUBLE_START。 |
| G66 | `ATOMIC_LAG5_IS_EIGHTWAY` | lag 5 kind 为 EIGHTWAY。 |

对存在的 NORMAL lag，actor 非零，四个 kind bit 全零。历史不存在时，actor 和全部 kind bit 全零。任一存在的非 NORMAL 动作必须恰有一个 kind bit 置位。

棋盘尺寸有意从 S0 推导，不在全局量中重复。

普通围棋模式中，G19–G66 严格全零。

编码前必须满足：

\[
0\le q[p,t]\le q^0[p,t],\qquad U[p,t]=q^0[p,t]-q[p,t].
\]

pre-settlement 状态中：

- Immortal/Eightway armed 数量等于相应 marker plane 的点数；
- `U - armedCount` 是 captured/inert tombstone 数量；
- 每个已用 Double 已经是 tombstone。

post-settlement 中，每个 marker count 均为零，所有已用事件均已 settled。

---

## D. 精确合法掩码与 policy/action codec

### D.1 规范动作索引

kind code：

```text
0 NORMAL
1 IMMORTAL
2 DOUBLE_START
3 EIGHTWAY
```

对画布坐标 `(X,Y)`：

\[
p(X,Y)=19Y+X,
\qquad
a(k,X,Y)=361k+p(X,Y).
\]

PASS 为：

\[
a_{\text{pass}}=1444.
\]

| Range | Meaning |
|---:|---|
| `0..360` | NORMAL |
| `361..721` | IMMORTAL |
| `722..1082` | DOUBLE_START |
| `1083..1443` | EIGHTWAY |
| `1444` | PASS |

因此固定 kind-major 动作顺序为 **NORMAL、IMMORTAL、DOUBLE_START、EIGHTWAY、PASS**，动作 ID 总数固定为 **1445**。

较小棋盘不得定义任何紧凑替代整数 ABI。对语义 `N×N` 棋盘，必须先使用 `(X,Y)=C_N(x,y)` 映射到居中的 19×19 画布，再使用本节冻结的 `a(k,X,Y)=361k+(19Y+X)`；`PASS` 始终为 `1444`。协议可以使用 typed action `{kind,loc}`，但任何 Action Schema V1 整数 ID、日志 ID、训练 ID 或客户端映射都不得采用基于 `N²` 的局部编号或其他替代编号。canvas-to-semantic 转换必须拒绝 S0 之外的非 PASS 点。

### D.2 Typed action 身份

一步棋是 `Action{kind,loc}` 或其规范整数 action ID。裸 Go `Loc` 不足以标识动作。

下列位置必须使用 typed action identity：

- 搜索边与 child arrays；
- PV 与 analysis output；
- game history 与 recent history；
- policy/Q targets；
- replay records；
- transition APIs；
- 当动作历史影响语义时的 transposition/graph hashes。

搜索 child capacity 必须支持至少 1445 个不同动作。

### D.3 Policy 与 Q 输出布局

Policy logits 与 Q predictions 是分离产物。

对 `Hπ` 个 policy 子头：

- 点 logits 的逻辑布局为 `[B,Hπ,4,19,19]`；
- 若序列化为 channels，点通道 `c=4h+k`；
- 每个 policy 子头有一个独立 PASS logit；
- 按上述动作公式展平为 `[B,Hπ,1445]`。

对 `Hq` 个 Q 子头，采用相同动作布局，但使用独立张量：

```text
policyLogitsNHA       [B,Hπ,1445]
qActionPredictionsNQA [B,Hq,1445]
```

Q 输出不是 logits，不做 softmax normalization，且不得接受 policy cross-entropy masking。

描述符角色应区分例如：

- current atomic policy；
- next atomic policy；
- soft current/next policy；
- optimistic current policies；
- Q win/loss；
- Q score。

旧“opponent reply”头改为“next recorded atomic decision”头。

### D.4 权威合法掩码

`legalMaskNA` 为 `bool[B,1445]`，由权威环境生成，不属于 38+67 输入。

它包括：

- 居中棋盘边界；
- 占用；
- 提子与自杀；
- simple ko；
- 官方 Collapse 的精确 occupancy-only positional-superko context；普通围棋/通用引擎兼容路由可按其配置处理 base-Go positional 或 situational superko；
- 各动作族特有的落子语义；
- 配额；
- phase；
- pending Double 限制；
- threshold 限制；
- PASS 合法性。

模式限制：

- 普通围棋：只有 NORMAL 和 PASS 可合法。
- Pending Double：只有 NORMAL 和 PASS 可合法。
- Post-settlement：只有 NORMAL 和 PASS 可合法。
- 棋盘外：四个点动作族条目全部为 false。
- `DOUBLE_START` 要求 pre-settlement、无 pending continuation、Double 配额为正、动作族本身合法，且 **`A+2≤T`**。

Double threshold 的边界语义必须精确如下：

- 仅当 `A+2≤T` 时才可开始 Double；
- 当 `A=T-2` 时，`DOUBLE_START` 是第 `T-1` 个完成的原子动作，continuation 是第 `T` 个完成的原子动作；
- 当 `A=T-1` 时，禁止开始 `DOUBLE_START`。

每个 policy 行必须至少有一个合法动作。

非法动作的 targets 和 visit counts 必须为零。

### D.5 感知掩码的 normalization 与 loss

对非空合法集合 \(\mathcal L\)：

\[
\log Z=\operatorname{logsumexp}_{a\in\mathcal L} z_a,
\]

\[
\mathcal J=-\sum_{a\in\mathcal L}t_a(z_a-\log Z).
\]

非法元素必须在乘法之前排除。实现不得依赖可能产生 NaN 的 `0 × -∞`。

仅当 finite sentinel 已针对每个受支持 dtype 测试为等价，且非法 target 项仍被显式排除时，才允许使用 finite sentinel。

### D.6 可选 T1 目标

- T0 是当前原子决策，使用当前状态合法掩码。
- T1 是下一条记录的原子决策，使用单独存储的下一状态掩码。
- T1 不是对手专用目标。
- T1 在 `DOUBLE_START → continuation` 之间有效。
- 若不存在下一决策，或两个决策状态之间发生 settlement 事务，则 T1 weight 为零。
- 零权重且不存在的 T1 具有零 counts，并可使用全零 mask。

### D.7 Double 与 settlement 转移

执行 `DOUBLE_START` 时，以下步骤原子完成：

1. 校验 typed legality。
2. 应用 Double source placement。
3. 减少 Double quota，并增加 used Double count。
4. 追加时间戳为 `A_before` 的稳定事件。
5. 将该事件标记为 consumed/tombstone。
6. 增加 `A`。
7. 记录 atomic history entry。
8. 设置 pending Double。
9. 保持同一玩家为 `P`。

在 continuation 节点：

- 仅 NORMAL 或 PASS 可合法；
- 它产生独立搜索节点和训练行；
- NORMAL continuation 独立执行完整落子、提子、自杀/保护及 PSK 合法性事务；
- PASS continuation 只验证 phase、actor 和 continuation 义务；它不落子、不提子、不检查自杀，也不执行 PSK 重复拒绝，但仍增加 `A` 与停着连计、产生动作事件、清除 pending Double，并追加未改变的稳定占据；
- continuation 合法提交后 pending 清除，下一行动者确定为该 continuation 行动者的对手；若 continuation 触发 settlement，则该对手保存为 `handoffActor`，且 settlement 完成后仍为当前行动者。

仅在完整原子转移之后检查 settlement trigger：

\[
A\ge T
\quad\text{或}\quad
\text{pre-threshold pass streak}=2.
\]

因为 Double continuation 是强制动作，`DOUBLE_START` 仅在 `A+2≤T` 时合法。特别地，`A=T-2` 时 start 和 continuation 分别完成第 `T-1`、`T` 个动作；`A=T-1` 时 start 非法。

pre-settlement 触发用 PASS 不计入 post-settlement 普通终局。settlement 后 pass-ending 状态重置。

Settlement 是事务式的：

1. 按 newest-to-oldest 顺序弹出完整 ledger entry。
2. 若事件为 armed，移除其能力。
3. 重建并执行提子，直到确定性稳定闭包。
4. 该 pop 到达稳定闭包后，立即把当前稳定黑白占位追加到官方 occupancy-only PSK 历史。
5. tombstone 在棋盘变换意义上按恒等操作处理，但其 pop 完成后仍追加稳定占位；因此可产生重复历史条目。
6. settlement 生成的重复占位自动允许，不进行合法性拒绝、回滚或提前终止；所有追加占位都约束未来玩家动作。
7. 不向 PSK 历史写入重建/提子的不稳定中间状态。
8. 继续处理，直到 ledger 排空。
9. 进入 post-settlement 普通行棋。
10. 仅在全部完成后暴露下一决策。

原子动作自身达到稳定闭包后的占位按正常动作历史规则记录；若其触发 settlement，之后还要按上述规则为每个事件 pop 追加占位。上述多个 PSK 追加不产生额外玩家决策、NN 节点、policy 行、atomic-history 槽或 V7 recent-board 槽。

转移 API 必须先确定权威 next actor，之后才能计算 situation hashes、base-Go 通用兼容路径中的 situational-superko hashes、current bans、graph hashes 或 child keys。禁止无条件调用 `getOpp(actor)`。官方 Collapse PSK 哈希本身仅由黑白占位决定，不包含 next actor。

---

## E. D4 与居中棋盘变换

### E.1 规范 D4 ID

使用 KataGo C++ bit 编号：

- bit 0：flip Y；
- bit 1：flip X；
- bit 2：transpose。

对 symmetry `s`：

```text
x = X
y = Y
if s & 2: x = 18-x
if s & 1: y = 18-y
if s & 4: swap(x,y)
```

D4 围绕画布中心 `(9,9)` 作用。由于棋盘居中，每个可落子 footprint 都映射到自身。

inverse 使用相同 ID，但 ID 5 与 6 互为逆。

### E.2 产物变换

对每个空间通道：

\[
S'_c(g_s(p))=S_c(p).
\]

对每个点动作族：

\[
a(k,X,Y)\mapsto a(k,g_s(X,Y)).
\]

PASS 保持 1444。

相同点置换应用于：

- 全部 38 个空间输入；
- 全部四个 policy block；
- legal masks；
- T0/T1 policy targets 与 visit counts；
- Q targets；
- ownership 与其他空间输出；
- replay event coordinates（执行 augmentation 时）。

Globals、原始时间戳、event IDs、quotas 和 scalar targets 不变。

### E.3 Python symmetry ID

现有 Python `apply_symmetry` 的整数含义不同。对规范 C++ symmetry ID，正向 Python ID 为：

```text
cpp_to_python_forward = [0,7,5,2,4,3,1,6]
```

对 inverse-output transformation：

```text
cpp_to_python_inverse = [0,7,5,2,4,1,3,6]
```

V9 policy helper 必须变换四个独立的 361 点 block，并保持 PASS 不变。现有 one-board-plus-pass helper 不适用于 1445 个动作。

### E.4 严格普通小棋盘适配器

上游 V7 将小棋盘放在左上角。因此，严格 9×9/13×13 兼容需要 descriptor-controlled adapter。

普通模式中：

1. 接受规范居中的 V9 S0–S21。
2. 将其平移到上游左上角放置。
3. 向未修改的 legacy route 精确提供 22 个空间通道和 19 个全局通道。
4. 对上游内部 inference symmetry，仅在平移后应用 legacy 全 19×19 symmetry。
5. 运行未修改的 legacy core。
6. 应用 inverse legacy output symmetry。
7. 重新居中 NORMAL policy 和每个 spatial output。
8. 保持 PASS 与 nonspatial outputs 不变。

平移必须发生在 positional embeddings 之前，也必须发生在 legacy internal symmetry 之前。对 transformer 与 absolute-position 模型，此顺序是强制要求。

规范 V9 data augmentation 仍使用居中 D4。适配器内部 legacy symmetry 是独立兼容操作。

---

## F. 训练与回放张量模式

### F.1 训练行语义

每行恰好表示一个非终局玩家决策。

- `DOUBLE_START` 与 continuation 产生独立行。
- 两行使用同一玩家视角。
- settlement 中间状态不产生行。
- 终局状态不产生 policy 行。
- 自动事件不消耗 history slot。
- value、score、ownership、Q 和 policy-target 视角使用实际 `P`。

### F.2 内存张量

| Artifact | Shape | Dtype |
|---|---:|---|
| `spatialInputNCHW` | `[B,38,19,19]` | float32 |
| `globalInputNC` | `[B,67]` | float32 |
| `legalMaskNA` | `[B,1445]` | bool |
| `policyTargetNA` | `[B,1445]` | float32 |
| `policyLogitsNHA` | `[B,Hπ,1445]` | compute dtype |
| `qActionPredictionsNQA` | `[B,Hq,1445]` | compute dtype |

### F.3 强制 replay manifest 与 arrays

每个 V1 replay shard 包含：

```text
replaySchemaVersion         uint16[1] = [1]
inputVersion                uint16[1] = [9]
actionCodecVersion          uint16[1] = [1]
canvasSize                  uint8[1]  = [19]

binarySpatialChannelIds     uint8[37]
continuousSpatialChannelIds uint8[1]

binarySpatialNCHWPacked     uint8[N,37,46]
continuousSpatialNCHW       float32[N,1,19,19]
globalInputNC               float32[N,67]

legalMaskNTAPacked          uint8[N,2,181]
policyVisitCountsNTA        uint64[N,2,1445]
policyTargetWeightNT        float32[N,2]
```

精确通道列表：

```text
binarySpatialChannelIds     = [0..25,27..37]
continuousSpatialChannelIds = [26]
```

加载器在对应合法集合上归一化非零 visit counts，生成 `policyTargetNA`。

对 T0：

- weight 为正；
- visit sum 为正；
- mask 非空。

对不存在的 T1：

- weight 为零；
- visits 为零。

Packing：

- 361 bits 需要 46 bytes；最后七个 bit 为零。
- 1445 bits 需要 181 bytes；最后三个 bit 为零。
- byte 内 bit order 为 big-endian，与 `numpy.unpackbits(..., bitorder="big")` 兼容。

shuffler 必须按 manifest 分支，校验精确 key/profile 集合，并禁止连接不兼容的 schema version 或 profile。

现有 KataGo 辅助 value/score/ownership arrays 可保留在 profile-specific extension 中，但其视角必须使用实际 `P`。

### F.4 Symmetry 与重组

同一次采样的 D4 操作必须应用于：

- 解包后的 binary planes；
- S26；
- 两个 legal masks；
- 两个 visit targets；
- 全部 spatial auxiliary targets。

通道必须按存储的 channel-ID arrays 重组，禁止按观测值推断。

### F.5 历史随机化

规范 replay 存储全部可用的五个 atomic lag。

训练历史截断使用单调 lag gates \(h_1\ge h_2\ge\cdots\ge h_5\)。对每个被丢弃的 atomic lag，加载器必须联合清零：

- 对应的两个 point plane；
- 对应的 G42–G46 actor scalar；
- 对应的四个 G47–G66 kind bit。

不得改变 G26 pass streak、G27 pending Double、event markers 或 event ranks。

S9–S16/G0–G4 继续精确使用上游 V7 history randomization。现有 22-channel matrix 实现必须扩展，对非 legacy 通道执行 identity behavior。

### F.6 Legacy replay 迁移

现有 KataGo NPZ 行不包含精确合法掩码，也没有足够的 superko 状态来重建它们。

因此，旧 NPZ 行仅在根据以下信息重新生成后才能进入 Training Schema V1：

- 原始 game/action records；
- 精确 rules；
- starting state；
- 完整 move history；
- 固定的 legality implementation。

仅把 362-way target 重映射到 1445 个动作是不充分的。无法重建精确 mask 的行必须从 V1 exact-mask training 中排除，或在单独版本化的 legacy-loss profile 下加载。

---

## G. Search key、NN cache key 与神经输入分离

### G.1 神经模型输入

只有：

- S0–S37；
- G0–G66；
- 单独版本化的可选 metadata encoder input。

下列内容不是神经输入：

- legal masks；
- event IDs；
- raw timestamps；
- full ledger；
- full positional-superko history；
- rule JSON；
- settlement cursor 或 trace。

### G.2 权威 GameState

`GameState` 保留精确绝对状态：

- board size 与 visible board；
- stable stone/source identities；
- actual next actor；
- base-Go rules、komi、ko、encore 与 scoring state；
- 官方 Collapse 的精确 occupancy-only positional repetition history；普通围棋兼容状态另按其 base-Go 规则保留所需历史；
- 精确 `T`、`A`、trigger count 与 pass streak；
- pre/post phase；
- pending Double owner 与 linked event；
- 精确 initial、remaining 与 used integer quotas；
- full ordered ledger；
- raw timestamps 与 stable IDs；
- armed/tombstone/captured/settled disposition；
- recent atomic actor/kind/location records；
- `LegacyV7View` 与 recent projection boards；
- terminal state。

settlement 每次 event pop 闭包后追加的稳定占位属于权威 positional repetition history；不稳定重建/提子中间态不属于。

### G.3 Search/transposition key

精确 search key 必须包括：

- visible board 与 stable source identities；
- actual next actor；
- full typed-action control state；
- 精确 quotas、`A`、`T`、pass streak 与 pending Double；
- full semantic ledger order 与 armed-event state；
- 官方 Collapse 的精确 occupancy-only positional repetition context，或语义精确等价的 persistent digest；普通围棋兼容路由可使用其配置所需的 base-Go positional/situational context；
- 节点单次 cached neural evaluation 使用的全部 history fields；
- terminal 与 base-Go phase state。

仅当没有内部引用在语义上使用稳定 ID 标签时，才可 canonicalize 掉 stable IDs。

Search edges 存储 typed actions，而非仅存 locations。

### G.4 神经求值缓存

优先 NN cache 在以下处理之前存储 raw model outputs：

- exact legality masking；
- policy temperature；
- pass capping；
- search-only suppression；
- normalization。

其 key 包括：

- model/checkpoint identity；
- descriptor 与 input ABI version；
- 精确规范 input bytes，或带 full-byte equality verification 的 digest；
- metadata inputs；
- compatibility-adapter mode；
- 影响 raw output 的 internal symmetry 与 precision options。

每次 cache hit 都重新计算并重新应用 legality。

若缓存 postprocessed probabilities，key 还必须包括：

- 精确 1445-bit legal-mask digest；
- 全部 policy postprocessing parameters；
- 全部 search-only move-suppression options。

上游 history-tolerant NN hash 与 masked-probability cache 对 V9 不充分。

### G.5 Replay-only metadata

Replay 应在张量外保留：

- board size 与 rule version；
- public rules hash 字段，其当前规范值为 `unassigned`；
- 精确 threshold 与 quotas；
- absolute next actor；
- 每个 atomic typed action；
- event IDs 与 raw timestamps；
- Double linkage；
- full ledger 与 settlement trace/checksum；
- state before/after hashes；
- 重建 occupancy-only positional superko 所需的精确信息，包括每次 settlement pop 稳定闭包后的占位；
- exact masks；
- source model/checkpoint 与 search parameters。

---

## H. 迁移初始化与 step-zero 测试

### H.1 强制架构路由

字面 step-zero compatibility 要求未修改的 legacy route：

\[
z_{\text{legacy}}
=
\operatorname{LegacySpatial}_{22}(S0{:}S21)
+
\operatorname{LegacyGlobal}_{19}(G0{:}G18).
\]

Collapse mode 另有零初始化的 extension projections：

\[
z_{\text{ext}}
=
\operatorname{ExtensionSpatial}_{16}(S22{:}S37)
+
\operatorname{ExtensionGlobal}_{48}(G19{:}G66).
\]

普通模式中：

- 完全跳过 extension path；
- 不通过已改变的 fused kernel 添加零张量；
- legacy 22/19 operator shapes 与 execution order 保持不变。

这是 bitwise claim 的强制条件。仅扩宽 convolution 或 linear layer 不充分。

### H.2 Policy 迁移

对每个 policy 子头：

- 旧 361 个点输出复制到 NORMAL 族；
- 旧 PASS 输出复制到 action 1444；
- Immortal、Double、Eightway 分支初始化为精确零；
- 普通路由先保持旧 362-element normalization 与 postprocessing order，再把结果 scatter 到 1445-way API。

对每个 Q 子头：

- 旧 point/pass predictions 复制到 NORMAL/PASS；
- 特殊动作族 Q 输出初始化为零；
- Q predictions 与 policy logits 保持分离。

Model V16 或已配置 Model V17 的 Q channels 必须被分类为 Q outputs，而非 policy logits。Model V18 保留且未发布；本 ABI 的目标模型版本是 Model V19。

### H.3 输入与训练状态迁移

migrator 必须确定性执行，且不得使用现有会添加噪声的 channel-expansion utility。

它必须：

- 逐 bit 复制保留的 raw-model parameters；
- 将新 parameters 初始化为精确零；
- 逐 bit 复制保留的 EMA/SWA parameters；
- 将新 EMA/SWA parameters 初始化为零；
- 保留 `n_averaged`；
- 精确复制保留的 optimizer momentum/moment/state buffers；
- 将新 parameters 的 optimizer state 初始化为零；
- 保留 scalar optimizer step counters 与 parameter-group hyperparameters；
- 更新嵌入的 Model V19、Inputs V9、Action Schema V1 描述符版本；
- 保留全部无关 train state。

禁止随机扰动，也禁止静默删除 optimizer 或 SWA state。

### H.4 G18 依赖

每个 main head、intermediate head、export path 和 backend 都必须为 score-belief parity wave 使用 **G18**：

```python
input_global[:,18:19]
```

不得使用 `input_global[:,-1:]` 或任何“最后一个全局通道”别名，因为 V9 中最后一个通道是 G66，不是 G18。

### H.5 Step-zero compatibility 的范围

Step-zero compatibility 是 forward/inference contract，不是 loss/gradient contract。

Exact-mask V1 training 不同于上游 KataGo training；后者在 policy loss 中仅掩蔽棋盘外点并保留 PASS。本设计不宣称 training loss 或 gradients 精确相等。

对于同一原始 checkpoint、backend、device、precision、symmetry 和 postprocessing options，普通围棋测试必须验证：

- adapter 生成的 legacy input bytes 等于上游 V7 bytes；
- S0–S21/G0–G18 具有精确上游值；
- S22–S37/G19–G66 为零；
- NORMAL raw logits 逐 bit 等于旧 point logits；
- PASS raw logit 逐 bit 等于旧 PASS logit；
- value、score、ownership 与 auxiliary outputs 逐 bit 相等；
- scatter 之前，完整 legacy policy postprocessing（包括 output scaling、temperature、pass cap 与 configured suppression）一致；
- special legal bits 为 false；
- 八种 internal symmetries 全部一致；
- 9×9、13×13、19×19 全部一致；
- transformer 与 absolute-position 架构在 positional processing 前使用 placement adapter；
- 每条 score-belief 路径显式读取 G18，即 `input_global[:,18:19]`。

不要求跨 backend 逐 bit 相等；每个 backend 与其自身迁移前执行比较。

---

## I. 充分性边界与有意省略的信息

1. **无界整数**
   Float32 `log2(1+n)` 对无界整数不是单射。这影响 quotas、used counts、`A`、`T` 和 countdown。精确整数仍由 `GameState` 权威保存。G28/G29 保留即时 `R=1`、`R=2` 的锐利边界。

2. **完整 superko 状态**
   有限张量有意不对未来官方 occupancy-only positional repetition 构成 Markov 状态。精确历史保留在 `GameState`、search keys 与 legal-mask generation 中。base-Go/通用引擎兼容模式若使用 situational superko，也必须在其自身状态中保留所需上下文；situational 不是官方 Collapse 规则。

3. **同点 armed stack**
   S26 无法表示同一点上的多个 armed event。V9 下此类状态非法。

4. **省略 tombstone**
   neural inputs 省略 tombstone locations、event IDs，以及纯 no-op 之间的 ledger order。官方 PSK 仍在每次 tombstone pop 稳定闭包后追加占位；由于该占位与当前占位相同，重复项不改变 positional 禁止集合。只有当 tombstone 不影响 board transition、score、timing 或 later activation 时，这种神经输入省略才有效。精确 pop 数量和顺序仍保留在权威状态与 replay metadata 中。

5. **省略 Double source**
   consumed Double source 没有 marker。若其之后的 settlement pop 能影响棋盘、分数或规则，则 V9 不充分。

6. **事务式 settlement**
   无法表示 partial-settlement neural 或 policy state。若 settlement 变为可中断流程，则必须定义新 ABI。每次 pop 稳定闭包进入 PSK 历史并不使该内部状态成为决策或 NN 状态。

7. **仅五个 atomic lag**
   更早动作历史保留为 replay/search metadata，不作为 neural input。

8. **Legacy 战术投影**
   V7 liberties、ladders 与 area 有意忽略特殊连通和免疫。特殊锚点及顺序由独立通道提供；本文不声称 V7 战术平面描述 Collapse mechanics。

9. **时间戳间隔与稳定 ID**
   S26 保留精确 active-event 顺序，不保留原始时间距离或身份。

10. **低精度排名**
    bfloat16 及更粗的 preprojection representation 可能合并相邻排名，因此不符合 ABI。

11. **居中放置与 V7 bytes**
    小棋盘的字面相等仅通过强制 top-left 普通兼容适配器成立。

12. **Exact-mask 训练目标**
    普通 forward inference 具有 step-zero compatibility；Exact-mask V1 training 有意不与上游目标保持 gradient compatibility。

---

## J. 规范性可执行不变量

1. Model V19 解析为 Inputs V9，且通道数严格为 38/67；Model V18 保留且未发布。
2. 每个 backend 拒绝不匹配的 descriptor、action layout 或 policy role。
3. 普通模式中每个 S22–S37 和 G19–G66 严格为零。
4. S0 在冻结居中偏移处恰有 `N²` 个 1。
5. 每个棋盘外 spatial value 为零。
6. 普通 19×19 的 S0–S21/G0–G18 逐字节等于固定 V7 输出。
7. 小棋盘适配器在 legacy core 前复现上游 top-left bytes。
8. S22–S25 标记每一个且仅标记 armed on-board event，包括安静能力。
9. 每个点的 S22–S25 之和至多为一。
10. S26 为正当且仅当 S22–S25 union 为一。
11. 对任意 armed events `e1,e2`，`a(e1)<a(e2)` 当且仅当 `S26(e1)<S26(e2)`。
12. 当且仅当 armed-event 集合非空时，S27 恰有一个点，且等于 `argmax(S26)`。
13. 对所有 `1≤L≤361`，float32 与受支持 binary16 排名表示严格有序。
14. bfloat16 preprojection rank path 被拒绝。
15. 每个 atomic lag 至多标记一个 self/opponent 点。
16. PASS 有 actor/kind globals，但没有点。
17. NORMAL 有非零 actor，且四个 kind bit 全零。
18. 不存在的历史具有零 actor、零 kind bits 和零 point planes。
19. Double continuation 节点的 lag 1 标识当前 `P` 与 `DOUBLE_START`。
20. V7 nested history gate 在第一次 actor mismatch 时停止。
21. settlement 不创建 atomic-history 槽或额外 V7 recent-board 槽。
22. 第一条 post-settlement 行重置 V7 included history，但保留 atomic history。
23. `U=q⁰-q`，且全部 quota counts 非负。
24. Double quota 与 used count 在 `DOUBLE_START` 更新，而非在 continuation 更新。
25. `DOUBLE_START` 合法的阈值条件严格为 `A+2≤T`：`A=T-2` 时 start 是第 `T-1` 个动作、continuation 是第 `T` 个动作；`A=T-1` 时 start 非法。
26. settlement 不会中断 pending Double。
27. 每个暴露的 pre-settlement 状态满足 `A<T`。
28. G28/G29 分别精确匹配 `T-A==1` 与 `T-A==2`。
29. 第二个 pre-threshold PASS 触发 settlement，且不带入 post-settlement pass ending。
30. 每次 settlement 在暴露决策前处理完整 ledger。
31. 从“会改变棋盘的事件顺序”中过滤 tombstone 得到相同最终可见棋盘；但不得据此省略每次 tombstone pop 后强制的 PSK 追加或审计记录。
32. 不触发 settlement 的完整原子转移记录一个动作稳定闭包占位；触发 settlement 的转移先记录动作稳定闭包占位，再在每个 event pop 的稳定闭包后追加一个占位。
33. settlement 生成的重复占位自动允许，不中断事务；这些占位全部约束未来玩家动作。
34. 不稳定 rebuild/capture 中间棋盘不进入 positional-superko history。
35. 官方 Collapse superko 仅比较黑白占位，不比较 next actor；situational superko 只属于 base-Go/通用引擎兼容说明。
36. Double start 后，所有依赖 next actor 的通用 situation/compatibility hashes 使用未改变的权威 next actor；禁止无条件换手。官方 PSK hash 仍只含占位。
37. 对全部 1445 个 ID，action encode/decode 为双射。
38. 在每个 symmetry 下 PASS 保持 1444。
39. D4 从不改变 action family。
40. 应用 symmetry 及其 inverse 后，每个 spatial、mask、target 与 action artifact 逐 bit 恢复。
41. Python 与 C++ 规范 symmetry helper 对八个 ID 全部一致。
42. Policy flattening 使用通道 `4h+k` 与 kind-major action blocks。
43. Policy masking 在 log-sum-exp 前排除非法动作。
44. 不计算任何 `0 × -∞` policy loss 项。
45. 每个 positive-weight target 在合法动作上总和为一。
46. T1 使用 next-state mask，绝不使用 current-state mask。
47. Q outputs 绝不作为 policy logits 处理。
48. Replay padding bits 为零，channel-ID manifests 精确匹配。
49. Binary tensors 与 S26 接受同一次采样的 D4。
50. Atomic history dropout 联合删除 point、actor 与 kind 字段。
51. 无法重建精确 legality 的 legacy NPZ 被 V1 exact-mask training 拒绝。
52. Raw NN cache hit 重新计算并重新应用当前 legality。
53. 神经输入相同但 occupancy-only positional-superko context 不同的两个状态保留不同 search keys。
54. Search edges 区分同一点上的全部四种 action kind。
55. 每个实现路径的 score-belief 精确读取 **G18**，即 `input_global[:,18:19]`，绝不读取 G66 或“最后一个全局通道”。
56. 普通兼容测试在 scatter 前保留完整 legacy 362-action postprocessing order。
57. 新 raw、EMA/SWA 与 optimizer parameters 初始化为精确零，且不扰动保留状态。
58. 文档与描述符中的公开规则哈希保持 `unassigned`，直至通过独立版本决策正式分配；本 ABI 文档本身不构成哈希分配或实现完成声明。

---

## K. 固定基线与仓库内来源

本规范的仓库/上游基线仅指当前 MutaGo 固定的 KataGo stable v1.16.5，SHA `ba938676d7f42d70950b3a535af2466fb642008c`。用于设计审计的其他本地代码树或草案不构成 MutaGo 基线，也不得在实现、发布或兼容性声明中替代该 SHA。

相关固定基线文件：

- [`cpp/neuralnet/nninputs.h`](../../cpp/neuralnet/nninputs.h)
- [`cpp/neuralnet/nninputs.cpp`](../../cpp/neuralnet/nninputs.cpp)
- [`cpp/neuralnet/modelversion.cpp`](../../cpp/neuralnet/modelversion.cpp)
- [`cpp/neuralnet/desc.h`](../../cpp/neuralnet/desc.h)
- [`cpp/neuralnet/nneval.cpp`](../../cpp/neuralnet/nneval.cpp)
- [`cpp/neuralnet/cudabackend.cpp`](../../cpp/neuralnet/cudabackend.cpp)
- [`cpp/game/boardhistory.h`](../../cpp/game/boardhistory.h)
- [`cpp/game/boardhistory.cpp`](../../cpp/game/boardhistory.cpp)
- [`cpp/search/search.cpp`](../../cpp/search/search.cpp)
- [`cpp/search/searchnode.h`](../../cpp/search/searchnode.h)
- [`cpp/dataio/trainingwrite.h`](../../cpp/dataio/trainingwrite.h)
- [`cpp/dataio/trainingwrite.cpp`](../../cpp/dataio/trainingwrite.cpp)
- [`python/katago/train/model_pytorch.py`](../../python/katago/train/model_pytorch.py)
- [`python/katago/train/data_processing_pytorch.py`](../../python/katago/train/data_processing_pytorch.py)
- [`python/katago/train/metrics_pytorch.py`](../../python/katago/train/metrics_pytorch.py)
- [`python/shuffle.py`](../../python/shuffle.py)
- [`python/train.py`](../../python/train.py)
- [`python/migrate_expand_channels.py`](../../python/migrate_expand_channels.py)
- [`docs/upstream/KataGo-README-v1.16.5.md`](../upstream/KataGo-README-v1.16.5.md)

基线代码目前仍实现 Inputs V7 的 22 个空间通道、19 个全局通道以及 362-way 普通动作接口；本文状态因此是 **FROZEN DESIGN / NOT YET IMPLEMENTED**。特别地，基线 score-belief 代码可因 G18 恰为 V7 最后一个全局通道而使用 last-channel slice；迁移到 V9 时必须改为显式 G18 slice `input_global[:,18:19]`。

---

## English Summary

This document freezes the design of **MutaGo Model V19**, **Inputs V9**, **Training Schema V1**, and **Action Schema V1** for **Collapse Go 0.1.0-draft**. Its implementation status is **FROZEN DESIGN / NOT YET IMPLEMENTED**. The pinned repository/upstream baseline is KataGo stable v1.16.5 at `ba938676d7f42d70950b3a535af2466fb642008c`; Model V18 is reserved and unpublished, and assignment of the final public rules digest remains **AUDIT-BLOCKED / unassigned**.

The neural ABI is exactly 38 spatial channels (S0–S37), 67 global channels (G0–G66), and a centered 19×19 canvas. The action ABI is exactly 1445 kind-major IDs ordered NORMAL, IMMORTAL, DOUBLE_START, EIGHTWAY, then PASS at ID 1444. Policy and Q tensors are separate, legality is supplied by an authoritative `[B,1445]` mask, and every score-belief path must explicitly read G18 via `input_global[:,18:19]`.

Official Collapse Go uses occupancy-only positional superko. Settlement is transactional and exposes no player decision or neural node, but every special-event pop appends its stable post-closure black/white occupancy to positional-superko history. Settlement-generated repetitions are automatically allowed and constrain future player actions; unstable rebuild/capture intermediates are not history states. `DOUBLE_START` is legal only when `A+2<=T`: at `A=T-2`, the start and continuation complete actions `T-1` and `T`, while starting at `A=T-1` is illegal. A Normal continuation performs the full placement/capture/survival/PSK transaction; a Pass continuation performs none of those board-legality operations but still updates counters, emits its event, clears pending Double, appends unchanged occupancy, and hands play to the opponent; that opponent remains `handoffActor` if settlement follows. Smaller boards always map through the centered 19×19 canvas before using the fixed 1445-way IDs; compact `a_N`/`PASS_N` alternatives are forbidden.
