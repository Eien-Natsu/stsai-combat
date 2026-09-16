# 搜索成本分解与 hybrid 消融

**范围**：单机（WSL2 / RTX 5070）上的成本测量。**不是**战斗强度，**不是**原游戏性能。
**数据**：`reports/search_profile.json`；checkpoint `runs/dev_base2/model/best.pt`
（`encoding_revision=2`），24 个冻结诊断根，64 simulations，`configs/native_pilot.json`。

---

## 1 `hybrid` 到底做了什么（v0.1 结构核实）

原 `configs/native_pilot.json` 是 `use_leaf_value=false`，但 `hybrid` 仍然在
**每次新节点展开**时调用完整 evaluator。实测确认：

```text
evaluator_calls_per_decision = 65.0   (64 simulations)
```

即 **1 次根展开 + 64 次子节点展开**，每次 simulation 一次。

两件事随之明确：

1. 该调用的 **value 输出在 `use_leaf_value=false` 时被丢弃** —— 只有 prior 被使用。
2. 该调用发生在**展开时**，而不是节点被再次访问时。未被再次访问的叶子节点，
   其先验计算是纯浪费（"推迟计算不会被访问的叶节点先验"是任务书列出的优化方向）。

另外，`V` 模式下 `evaluator_calls_per_decision = 130`（每步 2 次：prior 与 value 分别来自
不同 evaluator），这是分离 prior 与 value 之后才看得见的成本。

---

## 2 请四种模式的对照（冻结根，每种 24 个决策）

模式定义按任务书 §4.3：

| 代号 | 树内 prior | 新叶处理 |
|---|---|---|
| **S** | 启发式 | 完整 rollout + 启发式 cutoff |
| **P** | 网络 | 与 S **完全相同**的 rollout 与 cutoff |
| **V** | 启发式 | 网络 leaf value（走 SplitEvaluator） |
| **PV** | 网络 | 网络 leaf value |

实现：`SplitEvaluator`（`src/stsai/search.py`）把 prior 与 value 拆开，
`P` 与 `S` 使用同一 rollout 与 cutoff，因此是干净的 prior-only 对照。

| 设备 | 模式 | evaluator 调用/决策 | p50 | p95 | cutoff 比例 |
|---|---|---|---|---|---|
| CPU | S | 65.0 | 140.5 ms | 349.4 ms | 0.00 |
| CPU | P | 65.0 | 286.6 ms | 614.6 ms | 0.00 |
| CPU | V | 130.0 | 169.6 ms | 218.5 ms | 1.00 |
| CPU | PV | 65.0 | 158.8 ms | 211.8 ms | 1.00 |
| CUDA | S | 65.0 | 136.3 ms | 360.5 ms | 0.00 |
| CUDA | P | 65.0 | 399.9 ms | 643.9 ms | 0.00 |
| CUDA | V | 130.0 | 364.7 ms | 477.3 ms | 1.00 |
| CUDA | PV | 65.0 | 354.1 ms | 389.1 ms | 1.00 |

**噪声下限**：`S` 完全不使用网络，因此 CPU 与 CUDA 的 `S` 应当一致 ——
实测 140.5 vs 136.3 ms（约 3%），这就是本机的可比精度。
（第一次运行时两者相差近 2×，当时后台还有别的作业在跑；带争用的数字不可用。）

### 结论 1：batch=1 时 GPU 比 CPU 慢

| | p50 |
|---|---|
| 单次 batch=1 前向，CPU | 1.31 ms |
| 单次 batch=1 前向，CUDA | 8.20 ms（另一轮 2.02 ms） |

计时包含同步与结果回传并按此口径报告。CUDA 在这个 batch 规模下**慢于** CPU，
原因是每调用一次的启动开销与主机往返远大于一次小矩阵乘的计算量。
这解释了上表：**所有使用网络的模式在 CUDA 上都比 CPU 慢。**

> 这不是"GPU 没用"，而是"**单决策、batch=1 的推理用 GPU 没有收益**"。
> 要用上 5070，需要跨战斗批量推理或批处理搜索 —— 二者都会改变搜索行为，
> 因此必须保留单线程确定性回归与等预算对照，目前**都还没有实现**。

### 结论 2：prior 与 value 的成本可以分开归因

以 CPU、S 为基准：

- **P − S = +146 ms**：网络 prior 的代价（约 2×）。它是**每次 simulation** 都付。
- **V − S = +29 ms**：网络 leaf value 的代价远小于 P，因为 `use_leaf_value=true` 时
  **不再跑 rollout**（cutoff 比例 1.00），省下的 rollout 抵消了大部分前向成本。
- **PV ≈ V**：加了网络 prior 后涨幅也有限。

所以"hybrid 慢"的主因不是 value 网络，而是**每个展开节点都做一次前向的 prior 计算**。

---

## 3 与既有评测的关系

`runs/native_hard_i3/eval`（128 局/策略）测得：

| 策略 | 平均效用 | p50 | p95 |
|---|---|---|---|
| search（启发式 prior，64 sims） | 0.8754 | 149 ms | 600 ms |
| hybrid（网络 prior + value） | 0.8649 | 437 ms | 912 ms |
| model（纯网络） | 0.8207 | 3.6 ms | 9.9 ms |

与本报告的分解一致：`hybrid` 的 p50 约为 `search` 的 3 倍，而其中
**prior 网络调用**是主要成本项。按任务书的晋级判据
（"同墙钟预算更强，或在预定非劣范围内明显更快"），
`hybrid` **两者都不满足**，**不晋级为默认策略**。

---

## 4 尚未做

1. **等墙钟预算对照**：本报告只做了固定 simulations（64）对照。
   任务书要求同时报告固定墙钟预算下的表现，并且**墙钟预算接口尚未实现** ——
   没有超时控制，也就不能声称满足时限。
2. **PyTorch Profiler 细粒度分解**：observation 构造 / encode / collate / H2D / forward /
   D2H / 搜索树管理 / simulator step / rollout 的逐项耗时未测。
   本报告的分解粒度只到"evaluator 调用次数"与端到端 p50。
3. **节点重访率**：未记录。这是判断"推迟叶先验"能省多少的前提。
4. **缓存与批量推理**：未实现。缓存键必须覆盖模型版本、完整合法输入、
   必要公开历史与动作映射，否则不同 belief 的统计量会被错误合并。
5. 所有数字都在**未认证模拟器**上；没有原游戏验证。

## 复现命令

```bash
.venv/bin/python scripts/profile_search.py \
  --checkpoint runs/dev_base2/model/best.pt \
  --output reports/search_profile.json --roots 24 --devices cpu cuda
```
