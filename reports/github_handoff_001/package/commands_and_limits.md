# S2 实际命令与资源限额

本文件记录这一轮**实际执行**的命令与用量。协议里的上限写在 `protocol.json`，
这里写的是实际发生的次数与规模，两者不符处照实列出。

## 前置小修复（第 1 节）

```bash
# 补丁序列从 4 个扩到 5 个：0005 只给 CardManager.cpp 加一行 #include <algorithm>
python scripts/patch_series_receipt.py          # 从锁定 revision 建 detached worktree，按序 apply 全部 5 个
python scripts/gen_native_sources.py            # 重新生成 PRE_PATCH 快照与 manifest
python scripts/scan_std_includes.py             # 源码扫描：补丁后引擎代码中不再有该形态
python scripts/gen_semantic_compatibility.py    # 0005 只增头文件的论证 + 256 场重放回归
python scripts/build_native.py --jobs 8         # 本机构建（GCC 12.2）
python -m pytest tests -q                       # 本机全量
```

干净目录验证（review 入口，含完整 configure/build 日志与 exit code）见
`tests/build_and_test.log.gz` 与 `tests/junit.xml`。

## 数据（第 2 节）

```bash
python scripts/s2_freeze_lists.py               # 校验 S1R 分片、物化并冻结两份开发集
python scripts/s2_collect_add288.py             # 唯一一次新增采集：train index 96–383，2 worker
```

| 项 | 值 |
|---|---|
| 新增采集次数 | **1**（协议上限 1） |
| worker | **2**（上限 2） |
| 新增局数 | 288（上限 288） |
| 教师预算 | 64 simulations，`max_depth=64`，`rollout_limit=128`，`c_pue=1.5`，`rollout_epsilon=0.12`，`use_leaf_value=false`——与 S1R 完全相同 |
| 动作采样 | `sample_actions=true`，`iteration=0`，`max_actions=256` |
| 采集耗时（教师搜索） | 694.9 s |
| 结果 | 288 局全部完成，0 截断，253 胜，5117 行 |

D96/V24 未重新采集：分片对 S1R 交付 manifest 逐文件校验通过后才复用。

## 训练（第 3 节）

```bash
python scripts/s2_train_matrix.py               # 5 个新 run，逐个独立进程
python scripts/s2_training_summary.py           # 汇总六个逻辑 run
```

| run | 数据 | init_seed | 实际 updates | 耗时 |
|---|---|---:|---:|---:|
| D96_s17 | D96 | 17 | 复用 S1R，未重训 | — |
| D96_s29 | D96 | 29 | 500 | 30 s |
| D96_s43 | D96 | 43 | 500 | 26 s |
| D384_s17 | D384 | 17 | 500 | 28 s |
| D384_s29 | D384 | 29 | 500 | 31 s |
| D384_s43 | D384 | 43 | 500 | 28 s |

- 新训练 run 次数 **5**（上限 5）；每个 run **500** 次更新（上限 500）。
- `data_seed=42` 全程不变；随机初始化，无 warm start；模型/优化器/loss 权重/梯度裁剪与 S1R 完全一致。
- 环境：单张 RTX 5070，bf16，Python 3.12.14 / PyTorch 2.9.1+cu128；未升级软件或硬件，未使用云端。

## 对局评测（第 4 节）

```bash
python scripts/s2_evaluate.py                   # 6 个 selected 网络 + heuristic + search，各 512 场
python scripts/s2_paired_stats.py               # 预注册的配对分析
python review/recompute_s2.py --package <pkg>   # 独立复算
```

| 项 | 上限 | 实际 |
|---|---:|---:|
| 纯网络场次 | 6 × 512 = 3072 | 3072 |
| 基线场次 | 2 × 512 = 1024 | 1024 |
| 合计 | 4096 | 4096 |
| 每场动作上限 | 256 | 256 |
| bootstrap | 20000 次 / seed 20260920 | 同 |

- 全部策略 CPU FP32、batch one、**torch 线程固定为 1**（含基线），环境记录在 `provenance.json`。
- heuristic 与 64-sim search 在本轮代码下**重新跑过**，没有沿用 S1R 的历史成绩当作当前基线。
- 未静默剔除任何一场：运行异常会中止评测；达到动作上限的场次单独记为截断，
  在保守主汇总中效用记 0，并另给"仅完成对"的敏感性结果。

## 禁止范围（第 6 节）

未做：192 维模型、R1、容量/结构变化、reward 或 teacher 预算变化、DAgger、hybrid、
leaf value、机制扩展、第四个训练种子、最终 P6；未创建或读取 P6 manifest；未使用云端。
