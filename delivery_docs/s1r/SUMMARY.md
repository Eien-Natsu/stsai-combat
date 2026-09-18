# S1R 小结

先答第 9 节的七个问题，再给证据位置。边界与未证明项见 `reports/known_limitations.md`。

## 1. 新公开区间是否真正改变网络输入？

**是。** feature 13/14/15 承载"适用性、low/10、high/10"，`ENCODING_REVISION` 从 4 升到 5，
公开结构未变所以 schema 不动（仍为 4）。

- 复审方自带的红灯用例 `tests/test_review_gate.py::test_public_attack_base_reaches_encoder`
  在 bf26b0f 上失败（"public attack-base interval changed but every network input is identical"），
  现在通过：真实 native 观测 `[6,8]` 改成 `[7,7]` 后，六个编码数组不再全部相同。
- `tests/test_encoding_public_range.py` 覆盖四种合法字段状态：`[6,8]`、`[6,7]`、`[7,7]`、
  不适用（`-1`）。四者两两编码不同，且逐项断言归一化：`row[13]==适用性`、
  `row[14]==low/10`、`row[15]==high/10`（不适用时三者分别为 0、0、0）。
  "不适用"与"已知为 0"是两个不同输入（`row[13]` 0 vs 1）。
- 隐变量不入编码：同一公开状态、不同真实隐藏基础值时编码逐字节相同；把
  `true_attack_bases` / `public_attack_base` / `miscInfo` / `held_moves` / `rng_state` / `seed`
  塞进观测会被 `validate_public` 拒绝（这些名字现在也在 FORBIDDEN 里）。
- native 后端缺少该字段会被拒绝（不能冒充"不适用"）；reference 后端用显式的
  缺省规则，省略字段与显式"不适用"在该后端上编码一致。
- 旧编码权重被拒：`ENCODING_REVISION` 不匹配时 `check_checkpoint_semantics` 抛错。

## 2. 冷启动是否严格按锁定补丁顺序成功？未登记源码修改是否被拒绝？

**是，两者都实测。**

- `audit/patch_reconstruction.json`：从锁定 revision `7476a819…` 建 detached worktree
  （`worktree_head` 记录其 `rev-parse HEAD`，起始 `git status` 为空），按 0001→0002→0003→0004
  顺序 `git apply`，每一步记录命令、`--check` 与 `apply` 的 exit code、补丁后各文件哈希；
  结束时工作树哈希等于序列产物（`worktree_matches_series=true`）。
  旧的 0003 重复包含 0001/0002 的 hunk，在这一步无法通过——本轮已重新生成为纯增量。
- 未登记修改被拒绝：`tests/test_engine_tree_check.py` 覆盖原样树通过、
  已触及文件多加一个字节被拒、规则片段被还原被拒、半应用序列被拒、未登记文件被拒，
  且重复调用 `apply` 不会二次修改规则。
- 离线最小源码改为 **PRE_PATCH**（从 commit 取，不取打过补丁的工作树），
  由构建脚本施加同一序列，因此"编译的源码 = base + patches"是构造性成立而不是事后声明。
  补丁顺序、每文件来源/许可/哈希都写在 `native_sources_manifest.json`；
  pybind11 的完整 LICENSE 现在按 dist-info 实际位置收集（此前快照漏了它）。

## 3. 一键脚本是否真的构建后运行 native 测试、重放反例？

**是。** `review/run_review.py` 的顺序是：校验附件 → 用 PRE_PATCH 快照施加补丁序列并在
临时目录离线构建 → 把模块装进 checkout 并核对 `build_info` 的 revision 与补丁哈希 →
用**刚刚校验过的补丁后源码**重新生成意图表并比对 → 跑全量 pytest 并要求 native 用例真的执行 →
重放公开轨迹并复算 observation hash →（有模型时）加载权重跑 12 条公开观测。

- G3 的收据本身就是**新克隆**：`native_build` PASS、`import` PASS（revision 7476a8195402，4 patches）、
  `intent` PASS（50 行）、`tests` **277 项、0 failed、0 skipped**（含 155 个 native/回归用例）、
  `counterfactual` PASS（5 步重放、1024 个 sampler seed、公开根稳定）。
- 反事实是真跑：重放复审者的公开轨迹并逐步复算 hash，另在 strength=-9、显示伤害为 0 的终点
  用 1024 个 seed 抽样，确认 `{6,7,8}` 三个候选都仍可达（歧义没被"解决"成唯一值）。
- 本机缺工具链时脚本报 NOT_RUN 且总退出码非零，不会打印"所有可运行检查通过"。

## 4. 跨 head 批长、sampler 版本缺失、生命周期歧义的门槛结果？

| 项 | 结果 | 证据 |
|---|---|---|
| 跨 head 批长 | PASS | 反例（policy B=4、outcome B=1、mask B=4）现在抛错；B=1/3/9 负例、B=4 正例；全零 mask 仍有限损失与梯度；有效 batch 分区梯度不变性保持 |
| native checkpoint 缺 sampler | PASS | 缺失、`None`、旧值一律拒绝；**推理、warm start、resume 三个真实入口**都有负例，不只调 helper |
| reference 后端 | PASS | 用显式标记 `not_applicable`，省略字段不是通行证 |
| 真实歧义 | PASS | 复审者公开轨迹 `tests/fixtures/ambiguity_public_trace.json` 逐步重放一致；1024 seed 均保留公开根且只采相容候选 |
| 同回合改招 | PASS | `LARGE_SLIME / seed3`：同回合 LICK→SPLIT 不产生虚假执行记录，真正 SPLIT/SPAWNED 后新实体历史重置 |

