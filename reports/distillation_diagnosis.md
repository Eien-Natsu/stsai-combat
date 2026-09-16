# 蒸馏诊断报告

**范围**：工程正确性与开发集诊断。所有数字来自开发数据，**不是**原游戏验证，**不是**战斗强度。
**基线**：`reports/baseline_freeze.json`，`baseline_id = ec5bef08…`（commit `e09c652` 之后）。
**数据**：`data/dev/train`（96 局，79 胜 17 负，1774 状态）、`data/dev/val`（24 局，23 胜 1 负，330 状态）。
两个集合都在 `observation_schema=2 / encoding_revision=2 / scenario_revision=3` 下重新采集。

> **重要**：v0.1 时期采集的全部数据与 checkpoint 已因 schema 升级而**不可用**。
> 这是有意的：它们的 observation 含有一个被判定为泄漏的字段（见 §1），
> 旧 checkpoint 现在会**明确拒绝加载**而不是被静默套上新语义。

---

## 摘要：五个结论

1. **发现并修复了一个我自己引入的公平性泄漏**（§1）。上一轮把敌人"计划招式"的
   上游名称写进 observation，实测有 9 组 (怪物, intent, 伤害, 命中数) 对应两个不同招式 ——
   玩家看不出区别，模型却拿到了确切身份。已移除。顺带修好了 `moveHistory` 被当成
   "已执行历史"的语义错误。
2. **原来的 top-1 指标是错的，而且被强制动作状态抬高**（§2）。
   决策状态下学生与教师**实际动作**的一致率是 **0.587**，不是报告里的 0.69–0.72。
3. **网络能完美拟合教师**（§3）：256 个固定状态的训练 KL 降到 **7.6e-06**，输入冲突 0 组。
   所以验证集上的差距**不是**表达能力或实现问题。
4. **教师标签确实带噪声，但噪声不是主要项**（§4）。在**同一批状态**上做受控分解：

   | 量 | 值 |
   |---|---|
   | 教师自身重跑 KL（噪声下限） | **0.0228** |
   | 单次标签到多次均值的 KL | 0.0082 |
   | 学生相对教师标签的 KL | **0.0885** |
   | **学生超出教师自洽性的部分** | **0.0657（约 3.9×）** |
   | 教师动作类一致 / 学生一致 | 0.882 / **0.698** |

   学生误差约为教师自身噪声的 **3.9 倍** —— 差距主要在学生身上，不在标签噪声。

5. **按诊断建议做的"提高教师预算重标"实验是负结果**（§5）：
   用 4 倍预算（256 sims）重标训练集后，学生相对更好教师的 KL 只从 0.1354 降到 0.1290，
   动作一致率反而从 0.5547 降到 0.5304。**重标没有解决问题。**

> **一处需要更正的过程结论**：本轮中间曾根据（不同状态集上的）两个数字得出
> "学生误差与教师噪声同量级、学生已到噪声下限"。在**同一批状态**上重测后该结论**不成立**，
> 已由 §4 的受控分解取代。上面的数字是更正后的。

---

## §1 公开信息审计

### 1.1 已修复：泄漏的"计划招式"

上一轮把 `observed_move`（= `moveHistory[0]`，即**即将执行**的招式）从 enum 序数改成上游名称。
公平性审计的做法：枚举全部 17 个受支持遭遇、每个 40 个种子，按
`(怪物, intent, intent_damage, hits)` 分组，看是否有组对应多个招式名。

结果：90 个组中 **9 组有歧义**。

| 怪物 | 导出意图 | 歧义的两个招式 |
|---|---|---|
| JAW_WORM | ATTACK 12/17/22/27/32/37 | CHOMP、THRASH |
| ACID_SLIME_M | ATTACK 12 | CORROSIVE_SPIT、TACKLE |
| LAGAVULIN | BUFF | SLEEP、SIPHON_SOUL |
| LOOTER | BUFF | ESCAPE、SMOKE_BOMB |

这些情况下玩家在意图阶段**无法**区分（Jaw Worm 的 Chomp 与 Thrash 在力量缩放后伤害数字相同），
而 JVM 侧导出名称等于直接把答案给了模型。

**修复**：计划招式不再导出。`intent`、`intent_damage`、`hits` 已经承载了玩家能看到的一切。
回归测试 `test_planned_move_is_never_exported` 与
`test_encounter_stays_inside_its_declared_move_space`（覆盖表见下）。

### 1.2 顺带发现的第二个问题：`moveHistory` 不是"已执行"历史

