# stsai_s1r_review — 包内索引

S1R 轮：先修复四个已定位缺陷（G1 输入、G2 来源、G3 执行、G4 契约），
四项门槛全部实跑通过后再做**一组**同规模单种子采集、训练与开发评测。
结论先读 `SUMMARY.md`，边界读 `reports/known_limitations.md`。

- 基线：`bf26b0f4713e0bd4ac9858034ca94693840c5040`；HEAD 见 `git_and_provenance.json`
- 门槛判定：`gate_receipts.json`，`training_authorised=true`
- 本轮实际执行次数：采集 1 次（96+24 初始场景）、native 训练 1 次（500 updates）、
  开发评测 1 次（256 场景 × 3 策略）

## 文件

| 文件 | 内容 |
|---|---|
| `SUMMARY.md` | 直接回答第 9 节的 7 个问题 |
| `MANIFEST.sha256` | 包内每个文件的 sha256（`sha256sum -c`） |
| `protocol.json` | 本轮执行前写定的协议：HEAD、资源限制、冻结训练配置 |
| `git_and_provenance.json` | HEAD/分支、bundle 校验、引擎 revision 与补丁哈希、语义版本、数据指纹、权重与评测文件哈希 |
| `gate_receipts.json` | 四道门槛的逐项命令、exit code、原始日志位置、证据类型 |
| `repo.bundle` | 完整可克隆历史（`git clone repo.bundle repo && git -C repo checkout <HEAD>`） |
| `native_sources.tar.gz` + `native_sources_manifest.json` | 离线最小源码（PRE_PATCH）与逐文件来源/许可/哈希；patch 顺序由 build 脚本施加 |
| `review/` | 复核脚本：一键链、离线构建、反事实重放、模型 smoke |
| `tests/pytest.txt` + `tests/junit.xml` | 本机全量 pytest 原始输出与 JUnit（0 failed、0 skipped） |
| `audit/public_memory_evidence.jsonl.gz` | 复审者公开轨迹逐步重放：复算 observation hash、公开区间、1024 seed 抽样检查 |
| `audit/patch_reconstruction.json` | 从锁定 revision 起的补丁序列冷启动：每步命令、exit code、补丁后文件哈希 |
| `audit/sampler_effect.json` | 修复前后 sampler 对教师决策的影响探针（哪些 root 变了、哪些没变） |
| `audit/collection_report.json` | 重建采集的计数：独立战斗、总状态、决策状态、终局/截断、utility 定义、continuation 来源 |
| `training/run.json` `metrics.jsonl` `validation.jsonl` | 唯一一次 native 训练的冻结配置、逐步分子/分母、逐步验证 |
| `training/summary.json` | selected/last 的 step、KL 与逐项验证聚合 |
| `training/data_manifests.json` `initial_scenarios.json` | 采集分片哈希与语义版本；每个初始场景的重建校验 |
| `model/policy_weights.pt` | **selected 推理权重**（step 400，去掉 optimizer），loader 元数据完整 |
| `model/smoke_observations.jsonl.gz` `smoke_expected.json` | 12 条公开观测与独立加载期望值（含容差与并列规则） |
| `evaluation/*` | 256 场景 × 3 策略的逐场记录、逐决策时延、聚合与配对 bootstrap 输入 |
| `reports/command_log.txt` | 上面各 receipt 引用的原始日志（按 receipt 里的路径分节） |
| `reports/known_limitations.md` | 本轮**未**证明的东西 |

## 未包含（有意）

- `runs/`、优化器状态、venv、编译产物、上游 `.git`、游戏本体与资源：均不在包内。
- 训练分片本体：`training/data_manifests.json` 给出每个分片的哈希与语义版本，
  初始场景与配置足以另行确定性重建（见 `training/initial_scenarios.json`）。
- 旧 S1 权重副本与历史报告：沿用原样，未覆盖、未重写；本包只含本轮产物。

## 本轮无 NOT_RUN 项

四道门槛的必需步骤全部实跑通过。可选步骤中，`review/run_review.py` 的
`attachments` 需要 `--package`、`model_smoke` 需要 `--model`，随包运行时提供即可复现。
