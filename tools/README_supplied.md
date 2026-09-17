# STSAI 下一轮：泛化实验包

## 内容与边界

`STSAI_泛化实验执行任务书.md` 是目标机器 AI 的主要执行说明。
`experiment_protocol.json` 是机器可读的计划与待绑定字段，**不是已经支持的 stsai CLI 配置，也不是结果**。
`tools/diagnostic_stats.py` 是独立 NumPy 分析工具，不读取引擎、不修改仓库、不调用 GPU、不训练模型。
`tests/` 和 `reports/local_tool_tests.txt` 只验证本包的数值工具，不是目标仓库 195 项测试的重跑。

本包没有拿到目标机 git bundle、checkpoint 或逐场真实数据，不能宣称已独立复核最新 commit。
不要把计划值填入执行结果表。先在最新仓库导出工具要求的原始分布/逐样本预测，再分析。

## 本地工具测试

在已有 Python + NumPy 环境中运行，不要求升级目标机依赖：

```bash
python -m unittest discover -s tests -v
```

## 教师 KL 经验分解

输入 JSON 示例（**仅演示格式，不是真实战斗**）：

```json
{
  "score_space": "action_id",
  "states": [
    {
      "episode_id": "example_episode",
      "state_id": "example_state",
      "action_keys": ["a0", "a1"],
      "teacher_policies": [[0.8, 0.2], [0.2, 0.8]],
      "student_policy": [0.6, 0.4]
    }
  ]
}
```

```bash
python tools/diagnostic_stats.py kl teacher_samples.json teacher_decomposition.json
```

每个根内所有标签必须来自同一教师配置/合法信息状态/合法动作顺序；策略概率归一化、有限且非负。
经验分解方向固定为 `KL(teacher || student)`：

```
平均教师到学生 KL = 平均教师到经验均值 KL + 经验均值到学生 KL
```

代码不把 pairwise self-KL 视为噪声下限，不静默对零概率添加平滑，不验证原始行动等价性或隐藏信息公平性。
学生将教师正概率动作赋为 0 时，KL 无穷；工具直接拒绝，而不是悄悄截断以生成好看的指标。
若导出概率精度不足，导出端从 logits 以合适精度重新计算并归一化，不用工具修饰标签。

## 配对 Brier 差

输入 JSON 示例（**仅演示格式，不是真实模型成绩**）：

```json
{
  "design": "fixed_predictor_equal_weight_independent_clusters",
  "baseline_provenance": "example_only: baseline fixed on a separate calibration set",
  "rows": [
    {"cluster_id": "episode_a", "sample_id": "initial", "y": 0, "p_model": 0.2, "p_baseline": 0.3},
    {"cluster_id": "episode_b", "sample_id": "initial", "y": 1, "p_model": 0.7, "p_baseline": 0.3}
  ]
}
```

```bash
python tools/diagnostic_stats.py paired-brier predictions.json brier_difference.json --repetitions 10000 --seed 73021
```

输出的是按 cluster 等权、cluster 内先平均的 Brier 与配对差区间；model−baseline 越负越好。
同一局若导出多个状态，不能给它们不同独立 cluster id。
固定 baseline 的来源字段只是声明，工具无法代替 provenance 审计。
例子只有两个 cluster，不能用来推断真实性能；少量 cluster 的区间估计非常脆弱。

本工具不是所有设计通用的显著性检验：不处理复杂分层权重、训练种子×场景交叉随机效应、反复选择/可选停止，输入显式含这些字段时拒绝。
若同一卡组多个 episode 相关，应按你的估计目标和抽样设计另做分析，而不是任意改 cluster id 后宣称同一个估计量。

两个子命令均默认拒绝覆盖已有输出，确需覆盖时显式 `--force`。重复 pair id、NaN、错误概率范围与不一致动作长度均会报错。

## 下一次交接

实际附上源码 bundle/归档与关键 CSV/JSONL；只给目标机 `/tmp/...` 路径无法在另一会话复核。
不附游戏本体、账户、密钥或私人文件。所有模型/模拟器结果仍保留当前未认证边界。
