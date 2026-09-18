# stsai_s2_review — 包内索引

S2 轮回答一个问题：在**固定模型、固定有效 batch、最多 500 次优化更新**下，
把独立训练战斗从 96 局增加到 384 局，能否改善学生在开发场景上的效用。
先读 `SUMMARY.md`，边界读 `reports/known_limitations.md`。

- 基线：`c31ba2f02dccb92ff96d593e14ed5b3dd2644183`；包内 HEAD 见 `provenance.json`
- 协议：`protocol.json`（在**任何新增采集与训练之前**提交）
- 本轮实际执行：新增采集 1 次（288 局，2 worker）、新训练 run 5 次（各 500 updates）、
  对局 4096 场（6 个 selected 网络 + heuristic + search，各 512 场）

## 怎么复现

```bash
unzip stsai_s2_review_<sha>.zip -d pkg
git clone pkg/repo.bundle repo
(cd pkg && sha256sum -c MANIFEST.sha256)
python pkg/review/run_review.py --repo repo --sources pkg/native_sources.tar.gz \
    --package pkg --model pkg/model/D384_s17_selected.pt   # 需 cmake + C++17 编译器
python pkg/review/recompute_s2.py --package pkg            # 独立复算配对统计
```

`review/run_review.py` 的顺序：校验附件 → 用 PRE_PATCH 快照按序施加 5 个补丁并离线构建 →
真实 import 并核对 revision/补丁哈希 → 用刚校验过的补丁后源码重新生成意图表 →
全量 pytest（要求 native 零 skip）→ 公开反例重放 → 12 条模型 smoke。
缺工具链的必需步骤报 NOT_RUN、超时报 TIMEOUT，两者都让退出码非零。

`review/recompute_s2.py` 是按协议**独立重写**的统计复算（与生成交付数字的脚本不同源），
两者一致本身即是证据。

## 文件

| 文件 | 内容 |
|---|---|
| `SUMMARY.md` | 直接回答第 7 节要求的 7 个问题 |
| `MANIFEST.sha256` | 包内每个文件的 sha256 |
| `protocol.json` | 协议：run 表、冻结训练配置、选点规则、资源上限、统计方向 |
| `provenance.json` | HEAD/bundle 校验、引擎 revision 与 5 个补丁哈希、语义版本、六个 run 的配置与选中 SHA、数据与评测文件哈希 |
| `semantic_compatibility.json` | 0005 只增头文件的论证 + 新构建重放 256 场与 S1R 记录逐场一致的回归证据 |
| `repo.bundle` | 完整可克隆历史 |
| `native_sources.tar.gz` + `native_sources_manifest.json` | 离线最小源码（PRE_PATCH）与逐文件来源/许可/哈希 |
| `review/` | 一键复核链、离线构建、反事实重放、模型 smoke、S2 统计独立复算 |
| `tests/junit.xml` + `tests/build_and_test.log.gz` | 干净目录里那次构建+测试的 JUnit 与完整日志（含 configure/build 原始输出） |
| `data/initial_scenarios.json.gz` | D96/Dadd288/V24 的初始场景（分片本身不随包，可确定性重建） |
| `data/composition_and_shards.json` | D384 的组成：两个来源各自的指纹、分片哈希、规范化样本哈希 |
| `data/coverage.json` | 各条件的数据量、被看过多少、以及各清单之间的重叠计数 |
| `training/runs.json` | 六个 run：配置、数据指纹、selected/last step 与 SHA、真实教师一致率、覆盖计数 |
| `training/metrics.jsonl.gz` `validation.jsonl.gz` | 逐步训练日志与逐步完整验证（每行带 run 标识） |
| `training/selected_summary.csv` | 一屏可读的 selected 汇总 |
| `model/D384_s17_selected.pt` | **唯一上传的推理权重**（D384-seed17 按 V24 选定，去掉 optimizer） |
| `model/smoke_observations.jsonl.gz` `smoke_expected.json` | 12 条公开观测与独立加载期望值（含容差与并列规则） |
| `evaluation/scenarios.json.gz` | 两份开发集的物化清单 |
| `evaluation/episodes.jsonl.gz` | 4096 场逐场结果（胜负/截断/HP/效用/决策数/动作序列哈希） |
| `evaluation/decision_latency.jsonl.gz` | 逐决策动作索引与耗时 |
| `evaluation/paired_summary.json` | 配对统计与预注册判定规则的结果 |
| `reports/commands_and_limits.md` | 实际命令、run 表与资源限额 |
| `reports/known_limitations.md` | 本轮**未**证明的东西 |

## 未包含（有意）

- 另外五个模型的权重：只交配置、selected/last step 与 SHA、逐场原始结果；它们保留在执行机。
- D96-seed17 权重：已在上一轮交付（SHA `57ffb03f…`），不重复上传。
- `runs/`、optimizer 状态、venv、编译产物、游戏文件、完整训练分片。
