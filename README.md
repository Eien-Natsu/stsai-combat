# STSAI Combat

铁甲战士局内战斗 AI 研究工程。**目标、当前状态、验收、资源限制和协作规则只有一个入口：**

## [阅读 PROJECT_MAINLINE.md](PROJECT_MAINLINE.md)

下一轮执行者直接阅读 [NEXT_ACTIONS.md](NEXT_ACTIONS.md)，不要续跑初交付时期的安装/训练工单。

## 导航

| 内容 | 入口 |
| --- | --- |
| 唯一主线 | [PROJECT_MAINLINE.md](PROJECT_MAINLINE.md) |
| 当前单轮执行指令 | [NEXT_ACTIONS.md](NEXT_ACTIONS.md) |
| 架构与目标函数技术参考 | [docs/01_ARCHITECTURE.md](docs/01_ARCHITECTURE.md) |
| 信息边界技术参考 | [docs/02_FAIRNESS.md](docs/02_FAIRNESS.md) |
| 命令与环境参考（不是执行许可） | [docs/03_RUNBOOK.md](docs/03_RUNBOOK.md) |
| native 与实机接口参考 | [docs/04_NATIVE.md](docs/04_NATIVE.md) |
| 历史交付与路径解释 | [delivery_docs/README.md](delivery_docs/README.md) |
| 来源与许可 | [docs/SOURCES.md](docs/SOURCES.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |

代码在 `src/stsai/`、`native/`；测试在 `tests/`；工具在 `scripts/`、`review/`；历史证据在 `reports/`、`evidence/`、`training/`。
README 不另存一份进度表或训练计划。技术参考中的功能不等于本轮已验证，原游戏能力和实际效果以主线所引用的证据及边界为准。
