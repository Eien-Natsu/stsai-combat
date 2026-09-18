# S2R-REPRO 轮次小结

状态：**BLOCKED**（T0 的修复需要改判据，不在本轮授权内；其余 T1–T4 已完成并有证据）。
基线 `4462a7c048beebd1caed82a7c0ba1fc80d0cb16b`，实施分支 `agent/s2r-repro`，
目标分支 `s2/fixed-budget-data`（依赖 PR #2，未合并；见 PR 说明）。
request ID：`manual-chat-s2r-repro-001`（人工发起，无事件任务 ID）。

先读顺序：本文件 → `ci_failure_analysis.md` → `input_receipt.json` → `t3/`。

## 1. T0 CI 失败：根因已确定，修复需 reviewer 决定

CI run [35369602279](https://github.com/Eien-Natsu/stsai-combat/actions/runs/35369602279)
在 `2cc0c75` 上 111 passed / 1 failed / 6 skipped，失败为
`test_effective_batch_partition_invariance_end_to_end` 在 batch=8/accum=4 时
`policy.2.bias` 超出 `atol=1e-5, rtol=1e-4`。

定向运行 2 次（上限 2 次；本机 `+cu128` 与 CI 同款 `+cpu` 两个 wheel 结果**逐位相同**），
本机断言通过，余量只有 8–14 倍。根因：

1. `policy.2.bias` 是策略头输出 bias，给所有动作 logit 加同一常数，被掩码后的
   `log_softmax` 整体减掉 —— 解析梯度恒为 0。实测梯度 −2.7e−08 是 float32 相消残差，
   比其它参数（2.0e−03…2.8e−02）小 5 个数量级。前向验证：bias 平移 ±0.5/−3.0 时
   loss 变化为 0.0（`t0_gauge_check.json`）。
2. AdamW `eps=1e-8` 与残差同量级，更新量变成 `u = lr·g/(|g|+eps)` 的线性放大：
   实测三次更新 2.1791784e−04 / 2.1920493e−04 / 2.1882309e−04 与该公式一致到 8 位有效数字，
   灵敏度 `du/dg ≈ 2.25e3`，残差动 2% 就产生实测的 1.3e−06 参数差。
3. 携带正常梯度的参数在两种划分下只差 1 个 float32 ulp（量化极限），
   差异集中在 `policy.2.bias` 与 `in_proj_bias`（同属 eps 放大区）。

结论：**不是 loss/optimizer 缺陷，也不是"可以忽略的数值噪声"**，而是断言对"参数逐位可复现"
的隐含假设在规范方向上不成立。最小修复方案（本轮**未实施**）见 `ci_failure_analysis.md` §5：
把参数比较限制在携带信息的参数上，并对函数输出（掩码后 log-softmax / loss）断言不变性。
**需要 reviewer 决定是否批准该判据修改**；不批准则 CI 会继续红。

## 2. T1 七项输入：全部恢复并逐项核验

历史交付 ZIP `stsai_s2_review_253e391.zip` 的 `MANIFEST.sha256` **33/33 全部通过**，
28 项必需输入在包内齐全；7 项缺失项在原执行目录 `/workspaces/stsai_web` 与包内**逐字节一致**：

| 包内路径 | 字节 | 源（原执行目录） | 实测 sha256（= 包内 = 旧 manifest） |
|---|---|---|---|
| `model/D384_s17_selected.pt` | 7832457 | `model/D384_s17_selected.pt` | `ce9ff924…ef0648b` |
| `data/initial_scenarios.json.gz` | 30183 | `runs/s2/package_data/data/…` | `71ce6d34…2a16db2` |
| `data/composition_and_shards.json` | 62809 | `runs/s2/package_data/data/…` | `4266d4e4…1f67b2b` |
| `data/coverage.json` | 3739 | `runs/s2/package_data/data/…` | `d960bd92…9f066b5` |
| `evaluation/scenarios.json.gz` | 40016 | `runs/s2/package_data/evaluation/…` | `3a75ed61…55ff72b` |
| `evaluation/episodes.jsonl.gz` | 184546 | `runs/s2/evaluation/…` | `55e03a6a…154f30a` |
| `evaluation/decision_latency.jsonl.gz` | 861961 | `runs/s2/evaluation/…` | `c0c8ac50…49a835a3d2` |

hash 语义区分（`input_receipt.json` → `checkpoint_hash_semantics`）：

- 推理导出权重 7832457 B `ce9ff924…`，**无** `optimizer_state`，记录
  `source_step=500`、`source_sha256=7d758857…`；
- 训练 checkpoint `runs/s2/D384_s17/model/best.pt` 23483355 B `7d758857…`，**有** optimizer；
- 两者 hash 不同是设计，不是损坏；导出记录的来源 hash 与 provenance 的 selected hash 一致。

六个 run ×selected/last 共 12 个 checkpoint 全部与 provenance 记录吻合（含 S1R 复用的 D96_s17）。
四项与包不同处已逐条归因：`review/README.md` 是文档提交 2cc0c75 的重写，
`training/{metrics,validation}.jsonl.gz` 只是 gzip 容器重压（解压内容逐字节相同），
`tests/build_and_test.log.gz` 是打包时生成的 gzip。

## 3. T2 打包与输入契约

- 新增 `review/package_contract.py`：机器可读的必需输入清单（28 项，含
  `residency=repository|artifact`），**打包脚本与校验器共用同一份**（有测试防止漂移）。
- 新增 `review/check_review_inputs.py`（本轮入口）：`--repo/--package/--out`，14 项检查
  分列 PASS/FAIL/NOT_RUN 并写结构化 receipt；有任一必需项非 PASS 即非零退出。
- `scripts/make_s2_package.py` + `scripts/gen_s2_provenance.py`：支持
  `--artifacts <已验证的 artifact 根目录>` 与 `--lock <sha256 锁>`；不再依赖执行机的
  绝对路径或隐式 `runs/`。用 `--artifacts /workspaces/stsai_web --lock` 重建的包与历史包
  28 项输入逐字节一致（34 文件 / 12.68 MB），并通过全部 14 项检查。
- `review/run_review.py` 新增 `--jobs`（默认 2）并转发给 `offline_native_build.py`
  （底层原本默认 `min(4, cpu_count)`，超出项目 2 worker 预算）。
- 契约回归 14 项（`tests/test_review_inputs.py`）+ 转发测试 3 项
  （`tests/test_run_review_jobs.py`），负例包含：缺权重、缺逐场记录（仅汇总）、
  文件篡改、S1R/D96 权重替代、checkpoint 冒充导出、逐场与逐决策动作不一致、
  半填的键网格、旧语义版本、路径越界符号链接、不安全归档成员（`../`、绝对路径）、
  锁定值不符。**全部被拒绝且原始 stdout 保留**。

## 4. T3 干净环境复核：实际执行

隔离方式：子进程环境由显式字典构造（`HOME=<空目录>`、`PATH` 仅 venv+系统、
无任何 token 变量），无 SSH/keyring/gh 凭据可达（`t3/cold_review.json` → `environment`）。
本机无 docker，无法做到"不挂载宿主目录的容器级隔离"，这是本轮隔离的边界，已在
`cold_review.json` 中如实记录。

顺序与结果（第二次为最终一次，首次 31.4 s / 33.1 s，两次均全绿）：

| 步骤 | 结果 | 关键证据 |
|---|---|---|
| 附件校验 + 安全解包 | PASS | 33/33 manifest、无越界成员、7 项 artifact 锁定值一致 |
| 全新 clone（bundle → 253e391，detach） | PASS | 不复用旧 build/third_party/已装 native |
| 契约（对 clone 复检） | PASS | 14/14，含 `decision_records` 59812 条逐步对应 |
| PRE_PATCH + 5 补丁冷构建 | PASS | 编译 30 个目标 → `_lightspeed…so` 696184 B |
| 真实 import / revision / 补丁哈希 | PASS | `7476a8195402`，5 patches，`game_differential_verified=false` |
| 意图表重生成 | PASS | `intent_table.def` 50 行一致 |
| 全量 pytest | PASS | **277 tests, 0 failed, 0 errors, 0 skipped**，155 native/回归用例 |
| 公开反事实重放 | PASS | 5 步、1024 sampler seed、root stable |
| 代表模型 12 条 CPU smoke | PASS | 12/12，最大概率差 0.00e+00 |
| 独立复算 4096 场 | PASS | 复算前确认 4096 键完整无重复 |

统计闭环：复算 98 个数值字段与原 `s2_paired_summary.json` 全部在**预先声明的 1e-9** 容差内一致
（最大差异 **0.0**，98 项逐位相同；容差因此没有被用到），判定不变：仍为
**"insufficient evidence under the pre-registered rule"**（联合均值 0.0093522135，
95% 区间 [−0.0034831543, 0.0233042806] 跨零）。没有改阈值、没有剔除场景、没有把 3×256 当 768。

## 5. 没有验证的东西

| 项 | 状态 | 原因 |
|---|---|---|
| GCC 14.2 | **NOT_RUN** | 本机只有 GCC 12.2.0，无 gcc-14；不购买/安装系统编译器，也不从 GCC 12 成功推断 |
| CUDA / GPU | **NOT_RUN** | 本轮为 CPU 冷复核；无 GPU 训练或 CUDA 前反向检查 |
| 原游戏差分 | **NOT_RUN** | 无合法原版游戏副本；`game_differential_verified=false` 保持 |
| 另外五个模型 | 仅 hash 核验 | 12 个 checkpoint 与 provenance 全部吻合，但**未加载、未评测**（超出本轮"代表模型 12 条 smoke"预算） |
| Windows/MSVC 环境 | NOT_RUN | 未在 Windows 复核；隔离环境是 Debian 12/Python 3.12 |

## 6. 预算与交付

- 新增训练 runs **0**、真实数据优化 updates **0**、新采集 **0**、整场强度评测 **0**；
  未创建/读取最终 P6；未做 DAgger/hybrid/leaf value/扩容/teacher 变更。
- 完整冷复核 **2 次**（上限 2 次），31.4 s 与 33.1 s，单步最长 27.9 s（上限 1800 s）；
  T0 定向运行 2 次（≤60 s/次）。合计约 3 分钟，远低于 90 分钟预算。
- 编译并行 2（`--jobs 2`），统计/推理 torch 线程 1。
- 未新增云资源、未改系统依赖/驱动/SSH/安全设置、未重启。

## 7. 需要 reviewer 决定的问题

1. **T0 判据**：是否批准 `ci_failure_analysis.md` §5 的最小修复（排除规范方向 + 增加函数不变性断言）？
   不批准则 CI 的这条断言在换机器时会继续随机红。
2. **另外五个模型**是否需要在本机加载并评测（当前只核 hash），若需要请给出预算。
3. **GCC 14 复核**是否需要：需要则请指定可用的授权环境。
4. `.gitignore` 的 `logs/` 规则会连 `reports/` 下的同名目录一起忽略，本轮因此用了
   `reports/s2r/evidence/` 与 `reports/s2r/t3/step_logs/`（均已确认未被忽略）。
   若希望证据目录统一叫 `logs/`，请给出 `.gitignore` 例外写法。