审计表表述也已按第 4.4 节调整：零碰撞统计标为 **coverage regression**，
每个字段分别注明依据是源码推导、模型假设、构造反例还是实机运行。

## 5. 是否允许进入训练；实际次数？

四道门槛全 PASS（`gate_receipts.json`，`training_authorised=true`），因此执行了第 6 节：

- 采集 **1 次**（96 训练 + 24 验证初始场景，2 个 worker）
- native 训练 **1 次**（500 updates 上限内，实际 500）
- 开发评测 **1 次**（256 场景 × 3 策略）

数据重建没有复用修复前的教师标签：96/24 个初始场景逐个对 S1 物化记录做了重建校验
（scenario 与 episode_seed 全部一致），随后用修复后的 sampler 与新语义重新生成轨迹。
轨迹并不等同：`audit/sampler_effect.json` 显示 episode 17 的教师动作从 8 变成 5、
搜索 Q 值不同，episode 1 的 policy 向量不同（被采样的动作恰好相同）。

| | 独立战斗 | 总状态 | 决策状态 | 终局 | 截断 |
|---|---|---|---|---|---|
| train | 96 | 1774 | 1331 | 96 | 0 |
| val | 24 | 330 | 247 | 24 | 0 |

## 6. 训练与开发评测结果

模型 M128-R0（`d_model=128, layers=4, heads=4, dropout=0.1`），随机初始化（未 warm start），
`init_seed=17`、`data_seed=42`、有效 batch 32（16×2）、lr 3e-4、wd 0.01、epochs 40、
每 25 step 验证/保存、GPU 单张 RTX 5070、bf16。

| | step | checkpoint sha256 | kl_dev（逐战斗决策 KL 均值） | 教师熵 | 教师 top-1 一致 |
|---|---|---|---|---|---|
| **selected** | 400 | `34ea8ff0aa55cf6f…` | **0.10869** | 1.32458 | 0.7061 |
| last | 500 | `696350ae70af56da…` | 0.11352 | — | — |

交付的推理权重 `model/policy_weights.pt`（sha256 `57ffb03f01d5e7b1…`）由 selected 导出，
去掉 optimizer，保留 loader 需要的全部配置与语义版本；已在 12 个真实观测上与训练 checkpoint
逐位一致（`atol=0`）。`training/metrics.jsonl` 保留每一步的真实分子/分母与输入行数，
`training/validation.jsonl` 保留每次完整验证。

开发评测（256 个复用开发场景，0 截断）。设备与线程：AMD Ryzen 5 9500F（12 逻辑核），
torch 2.9.1+cu128，纯网络推理在 **CPU FP32、batch one、未显式设置线程数**（torch 默认 6 线程，
`OMP/MKL/OPENBLAS_NUM_THREADS` 均未设置）；GPU 仅用于训练。逐决策时延定义写在
`evaluation/paired_summary.json`：合并所有决策的百分位，不是"逐场百分位再取中位数"。

| 策略 | wins | losses | 均值 utility | 逐决策 p50 / p95（合并） |
|---|---|---|---|---|
| heuristic | 228 | 28 | 0.80732 | 0.024 / 0.057 ms |
| search（64 simulations，当前修复版） | 245 | 11 | 0.86784 | 155.9 / 1023.6 ms |
| **student（selected 纯网络）** | 235 | 21 | 0.82527 | 1.25 / 2.24 ms |

配对 bootstrap（20000 次，seed 20260918，条件于这一个固定训练种子与这一份开发集）：

| 比较 | 均值差 | 95% 区间 | 配对 / 丢弃 |
|---|---|---|---|
| student − heuristic | +0.01795 | [−0.00763, +0.04490] | 256 / 0 |
| student − search | −0.04257 | [−0.06346, −0.02438] | 256 / 0 |
| search − heuristic | +0.06052 | [+0.03411, +0.08900] | 256 / 0 |

**读法：** student 与 heuristic 的区间跨 0，不能据此声称超过启发式；student 明显低于 search。
本轮没有把"胜率必须上涨"设为门槛，也没有据此追加调参或改选 checkpoint。
Outcome/value 只作辅助诊断，不参与搜索或选点。

## 7. 本机实跑 / 源码推导 / 声明近似 / 仍未验证

- **本机实跑**：全部 4 道门槛、离线构建与 import、277 项 pytest（含 native，0 skip）、
  反事实与公开轨迹重放、意图表再生成、采集 96+24、训练 500 updates、开发评测 768 局、
  模型导出与 12 条 smoke。
- **仅源码推导**：两个上游规则修复（Disarm+ 力量、A18+ Nob 移动模式）、事件日志插桩、
  `<algorithm>` 头文件的来源判定；意图表分类（`ENGINE_DERIVED_ONLY` / `UI_SOURCE_VERIFIED`）。
- **声明近似**：sampler 的独立 RNG 流与公开区间上的均匀先验（含虱子候选集），
  不是原版联合后验；洗牌顺序在公开多重集上均匀随机。
- **仍未验证**：原版游戏差分（`game_differential_verified=false`，本机无合法游戏副本，
  该步骤未执行）；`miscInfo` 在 17 个遭遇之外的可达性；原版意图 UI 一致性；
  采样近似的真实后验偏差。本轮的开发集此前已被使用，后续复用会进一步削弱其留出性。

## 结论

本轮的目标是"修复通过并得到一组可加载、可复算的新 pilot 基线"，两点都已达成；
正确目标**不是**保证学生超过启发式，也不是原游戏超人类认证——两者都没有被声称。
