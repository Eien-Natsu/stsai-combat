# 历史交付文档，不是当前任务

当前唯一控制入口是 [PROJECT_MAINLINE.md](../PROJECT_MAINLINE.md)，执行入口是 [NEXT_ACTIONS.md](../NEXT_ACTIONS.md)。
本目录保留 S1R/S2 的交付说明原文，用于理解当时结论与包内结构；不要按旧 SUMMARY/INDEX 自动续训或认定其中所有路径在当前 checkout 存在。

## 阅读范围

[S1R 索引](s1r/INDEX.md)和[小结](s1r/SUMMARY.md)解释公开历史采样修复后的交付；[固定预算 S2 索引](s2/INDEX.md)和[小结](s2/SUMMARY.md)解释 D96/D384 对照。
`reports/s2_protocol.json`、`reports/s2_freeze.json` 属于更早的 louse 修复轮；固定预算 S2 的预注册协议是 [s2_volume_protocol.json](../reports/s2_volume_protocol.json)。同名 S2 不代表同一阶段。

## 包内路径与仓库路径

| 历史 ZIP 路径 | 当前仓库位置 / 状态 |
| --- | --- |
| `protocol.json`（固定预算 S2） | `reports/s2_volume_protocol.json` |
| `reports/known_limitations.md` | `reports/s2_known_limitations.md` |
| `reports/commands_and_limits.md` | `reports/s2_commands_and_limits.md` |
| `evaluation/paired_summary.json` | `reports/s2_paired_summary.json` |
| `tests/junit.xml` / 构建日志 | `reports/s2_junit.xml` / `reports/s2_build_and_test.log` |
| 包根 `native_sources*` | 仓库 `native/native_sources*` |
| 包内 `audit/*` 的对应审计 | 当前仓库 `evidence/`；具体映射应按文件逐项确认 |
| `model/D384_s17_selected.pt`、S2 原始对局/延迟及数据组成 | 当前干净 checkout 缺失，须由原产物/可信附件恢复，不可从汇总反造 |

历史报告、JUnit、manifest 和统计保留原字节。新的复核结果写到独立轮次目录；修正文案的展示误差也不能偷偷改实验原始证据。
结构化 S2 统计中的联合均值为 0.0093522135；历史 SUMMARY 的近似展示不改变“95% 条件场景区间跨零、证据不足”的判定。精确值以结构化统计及完成后的独立复算为准。