审计"已执行招式"通道时发现 `moveHistory[1]` 是**最近两次 roll 过的招式**，
不是最近两次执行过的。一个每回合都攻击的 Cultist，`previous_move` 永远停在 `INCANTATION`：

```text
t0 prev=INVALID             intent=BUFF
t1 prev=CULTIST_INCANTATION intent=ATTACK dmg=6
t2 prev=CULTIST_INCANTATION intent=ATTACK dmg=11   <- 应该是 DARK_STRIKE
t3 prev=CULTIST_INCANTATION intent=ATTACK dmg=16
```

原因是复用同一招式的怪物不会重新 roll。**修复**：适配器自己记录"上一回合观察到的当前招式"，
并把"战斗已分出胜负但敌人仍存活"（例：Looter 逃跑结束战斗）也算作已执行 ——
死亡敌人可能在被杀前没行动，所以不计入。

已执行招式的身份是公开的：玩家看着它结算（伤害数字、格挡、施加的状态都能区分那 9 组歧义对）。

### 1.3 字段覆盖与版本

- `SCHEMA_VERSION` 1 → 2（观察 schema），`ENCODING_REVISION` = 2，`UTILITY_REVISION` = 1，
  `SAMPLER_REVISION` = `independent_rng_approximation/1`，`SCENARIO_REVISION` = 3。
  全部写进 collection settings、checkpoint 与 `baseline_freeze.json`。
- `model.load_checkpoint` 现在**拒绝**编码语义不同的 checkpoint（缺失字段按 revision 1 处理），
  实测旧 checkpoint 被拒绝：`Checkpoint was trained on encoding_revision=1 but this build uses 2`。
- **尚未做**：逐字段覆盖表（来源／玩家是否可知／是否导出／编码器是否使用／采样器处理／对应测试）
  还没有生成机器可读版本。已确认的是 0 组编码输入冲突（§3），
  但 token 哈希碰撞与"同名不同升级/变费/免费/保留"的区分**没有单独取证**。

---

## §2 指标分解

### 2.1 旧指标错在哪（实测占比）

`search.py` 在根访问数并列时用 Q 值继续打破并列：

```python
index = max(range(len(visits)), key=lambda j: (visits[j], root.edges[...].q))
```

而 `training.py` 比的是 `policy.argmax()`。两者在并列时**不是同一个动作**。

在真实开发数据上实测：

| 数据 | 决策状态 | `policy.argmax()` ≠ 教师实际动作 | 根访问并列率 |
|---|---|---|---|
| train | 1331 | **51 (3.8%)** | 170 (12.8%) |
| val | 247 | **7 (2.8%)** | 43 (17.4%) |

所以：这个现象**真实存在但很小**，不足以解释 0.72 与 1.0 的差距。
把它当成主因会是错的 —— 这里如实报告占比，不夸大。

### 2.2 真正抬高数字的是强制动作状态

**25% 的状态只有一个合法动作**（train 443/1774，val 83/330）。这些状态一致率按定义为 1.0。
把它们剔掉之后的真实数字：

| 指标 | 全部 330 状态 | **仅 247 个决策状态** |
|---|---|---|
| raw_top1（旧口径） | 0.6636 | **0.5506** |
| 与教师**实际动作**一致 | 0.6606 | **0.5466** |
| 访问并列容忍一致 | 0.7121 | **0.6154** |
| 动作等价类一致 | 0.7061 | **0.6073** |
| 教师熵 H | 0.9914 | **1.3245** |
| 策略 KL | 0.0894 | **0.1194** |
| 交叉熵 CE = KL + H | 1.0808 | **1.4439** |

训练日志也已同步修正，现在同时报告
`teacher_top1_agreement`（旧）、`teacher_choice_agreement`、
`teacher_choice_agreement_decision_states`、`policy_kl`、`teacher_entropy`：

```text
teacher_top1_agreement                    : 0.6970
teacher_choice_agreement                  : 0.6909
teacher_choice_agreement_decision_states  : 0.5870   <- 诚实数字
decision_states 247 / forced_states 83
policy_kl 0.0823 / teacher_entropy 0.9914
```

**"0.72" 这个数字从来不代表学生在有得选的时候有多准；它代表的是 0.587。**

### 2.3 交叉熵平台期不等于学不动

按 `CE = KL + H` 分解后，分层的结论很清楚 —— 平台期主要是**教师本身就不确定**：

