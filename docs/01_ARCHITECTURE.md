> 开发技术参考，来源固定为 `d2e1f0f1449e880af21912b17687d9527dfc49f6`；内容描述开发实现而非当前 main 的旧运行代码。执行权限/准确代码基线只见根 PROJECT_MAINLINE.md 与 NEXT_ACTIONS.md。
> [原参考文件](https://github.com/Eien-Natsu/stsai-combat/blob/d2e1f0f1449e880af21912b17687d9527dfc49f6/docs/01_ARCHITECTURE.md)。

# 技术参考：架构与学习目标

本文件解释实现，不定义当前计划或验收状态。目标/授权见 [主线](../PROJECT_MAINLINE.md)，执行见 [NEXT_ACTIONS](../NEXT_ACTIONS.md)。

## 数据流

真实环境保留私有随机状态 → 白名单公开 observation/合法动作 → 独立 agent seed 驱动的 sampler → 按公开历史组织的 PUCT → 搜索访问分布/真实执行结果 → replay 蒸馏 → 独立整场评测。
`search.run` 的公开接口不接收真实引擎内部状态。native 在审计过的窄范围副本重采样；这不是任意 BattleContext 都安全的保证，详见 [信息边界](02_FAIRNESS.md)。

## 搜索与后续优化

每次 simulation 从根采样潜在世界；动作边按后续公开观察摘要分支，不提前利用尚未观察到的未来。rollout 使用启发式，深度/步数截断记录 cutoff；实际根访问预算至少为合法动作数。
`use_leaf_value=false` 的当前配置不能解释为已验证学习叶值。跨决策树复用、宏动作、GPU 批量树推理只是后续候选，需独立授权和等预算评测。上游知道 RNG 的搜索器不能直接当公平教师。

## 单战目标与网络

终局效用定义见 `src/stsai/objective.py`：死亡为 0；存活为 `max(0, 0.8 + 0.2 * end_hp / max_hp - 0.02 * potions_used)`（药水系数可配置，当前 native 无药水）。它不是严格“先胜率后 HP”的词典序目标，也不是长期整局胜率。
网络提供合法动作 policy、11 类 outcome（死亡+10 个存活 HP 区间）和独立 sigmoid utility；outcome 可在相邻 HP 中心插值。value 不是校准后的生存概率，不能把 0.8 显示为 80% 胜率。
当前 loss_revision=2：policy 只对有选择的状态归一；outcome/value 只对已完成终局的有效 mask 归一。累计梯度按整个有效 batch 的分子/分母组合，而不是平均微批次均值；生产路径检查形状，避免 (B,1) 广播成 (B,B)。详见 `src/stsai/training.py` 及其回归测试。
实体 token/数值特征和可变动作指针组成模型输入，padding 被 mask，容量溢出显式报错。固定哈希 ID 词表不等于无碰撞枚举，正式全覆盖需另作版本化设计。

## 数据、恢复和模型选择

Replay 按 episode 保存 backend/split/配置/来源，场景 seed 仅作重放元数据，不进特征。训练读取使用有界 shuffle，验证遍历完整的冻结集合；不得混用 test 或不同目标的数据。
S2 按 V24 的逐战斗决策 KL 选择 checkpoint，并列取更早 step；`best.pt` 的文件名不等于实战最强。真实教师动作一致率与 visit-argmax/含被迫动作的 legacy 指标分开。
同数据同结构的恢复与新数据 warm-start 是不同操作；必须核对语义版本、数据指纹和 checkpoint 类型。恢复部分 epoch 不承诺精确数据游标恢复；跨设备/版本也不承诺逐位一致。
网络指导新搜索、重采样和 replay 混合不能保证单调变强。只有主线授权的受控实验与真实配对结果能决定是否推进；本参考不启动下一轮。
