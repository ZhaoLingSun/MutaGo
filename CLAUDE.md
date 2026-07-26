# CLAUDE.md

本文件是 Claude Code 在 MutaGo 仓库中的实用入口。规范性政策位于 [AGENTS.md](AGENTS.md)；开始任何分析、编辑、测试、Git 操作或发布准备前，必须先阅读并遵守该文件。若本文件与 [AGENTS.md](AGENTS.md) 不一致，以 `AGENTS.md` 为准。

## 开始工作前

1. 运行 `git status --short --branch` 和针对任务路径的 `git diff -- <paths...>`，识别现有或并行工作。
2. 阅读 [设计文档索引](docs/设计文档/README.md)，再阅读与任务直接相关的冻结文档。规则工作至少要阅读[坍缩围棋规则](docs/设计文档/02-坍缩围棋规则-v0.1.0-draft.md)、[输入特征 ABI](docs/设计文档/04-输入特征ABI-V9.md)和[测试门槛](docs/设计文档/06-测试与一致性门槛.md)。
3. 把任务允许修改的路径列成明确清单；不要触碰清单外文件，也不要清理他人的未提交变更。
4. 对标为 **UNFROZEN** 的事项停止猜测：先取得明确设计决定，再实现或写入持久化接口。

## 继承的 C++ 构建命令

KataGo 基线的常用 Linux/Eigen 构建方式是在 `cpp` 目录内构建：

```bash
cd cpp
cmake . -DUSE_BACKEND=EIGEN -DUSE_AVX2=1
make -j4
```

后端选择、平台依赖和其他构建参数见 [Compiling.md](Compiling.md)。不要仅为“验证一下”而切换后端、下载大模型或改写本地构建配置；先确认任务范围和机器能力。

## 继承的 C++ 测试命令

从 `cpp` 目录运行已构建的 `katago`：

```bash
./katago runtests
./katago runoutputtests
```

仓库还保留以下上游包装脚本：

```bash
./runoutputtests.sh
./runsearchtestslimited.sh
./runsearchtests.sh
./runcmdtests.sh
```

使用时注意：

- `runtests` 是优先运行的核心本地测试入口。
- 上述四个包装脚本都会修改工作树中的测试输出或临时内容；只有任务明确授权相关路径时才能运行，运行后必须检查并清理或保留预期产物。
- `runoutputtests.sh` 会通过 `tee` 写入测试结果文件。
- `runsearchtestslimited.sh` 和 `runsearchtests.sh` 会写入 `tests/results` 与测试暂存内容；完整脚本还可能下载外部测试模型。它们依赖脚本记录的模型、配置和运行环境，不能把因资产缺失而未运行写成“已通过”。
- `runcmdtests.sh` 会删除并覆盖部分结果文件，并覆盖较广的命令行、GTP、analysis、match、sampling 与数据工具路径；只在任务范围和文件副作用均获授权且依赖齐备时运行。
- 新的坍缩围棋实现还必须满足 [AGENTS.md](AGENTS.md) 与[测试门槛](docs/设计文档/06-测试与一致性门槛.md)中的独立 Python 差分、百万动作零差异、ASan/UBSan、undo/redo、D4、PSK、结算和后续生产门槛；上述继承命令本身不能证明这些新门槛已经通过。

## 受限工作流

1. **定位权威层。** 确认变更属于 C++ 生产权威、Python 独立预言机、薄 Gateway、薄 Web、schema、文档还是测试。
2. **最小修改。** 只编辑明确授权的路径。生成文件只能通过声明的生成器更新，不能手改。
3. **最小验证。** 先运行与改动直接相关的快速测试或文档检查，再根据影响范围扩展；记录未运行及其原因。
4. **审阅差异。** 使用针对明确路径的 `git diff --check`、`git diff --stat -- <paths...>` 和 `git diff -- <paths...>`，确认没有越界、占位身份或虚假完成声明。
5. **谨慎交付。** 默认不暂存、不提交、不推送。只有用户明确要求时才执行；暂存必须使用 `git add -- <明确路径...>`，然后检查 staged diff。禁止宽泛暂存、force push 和共享历史改写。

## 文档工作提示

- 项目治理与设计文档采用完整中文正文，并以 `## English Summary` 结尾。
- 仓库内链接使用相对路径。
- 不要因规则文档文件名包含 `draft` 而把已冻结玩法重新描述成未决。
- `collapse-go` 不是已分配的公共 `rulesetId`；公共 `rulesetId` 与规范语义描述符字段/规范化为 **UNFROZEN / unassigned**，最终公开描述符 SHA-256 为 **AUDIT-BLOCKED / unassigned**。
- 不要修改不可变的上游快照 [docs/upstream/KataGo-README-v1.16.5.md](docs/upstream/KataGo-README-v1.16.5.md)。

## English Summary

[AGENTS.md](AGENTS.md) is the canonical policy; this file is a practical Claude Code entry point. Inspect existing changes, read the relevant frozen design documents, define exact allowed paths, make the smallest scoped change, run the smallest relevant checks before broader tests, and inspect path-scoped diffs. The inherited C++ flow builds from `cpp` with CMake/Make and provides `runtests`, `runoutputtests`, and broader output/search/command wrappers; model-dependent tests may require external assets and must not be reported as passed when not run. Default to no staging, commit, or push. If explicitly requested, stage named paths only and never force-push or rewrite shared history.