| 分层 | 状态数 | raw_top1 | 动作类一致 | KL | 教师熵 H |
|---|---|---|---|---|---|
| 合法动作 2–3 | 33 | 0.667 | 0.818 | 0.0342 | **0.494** |
| 合法动作 4–6 | 151 | 0.589 | 0.662 | 0.0969 | 1.284 |
| 合法动作 7+ | 63 | **0.397** | 0.365 | 0.2181 | **1.857** |
| 低血量 | 30 | 0.733 | 0.733 | 0.1237 | 0.992 |
| 中血量 | 131 | 0.519 | 0.565 | 0.1335 | 1.471 |
| 回合早期 | 165 | 0.545 | 0.612 | 0.1236 | 1.370 |
| 回合后期 | 26 | 0.731 | 0.731 | 0.1126 | 0.938 |

合法动作越多，教师越不确定（H 从 0.49 涨到 1.86），一致率随之从 0.67 掉到 0.40。
低血量时教师变得果断（H 0.99），一致率升到 0.73。
**这是"教师软标签 + argmax 指标"的固有现象，不是容量墙。**

### 2.4 动作等价类

`distill_diagnosis.py` 的等价类**保守**定义：`kind + card_id + 目标槽位 + 升级数 +
当前费用 + 消耗 + 虚无 + 免费 + 保留 + specialData + 类型`。
同名卡不因同名合并，不同敌人槽位不因同名敌人合并。原始 action-id 指标一并保留。

决策状态上类一致率 0.607 > 原始 0.551：约 6 个百分点来自"等价动作被判错"。
等价类失败案例**尚未**单独沉淀成测试集，这是缺口。

---

## §3 最小可拟合实验：能拟合

`scripts/fit_probe.py`，256 个固定决策状态，冻结教师软标签，关闭 dropout / weight decay /
value 与 outcome 辅助损失，FP32，仅拟合 policy。

| 项 | 值 |
|---|---|
| 使用状态 | 256（**0 组输入冲突**：编码后逐字节相同却标签不同） |
| 教师熵 | 1.3397 |
| 训练步数 | 1500（上限） |
| **最终训练 KL** | **7.63e-06** |
| 目标 | ≤ 0.01 nat → **达成**（第 200 步就到 0.014） |

KL 曲线：`0.347 (step 1) → 0.044 (100) → 0.0044 (300) → 3e-05 (900) → 7.6e-06 (1500)`

**结论**：没有输入别名、没有动作错位、没有 mask 错误、这个规模下没有表达能力问题。
验证集上的差距只能来自泛化、数据量或**教师标签噪声** —— 于是下一步查教师。

---

## §4 教师稳定性与噪声下限

`scripts/teacher_stability.py`。64 个分层状态从开发轨迹**重放**到达
（逐步核对 `observation_key`，**0 次重放失败**），每个状态用 4 个独立搜索种子重跑。

| simulations | 两两动作类一致 | 四种子全一致状态 | 两两策略 KL | 根访问并列率 | 单次耗时 |
|---|---|---|---|---|---|
| **64（训练用的预算）** | **0.7995** | **42 / 64** | **0.0806** | 0.664 | 0.23 s |
| 256 | 0.8333 | 47 / 64 | 0.0823 | 0.477 | 0.97 s |
| 1024 | 0.9297 | 57 / 64 | 0.1199 | 0.356 | 3.88 s |

注意 KL 随预算**上升**（0.081→0.120）并不矛盾：预算越高访问分布越尖锐，
两次独立运行即使选同一个动作，分布形状差异也可能更大。**动作一致性才是这里的关键指标。**

### 把噪声与学生误差分开（同一批状态）

上面那张表的数字来自 `data/dev/train` 的分层状态，而学生的 KL 来自 `data/dev/val` 的决策状态。
**不同状态集上的两个数字不能相减**，所以另做一次受控测量（`scripts/noise_floor.py`，
24 个 val 状态、每个教师跑 4 次、预算 256）：

| 量 | 值 | 含义 |
|---|---|---|
| `teacher_self_kl` | **0.0228** | 教师两次独立运行之间的 KL：完美学生也达不到比这更低 |
| `mean_teacher_kl` | 0.0082 | 单次标签到多次均值的 KL：单个样本的固有噪声 |
| `student_kl` | **0.0885** | 学生相对教师（多次均值）标签的 KL |
| **`student_excess`** | **0.0657** | 扣掉噪声下限后学生自己的误差 |
| `ratio` | **3.88×** | 学生误差是教师自洽性的近 4 倍 |
| 教师类一致 / 学生类一致 | 0.882 / **0.698** | 同上 |

