# 架构与算法

## 数据流

```text
真实环境（私有 RNG／真实抽牌顺序）
  └─ observe() → 白名单公开观察 + 完整合法动作
                    ├─ heuristic / Transformer → 候选动作先验
                    └─ sampler(agent_seed) → 与公开观察一致的模拟世界
                                             └─ history-indexed PUCT
搜索访问分布 + 整场真实执行结果
  → gzip JSONL replay → 蒸馏训练 → best/last checkpoint
  → 纯策略评测 / 网络辅助搜索评测 → 人工定义的晋级关卡
```

`search.run(obs, sampler, seed)` 不接收真实引擎内部状态。reference 从公开观察重建；native 在窄范围审计后的副本上重新采样未来 RNG 和未知牌序。后者需要逐敌人确认隐藏字段没有残留，不能把复制整个引擎误称为通用安全解法。

## 搜索

树节点按从当前根开始的动作与**公开观察历史**组织。动作边下用公开观察摘要分出随机结果子节点，因此两个未来抽牌结果可以产生不同决策；未知的未来结果不能在抽到之前用于当前决策。不是先看完整未来随机序列然后把每个完全信息最优动作平均。

每次 simulation 在根采样一个与当前观察一致的潜在世界；通过 PUCT 选择动作，遇到新公开观察节点时展开。默认通过带少量随机性的启发式 rollout 到终局；超过深度／步数则使用启发式 cutoff 值并记录 cutoff_fraction。全部根动作至少访问一次，因此实际预算为 `max(simulations, legal_action_count)`。

默认配置 `use_leaf_value=false`。训练初期不把未校准价值网络直接替代 rollout。后续可打开 leaf value，但要同时评测校准误差、强度及延迟。默认搜索无跨决策树复用、无宏动作压缩、无跨进程 GPU 批量树推理；这些是明确优化任务。

## 学习目标：不要误读为长期胜率

当前局内终局效用定义为：

```text
死亡：0
存活：max(0, 0.8 + 0.2 × end_hp / max_hp − 0.02 × potions_used)
```

这是本项目明确选择的单场工程目标，不是数学意义上的“先绝对最大化胜率，再最大化 HP”的词典序目标，也不是未来整局胜率。系数可配置，但改变后必须新建数据目录；不同目标的数据不能不加说明混训。原版 pilot 无药水，药水罚项暂不生效。

即使 0.8 的存活项较大，期望效用仍可能在少量胜率和大量 HP 间作交换；因此评测必须同时单独列出死亡率。全卡池后 Feed、Ritual Dagger、遗物充能、药水保存等长期资源不能直接用此标量完全表达，需增加资源头／上下文价格或外部整局 value。

网络输出：合法动作 policy logits、11 类 outcome logits（死亡 + 10 个存活 HP 区间）、独立 sigmoid utility value。outcome 目标在相邻 HP 中心插值；非终局截断样本 policy 可学，outcome 和 value 用 mask 排除。value 头预测当前数据行为策略下的效用，不是未经检验的校准死亡概率。不要把 value=0.8 显示为“80% 胜率”。

训练 loss 为 policy CE + 0.5 × outcome CE + utility MSE。网络使用状态实体 token、数值特征和可变长度动作指针，动作由 source(s)、target、类型与数值提示打分。padding 被 mask；超过容量显式报错，不静默截断。

ID 使用固定哈希映射到 8,192 词表，不依赖 Python 随机 hash。存在哈希碰撞的理论可能；扩展正式全卡池时建议改为版本化、无碰撞枚举词表。初版不使用文本 LLM。

## 迭代与数据

首轮 heuristic 搜索提供访问分布。后续模型只提供搜索先验／可选叶值，执行更高预算搜索获取新标签，蒸馏到下一轮模型。`--sample-actions` 从根访问分布采样行为，用于扩展覆盖；旧数据通过 `--replay` 保留。

这种迭代不是训练完成即保证单调变强，也不具备精确 AlphaZero 理论前提。teacher 不佳、分布太窄、rollout 偏差和高 cutoff 都会让进步停止。需要真实 paired evaluation 决定保留哪一版。

Replay 按 episode 压缩保存，带 split、backend、模型 hash、搜索参数、迭代信息。场景 seed 存元数据用于重放，绝不作为 observation 特征。训练加载器有有界 shuffle buffer，不把全部数据载入 RAM。
