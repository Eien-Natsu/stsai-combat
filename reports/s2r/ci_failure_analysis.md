# T0：CI 批次划分一致性失败的定向诊断

状态：**根因已确定，修复判据不在本轮授权内 → BLOCKED，交回 review 决定。**
本文件只记录诊断与证据，没有改动 loss、optimizer、模型语义或任何测试。

## 1. CI 实际报告的事实

| 项 | 值 |
|---|---|
| run | [35369602279](https://github.com/Eien-Natsu/stsai-combat/actions/runs/35369602279)（job 105680168167） |
| 事件 / 分支 | `pull_request` / `chatgpt/consolidate-mainline` |
| 被测 head | `2cc0c759a4900bb3822a47609bdf6a0a62f824b8` |
| 被测 merge | `3eb32ec766476016964248ee0b9791a17c3da72e`（文档记录值，GitHub 已回收该 ref，无法重新 fetch 校验） |
| 结果 | 111 passed, 1 failed, 6 skipped；后续 CPU smoke 跳过 |
| 失败用例 | `tests/test_training_loss.py::test_effective_batch_partition_invariance_end_to_end` |
| 失败断言 | `torch.allclose(reference["policy.2.bias"], state["policy.2.bias"], atol=1e-5, rtol=1e-4)` |
| 打印值 | reference(32x1) `tensor([-0.0047])` vs 8x4 `tensor([-0.0046])` |

被测代码与本次实施基线一致：`git diff 2cc0c75 4462a7c -- src tests review scripts` 为空，
`git diff 4462a7c origin/pr-2-merge -- src tests review scripts` 也为空。
即：CI 测的 `src/stsai/training.py`、`tests/test_training_loss.py` 与本分支逐字节相同
（`docs/s2` 之外只有 3 个文档文件变化）。

CI 环境（日志）：ubuntu-24.04 image `20260907.300.1`、Python 3.12、torch 2.9.1+cpu、
pytest 8.3.5、numpy 2.2.6。日志未记录 runner 的 CPU 型号。

## 2. 定向复现：本机两次，均 PASS，但余量只有 8–14 倍

命令（隔离 CPU 环境，无写凭据；单次 timeout 60s）：

```bash
# run 1：历史执行环境（torch 2.9.1+cu128）
timeout 60 /workspaces/stsai_web/.venv/bin/python reports/s2r/t0_partition_diagnose.py \
    --out /tmp/t0_run1_historical_env.json
# run 2：CI 同款 CPU wheel（torch 2.9.1+cpu）
timeout 60 /home/node/s2r-cpu-venv/bin/python reports/s2r/t0_partition_diagnose.py \
    --out /tmp/t0_run2_cpu_torch.json
```

两次 exit code 均为 0，断言在本机**通过**。诊断脚本调用未修改的 `stsai.training.train`
跑同一份合成数据的三个划分，并在 `AdamW.step` 外层记录更新前的梯度（原始 step 照常执行）。

| 划分 | `policy.2.bias` 梯度 | 施加的 AdamW 更新 | 步后参数值 | 对 32x1 的最大参数差 |
|---|---|---|---|---|
| 32x1 | −2.6542693e−08 | +2.1791784e−04 | −0.0042430726 | — |
| 16x2 | −2.7124770e−08 | +2.1920493e−04 | −0.0042417855 | 1.2871e−06 |
| 8x4 | −2.6950147e−08 | +2.1882309e−04 | −0.0042421673 | 9.0525e−07 |

两次运行的梯度、更新、参数差**逐位相同**（`+cu128` 与 `+cpu` 两个 wheel 在本机给出同一结果）。
所以本机差异不是 torch 构建造成的；CI 与本机的唯一已知差异是 CPU 与内核分派。

所有划分的初始值一致：−0.0044609904289245605。

## 3. 逐参数差异的分布：差异集中在两个参数上

8x4 对 32x1 的差（全参数排序前 8 名，`t0_partition_diagnose.py` 记录全表）：

| 参数 | 最大绝对差 | 该参数量级 | 解释 |
|---|---|---|---|
| `policy.2.bias` | 9.05e−07 | 4.24e−03 | 梯度是相消残差（见 §4） |
| `encoder.layers.0.self_attn.in_proj_bias` | 2.56e−07 | 3.00e−04 | 同样落在 Adam eps 放大区（见 §4.3） |
| `encoder.layers.0.linear1.bias` | 6.71e−08 | 2.47e−01 | ≈1 ulp |
| `encoder.layers.0.self_attn.out_proj.weight` | 1.49e−08 | 2.50e−01 | ≈1 ulp |
| 其余全部参数 | ≤ 7.45e−09 | ≥ 0.125 | ≤1 ulp |

其它参数的梯度量级是 2.0e−03 … 2.8e−02；`policy.2.bias` 是 2.7e−08，
比最小的其它参数还小 **5 个数量级**。携带正常梯度的参数在两种划分下只差 1 个 float32 ulp，
这是 `p -= u`（u ≪ p）本身的量化极限，不能更小。

## 4. 根因

### 4.1 `policy.2.bias` 的梯度在解析上为零

策略头最后一个 `Linear(d_model, 1)` 的 bias 给**所有**动作 logit 加同一个常数；
`model.py:47` 在加完之后才 `masked_fill(~action_mask, -1e9)`，于是合法动作的
`log_softmax` 把这个常数整体减掉。因此该参数是规范（gauge）方向：不改变任何预测、也不改变 loss。

前向验证（`reports/s2r/t0_gauge_check.py`，只做前向，无优化步）：

| bias 平移 | loss 变化 | log-softmax 最大变化 |
|---|---|---|
| +0.5 | 0.0 | 1.19e−07 |
| −3.0 | 0.0 | 2.38e−07 |
| +1000 | 3.18e−07 | 1024.0（超出 float32 有效位数后的相消） |

loss 完全不变 ⇒ 该参数的解析梯度是 `Σ_j (p_j − q_j) = 1 − 1 = 0`。
实测的 −2.7e−08 是 float32 求和相消后的残差，不是信号。

### 4.2 AdamW 的 eps 把残差线性放大 2.25e3 倍

`torch.optim.AdamW` 默认 `eps=1e-8`，第一步更新为 `u = lr·g/(|g|+eps)`。
本参数 `|g| ≈ 2.7e-8 ≈ 2.7·eps`，分母由 eps 主导，于是

```
u(2.6542693e−08) = 3e−4 · 2.6542693/(2.6542693+1) = 2.1791784e−04   ← 与实测一致到 8 位有效数字
u(2.7124770e−08) = 2.1920493e−04                                     ← 一致
u(2.6950147e−08) = 2.1882309e−04                                     ← 一致
```

灵敏度 `du/dg = lr·eps/(|g|+eps)² ≈ 2.25e+03`：残差只要变动 2%（约 5.8e−10），
参数就动 1.29e−06 —— 正是实测的划分间差异。**更新量测的是浮点噪声，不是梯度。**

### 4.3 这不是孤例：`in_proj_bias` 落在同一放大区

`nn.MultiheadAttention` 把 `in_proj_bias` 零初始化，所以步后数值 = 一步更新本身。
它有 48 个分量，其中梯度落在 eps 邻域（|g| ~1e−7）的分量同样被线性放大，
`du/dg ≈ 248`、残差变动 ~1e−9 就给出实测的 2.6e−07。机制与 §4.2 完全相同。

### 4.4 为什么 CI 失败而本机通过

同一机制，两种划分给出不同残差（本机 2.65/2.71/2.70e−08，差异 2%），
经 eps 放大成 1e−6 量级的参数差。断言容差是 `atol=1e-5 + rtol=1e-4·4e-3 ≈ 1.05e-5`，
本机余量只有 8–14 倍；换一套 CPU 内核（不同的归约顺序即可）残差偏离几个百分点，
参数差就越过 1.05e−5。CI 打印的 `-0.0047` / `-0.0046`（共享初值 −0.004461）
与"同号但幅度不同的更新"一致，与"两个划分更新相差 ~1e−4…2e−4"一致。
CI runner 的 CPU 型号未记录，无法在本机逐位复现那一次；复现到的是**机制**。

### 4.5 结论的边界

- 这不是"数值噪声可以忽略"：该参数确实动了 2.2e−04（0.73·lr）/步，方向由噪声决定；
  但它动了也不影响模型输出（§4.1），所以**不是正确性缺陷**。
- 这也不是 loss/optimizer 的语义错误：`combine_numerators` 的有效 batch 分母、
  逐 microbatch 累加分子、`policy_term` 的 rank/length 契约在三个划分下给出相同的
  有效 batch 数值（单位测试 `test_effective_batch_mean_ignores_the_partitioning` 已覆盖）。
  真正被打破的是断言对"参数逐位可复现"的隐含假设。
- 本机 PASS **不能**证明 CI 那条断言成立；它只说明本机余量小到跨机器不保。

## 5. 需要 reviewer 决定的最小修复方案（本轮**未实施**）

不在本轮改动，因为 NEXT_ACTIONS 明确：改判据必须先 BLOCKED 交回 review。

方案 A（推荐，改动最小）：断言分两类。
保留对**携带正常梯度**参数的 `allclose`；把 `policy.2.bias` 从参数比较里显式排除，
并在测试 docstring 写明它是 §4.1 证明的 loss 无关方向（可附 `t0_gauge_check.py` 的结论），
而不是"容差不够所以跳过"。
再用同一批数据断言**功能不变性**：三个划分的 `policy_logits` 掩码后 log-softmax 与 loss
在 ulp 级一致。该规则要抓的旧错误（按 microbatch 均值平均）会同时污染所有 informative 参数
和函数输出，检测力不减。

方案 B：把参数比较改成在"对 loss 有影响的方向"上比较（投影掉规范方向），
等价于 A 但更抽象，不建议在测试里引入。

明确不做：放宽容差、删除/skip 用例、改 loss/optimizer、给 bias 特殊梯度处理——
最后一项会变成训练语义变更，超出本轮授权。

## 6. 本轮用量与证据位置

- 定向运行：**2 次**（上限 2 次），单次 timeout 60s，实际各约 10–20s；合计远低于 90 分钟预算。
- 未做任何优化步以外的训练、未使用真实数据、未启用 GPU。
- 证据文件：
  - `reports/s2r/evidence/ci_run_35369602279.log`（CI 完整日志）
  - `reports/s2r/evidence/t0_run{1,2}_stdout.txt`、`t0_run{1,2}_exit.txt`
  - `reports/s2r/evidence/t0_run1_historical_env.json`、`t0_run2_cpu_torch.json`（全部参数的完整差异表）
  - `reports/s2r/t0_partition_diagnose.py`、`reports/s2r/t0_gauge_check.py`
  - `reports/s2r/t0_gauge_check.json`、`reports/s2r/t0_runs_summary.json`

## 7. 未解决项

- CI 那次运行的 runner CPU 型号未知，本机无法逐位复现该次残差（只复现机制）。
- `3eb32ec…` 这个 merge SHA 只来自文档记录；GitHub 已回收 refs/pull/2/merge 的旧值，
  当前该 ref 指向 d4f93ab（4462a7c 并入 de266c4），代码内容一致（§1）。
- 本机没有在"非 1 线程"或其它 ISA 下验证残差如何变化——那需要额外运行，超出 T0 的 2 次限额。