**结论：教师噪声约占学生 KL 的四分之一，其余约四分之三是学生自己的误差。**
先前"学生已到噪声下限"的说法依据的是不可比的两个数字，此处更正。

按遭遇分层后不稳定性集中在少数敌人（64 sims）：

| 遭遇 | 状态 | 动作类一致 | 两两 KL |
|---|---|---|---|
| GREMLIN_NOB | 3 | **0.500** | 0.228 |
| FAT_GREMLIN | 3 | 0.778 | **0.471** |
| ACID_SLIME_M | 3 | 0.611 | 0.004 |
| CULTIST / BLUE_SLAVER / FUNGI_BEAST / GREEN_LOUSE / ACID_SLIME_L | 各 3 | **1.000** | ≈0.00 |

**尚未做**：独立的动作价值审计（用另一批 belief samples + 固定 continuation policy 计算
`estimated_action_gap = E[U|teacher] − E[U|student]`）。本轮只报了标签稳定性，
没有证明"跟随教师"在效用上更好。这是最重要的未完成项。

---

## §5 重标实验（负结果）与决策

### 5.1 按诊断建议做的重标实验

`scripts/relabel.py` 把开发状态用 4 倍预算（256 sims）重标，**只换标签、不动 observation**，
逐步核对 observation hash（0 次重放失败）。两个学生用完全相同的配置训练，
唯一差别是训练标签的教师预算；两者都在**同一套 256-sim 验证标签**上评分：

| 学生训练标签 | 决策状态动作一致 | 动作类一致 | KL | 教师熵 |
|---|---|---|---|---|
| 64 sims | 0.5547 | 0.6275 | 0.1354 | 1.2774 |
| **256 sims** | 0.5304 | 0.6235 | **0.1290** | 1.2774 |

**重标没有解决问题**：KL 只降了 4.7%，动作一致率反而略降。
把教师预算提高 4 倍并没有把学生变好。

### 5.2 按判据表的决策

| 判据 | 本轮结果 | 后续动作 |
|---|---|---|
| 公开历史或动作信息确实丢失 | **是**，已修（§1） | 修编码器，保留 128 维，重做对照 |
| 原始 top-1 低但类一致高 | 部分是（0.607 vs 0.551） | 修指标（已做） |
| 教师重跑不稳定，提高预算能改善 | 64 sims 时不稳；**但重标实验无效**（§5.1） | **不采用**"重标即解决"的假设 |
| 小样本拟合失败 | **否**（KL 7.6e-06） | 不采更大数据集来掩盖 |
| 教师稳定、可拟合，但验证仍有明显容量证据 | **是**（教师类一致 0.882 / 学生 0.698，学生 KL 是噪声下限的 3.9×） | **下一步做 128 与 192 维的多训练种子对照** |
| 教师轨迹上好、学生自主轨迹上差 | 未测 | 需要学生自主轨迹实验 |

**结论**：误差既不是表达能力（能拟合），也不是教师噪声（只占约 1/4）。
剩下的是**泛化**问题 —— 模型在第 100 步就达到最优验证损失然后过拟合，
而数据只有 96 局 / 1331 个决策状态。下一轮的正当方向是
**128 vs 192 维、3 个训练种子的对照**，以及测试强正则／更多数据，
而不是继续调教师。

按任务书要求，这些都属于**下一轮**的对照实验；本轮到此停止，不把未做的对照写成结论。

### 5.3 关于正式 1000 场评测

任务书 §P6 要求"完成开发模型选择并冻结候选后"再做正式配对评测。
本轮开发选择**尚未完成**（结论是"还需要 128/192 对照"），
因此**没有生成也没有解封最终测试 manifest**，没有跑正式评测，也没有创建最终结果报告。
提前用掉 test 会让它变成开发集。

---

## §6 结局校准（独立于效用）

`scripts/calibration_report.py`。v0.1 的 sigmoid `value` 是**战斗效用**估计，
不是存活率，所以死亡概率取 11 类 outcome softmax 的第 0 类。

开发验证集（330 状态 / 24 场，死亡率 13.6%）：

| 指标 | 值 |
|---|---|
| 死亡 Brier | 0.0901 |
| 常数死亡率基线 Brier | 0.1178 |
| Brier skill（相对基线） | **0.235** |
| 死亡 NLL | 0.2849 |
| ECE（10 分箱） | 0.0925 |

**每场只取一个状态**（按战斗聚类，避免同局多步当独立样本）：

