# 最小推理复现包

**这是派生产物，不是原始 checkpoint。** 为了让附件保持可传输，`*.inference.pt` 由
`runs/matrix/<cell>/model/best.pt` **去掉优化器状态、RNG 状态、epoch/best_val 记录**得到，
`model_state` 与 `model_config` 逐张量未改动。**没有重新训练、没有改动权重值。**

每个文件的 `source_checkpoint_sha256` 字段给出它对应的原始 checkpoint 哈希，
可用于与执行机上的文件核对。

| 文件 | 原始 checkpoint | 原始 SHA256 | 原始大小 | 派生文件 SHA256 | 派生大小 |
|---|---|---|---|---|---|
| `M128-R0-s17.inference.pt` | `runs/matrix/M128-R0-s17/model/best.pt` | 见 `MANIFEST.sha256` | 23.5 MB | 见 `MANIFEST.sha256` | 7.8 MB |
| `M192-R1-s43.inference.pt` | `runs/matrix/M192-R1-s43/model/best.pt` | 见 `MANIFEST.sha256` | 43.1 MB | 见 `MANIFEST.sha256` | 14.4 MB |

`M128-R0-s17` **同时是动作价值审计里冻结的 continuation policy**（`evidence_response.md` §C.4），
所以不需要另附第三个权重。

## 为什么是这两个

- `M128-R0-s17`：本轮冻结候选（资源最省那一档），也是审计 continuation。
- `M192-R1-s43`：12 个 run 里**唯一**一个开发效用相对启发式的 95% 区间排除 0 的
  （+0.02623，[+0.00214, +0.05219]，`evidence_response.md` §B.1）。

两个权重都**不**是「最强模型」的认证：它们都训练在 §0.1 描述的**有缺陷目标函数**下。

## 运行环境

与训练相同的解释器与环境即可：Python 3.12、`torch==2.9.1`、`numpy`。
不需要 CUDA——CPU float32 是这批测量里更快的推理设备（batch=1）。

```bash
cd <repo root>
.venv/bin/python review_weights/verify_inference.py
```

脚本会：

1. 加载两个 `*.inference.pt`；
2. 用 `master_seed=20260917`、`scenario_index=0` 重建**已冻结的公开开发场景**；
3. 取第 0–3 个公开状态（同一局内连续强制动作后的状态）；
4. 打印每个状态的 argmax 动作、top-3 概率与 value；
5. 与 `smoke_states_and_expected.json` 中记录的期望值逐项比对，不一致就非零退出。

**注意**：期望值是特定构建（`encoding_revision=2`、`observation_schema=2`）、
特定 torch 版本下的 float32 前向结果。换编码器或换精度会导致差异，
此时应视为**版本不匹配的警报**，而不是"权重坏了"。