| 指标 | 值 |
|---|---|
| 战斗数 | 24 |
| 死亡 Brier | 0.0509 |
| 聚类 bootstrap 95% | **[0.0153, 0.1884]** |
| ECE | 0.0972 |

可靠性表显示低分箱（0–0.1，209 个状态）预测均值 0.062、实际死亡 0.000 ——
模型在低区间**高估**死亡。但 24 场战斗的区间很宽，这个结论本身不确定。

顺带澄清一个容易误读的数字：训练日志里 `policy_loss ≈ 1.07` 一度看起来**低于**教师熵 1.32，
仿佛违反 `CE ≥ H`。实际是分母不同：1.32 是**决策状态**的熵，而 1.07 覆盖**全部状态**，
其中 25% 是强制动作（H=0, CE=0）把均值拉低了。逐状态验证 `min(KL) = 0`，无负值。

**未做**：temperature scaling（按要求只能在独立校准集上拟合）。上表未做任何校准后处理。

---

## §7 仍然不确定的事

1. **跟随教师是否更好**没有被证明 —— 缺独立的动作价值审计（`estimated_action_gap`）。
2. 教师不稳定的**来源**未定位：是根采样方差（MCTS 固有），还是启发式 evaluator 的噪声？
   未做"用 1024-sim 教师当参考、看 64-sim 教师错在哪"的分析。
3. 强制动作占 25%，说明夹具仍有大量"没得选"的状态，对训练信号是稀释。
4. 字段覆盖表（§1.3）尚未机器可读化；token 碰撞未取证。
5. 全部结论都在**未认证模拟器**上；没有原游戏差分（G3 仍未执行）。

## 复现命令

```bash
.venv/bin/python scripts/freeze_baseline.py --output reports/baseline_freeze.json
.venv/bin/python -m stsai collect --backend lightspeed_pilot --output data/dev/train --count 96 --workers 3 --sample-actions --config configs/native_pilot.json
.venv/bin/python -m stsai collect --backend lightspeed_pilot --output data/dev/val --split val --count 24 --workers 3 --config configs/native_pilot.json
.venv/bin/python -m stsai train --train-data data/dev/train --val-data data/dev/val --output runs/dev_base2/model --device cuda --backend lightspeed_pilot --config configs/native_pilot.json
.venv/bin/python scripts/distill_diagnosis.py --checkpoint runs/dev_base2/model/best.pt --data data/dev/val --output reports/distill_diagnosis_val.json --per-state reports/distill_diagnosis_val_states.jsonl --device cuda
.venv/bin/python scripts/fit_probe.py --data data/dev/train --output reports/fit_probe.json --states 256 --updates 1500 --device cuda
.venv/bin/python scripts/teacher_stability.py --data data/dev/train --output reports/teacher_stability.json --states 64 --seeds 4 --budgets 64 256 1024
.venv/bin/python scripts/calibration_report.py --checkpoint runs/dev_base2/model/best.pt --data data/dev/val --output reports/calibration_val.json --device cuda
.venv/bin/python scripts/relabel.py --source data/dev/train --output data/dev/train_256 --budget 256 --workers 4
.venv/bin/python scripts/relabel.py --source data/dev/val   --output data/dev/val_256   --budget 256 --workers 4
.venv/bin/python -m stsai train --train-data data/dev/train_256 --val-data data/dev/val_256 --output runs/dev_relabel/model --device cuda --backend lightspeed_pilot --config configs/native_pilot.json
.venv/bin/python scripts/noise_floor.py --data data/dev/val_256 --checkpoint runs/dev_relabel/model/best.pt --output reports/noise_floor.json --states 24 --seeds 4 --budget 256 --device cuda
```

## 本轮新增/修改的脚本

| 脚本 | 用途 |
|---|---|
| `scripts/freeze_baseline.py` | 冻结基线（commit／engine／patch／版本／checkpoint SHA） |
| `scripts/distill_diagnosis.py` | 指标分解、分层、等价类 |
| `scripts/fit_probe.py` | 256 固定状态的最小可拟合实验 + 输入冲突检测 |
| `scripts/teacher_stability.py` | 教师重跑稳定性（重放根） |
| `scripts/noise_floor.py` | 噪声下限 vs 学生误差的受控分解 |
| `scripts/relabel.py` | 高预算重标（只换标签） |
| `scripts/calibration_report.py` | 死亡概率校准（与效用分开） |
| `scripts/profile_search.py` | S/P/V/PV 消融与成本分解 |
