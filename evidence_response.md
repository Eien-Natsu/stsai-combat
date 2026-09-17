# STSAI fb9bf6e 复核材料：逐项应答

**性质**：证据回包。本轮**没有**启动训练、**没有**新增数据、**没有**提高教师预算、**没有**动 P6、
**没有**修改 `reports/generalization_protocol.json` 或任何冻结协议。
凡本文给出的数字，都标注了它是「已保存产物的直接导出」还是「为对账而做的重新导出」。

**已保存 / 重新导出 / 未保存**三档在文末 `NOT_SAVED` 清单里汇总。

---

## 0 交付边界，以及准备材料时发现的两件事

### 0.0 边界

- 报告 commit：`fb9bf6e`。源码 bundle：`stsai-handoff-fb9bf6e.bundle`（本次附件内含，附 SHA256）。
- 本包另外新增的文件（本文、`INDEX.md`、`MANIFEST.sha256`、`review_weights/`、`reports/_review_*.txt`）
  是**在 fb9bf6e 之后的工作区新增**，不属于 fb9bf6e。它们已提交为 `stsai-review-evidence` 分支上的一个
  独立 commit（见 `INDEX.md` 的 commit 对照表），**没有改写任何既有产物**。
- 未提供：游戏本体/JAR、`.venv`、GPU 二进制、全部训练数据、优化器状态。

### 0.1 【新发现】训练损失里的广播错误——12 次矩阵是在错误的目标函数下训练的

复核要求「区分 policy KL 与辅助损失」，照做时发现 `src/stsai/training.py::losses()` 有一处**我上一轮引入的
广播错误**：

```python
elementwise = -(labels["policy"] * logits.log_softmax(-1)).sum(-1)   # 形状 (b,) 已对动作求和
decision    = labels["decision"]                                     # 形状 (b,)
policy      = (elementwise * decision.unsqueeze(-1)).sum() / decision.sum().clamp_min(1)
#              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ (b,) × (b,1) → (b,b) 外积
```

`(b,)` 乘 `(b,1)` 广播成 `(b,b)`，求和从 b 项变成 b×b 项。最小复现（`reports/_review_loss_bug_repro.txt`）：

| | 值 |
|---|---|
| 当前代码路径乘积形状 | **(16, 16)** |
| 应该是 | (16,) |
| 当前 policy 项 | 136.00 |
| 预期 policy 项 | 8.62 |
| **膨胀倍数** | **15.79** |

与实测一致：矩阵运行的验证 `policy_loss` = **16.90**，而改动前的 `dev_base2` 是 **1.07**。
`loss` 因此也是坏的（矩阵 `best_validation_loss` ≈ 18.3，改动前 2.22）。

**影响范围（逐项区分）**

| 量 | 是否受影响 | 说明 |
|---|---|---|
| `kl_dev` / `policy_kl` / `kl_over_decision_states` / 教师熵 / 一致率 | **不受影响** | 走的是另一条正确路径；这解释了为什么 KL 数值合理 |
| **checkpoint 选择** | **不受影响** | 冻结指标是 `kl_dev`，不是总 loss |
| **训练梯度** | **受影响** | policy 项被放大 ~16×，辅助头（outcome ×0.5、value ×1）相对被压制 |
| `generalization_matrix.csv` 里的 `loss` / `policy_loss` | **受影响，是坏值** | 引用时不要用这两列 |
| `best_validation_loss` / `best_selection_metric` 的第二项 | **受影响** | `best_selection_metric[0]`（kl_dev）有效 |
| 开发闭环、动作价值审计、Brier | 推理路径，**不受直接影响** | 但用的是这批模型，见下 |

**这解释了 Brier 回归**（D 节）：改动前的两个 checkpoint（`dev_base2`、`dev_relabel`）模型 Brier ≈ 0.089–0.090，
而全部 5 个检查过的矩阵 checkpoint 是 0.131–0.164：

| checkpoint | 模型 Brier | 对冻结基线差 |
|---|---|---|
| dev_base2（旧 loss，旧选择） | 0.0901430653 | −0.0397194426 |
| dev_relabel（旧 loss，256-sim 标签） | 0.0891486241 | −0.0407138837 |
| M128-R0-s17（新 loss，kl_dev 选择） | 0.1314604199 | +0.0015979121 |
| M128-R0-s29 | 0.1636936277 | +0.0338311199 |
| M128-R0-s43 | 0.1521442667 | +0.0222817588 |
| M192-R0-s43 | 0.1612164168 | +0.0313539089 |
| M192-R1-s43 | 0.1373665139 | +0.0075040061 |

两个候选机制**同时**存在、方向相同，仅凭已保存产物**无法完全分离**：
(a) 目标函数里 policy 权重被放大 16×，outcome 头被相对饿死；
(b) checkpoint 选择从「总 loss」改成「纯 policy 的 kl_dev」，选点时不再看 outcome 头。
一个弱证据支持 (a)：同一 run 内 `last.pt`（step 500）比 `best.pt`（step 225）更差
（0.1626 vs 0.1315），即训练继续时校准持续变坏，与 outcome 头欠训练一致。

**本轮不修、不重跑。** 理由是本次是证据交付：若现在改 `losses()`，工作区代码就不再是产出这批
冻结产物的代码，复核会更难做。修正是一行——去掉 `.unsqueeze(-1)`：

```python
policy = (elementwise * decision).sum() / decision.sum().clamp_min(1)
```

已加一个 tripwire 测试 `tests/test_training_loss.py::test_policy_term_is_mean_over_decision_states`，
标记 `xfail(strict=True)`：现在是「已知失败」，一旦有人修好它会立刻变成 XPASS 失败，防止静默修改。

**对既有结论的影响**：12 个 run 共享同一错误，所以**宽度与正则化的对比在内部仍然成立**
（两侧同病），但必须改述为「在这批**在错误目标下训练**的模型上，未观察到宽度或正则化收益」。
Brier 相关结论（D 节）则必须按 0.1 与 D 节重新解读。

### 0.2 【更正】公开意图映射：上一轮的「泄漏修复」过度删除

复核端引用旧 `native/bridge.cpp:227` 的 `intent = isAttacking() ? "ATTACK" : "BUFF"` —— 这个映射
**现在仍然只有两类**。据此逐项核对上一轮报告的「9 组歧义」（`reports/_review_A_ambiguity.txt`），
并用上游源码验证每个招式实际做了什么：

| 歧义组（旧口径） | 上游源码 | 真实游戏 Intent | 是否真的歧义 |
|---|---|---|---|
| JAW_WORM CHOMP vs THRASH | `MonsterSpecific.cpp:850` 只攻击；`:863` 攻击 **+ `MonsterGainBlock(idx,5)`** | ATTACK vs **ATTACK_DEFEND** | **否，是适配器丢的** |
| ACID_SLIME_M CORROSIVE_SPIT vs TACKLE | `:373` 攻击 **+ `MakeTempCardInDiscard(SLIMED)`**；`:386` 只攻击 | ATTACK_DEBUFF vs ATTACK | **否，是适配器丢的** |
| LAGAVULIN SLEEP vs SIPHON_SOUL | `:881` **`DebuffPlayer<DEXTERITY/STRENGTH>`**；`:888` 睡眠 | SLEEP vs **DEBUFF** | **否，是适配器丢的** |
| LOOTER ESCAPE vs SMOKE_BOMB | `:936` **`addBlock(6)`**；escape 单独一支 | ESCAPE vs **DEFEND** | **否，是适配器丢的** |

**结论：9 组全部是适配器把公开类别压成两类造成的，没有一组是"真实玩家不知道"。**
复核端的判断正确，我上一轮把「适配器不够细」误判成「引擎泄漏」。

频率（`data/dev/train`，按粗意图匹配）：

| 怪物 | 状态数 | 占训练状态 | 决策状态数 | 占决策状态 |
|---|---|---|---|---|
| JAW_WORM | 111 | 6.26% | 86 | 6.46% |
| LAGAVULIN | 128 | 7.22% | 95 | 7.14% |
| ACID_SLIME_M | 79 | 4.45% | 61 | 4.58% |
| LOOTER | 20 | 1.13% | 15 | 1.13% |
| **合计** | **338** | **19.05%** | **257** | **19.31%** |

**即约 19% 的训练决策状态落在学生看不见、而真实玩家看得见的公开信息上。**
学生因此**比真实玩家更瞎**，而教师搜索的 rollout 内部用的是真实 move_id，**教师相对学生是特权的**。
这是「学生像不像教师」这一目标的一个真实错配来源。

**正确修法（下一轮，不在本轮实现）**：不是把内部 `move_id` 全开，也不是继续删——
而是从招式的**效果结构**派生一个与游戏 `Intent` 枚举同粒度的公开类别
（ATTACK / ATTACK_DEFEND / ATTACK_DEBUFF / DEBUFF / DEFEND / BUFF / SLEEP / ESCAPE），
只导出这个类别；只有在**该细化类别仍然歧义**时才隐藏计划招式。
本轮给出的是判定标准与已验证的四组效果证据，未实现派生逻辑。

---

## A 公开意图、历史记忆与 sampler

### A.1 当前映射与版本

| 项 | 当前值 | 位置 |
|---|---|---|
| 意图映射 | `isAttacking() ? "ATTACK" : "BUFF"` —— **仍只有两类** | `native/bridge.cpp::observe()` |
| 观察 schema | `SCHEMA_VERSION = 2` | `src/stsai/util.py` |
| 编码器 | `ENCODING_REVISION = 2`，**不读取任何招式身份** | `src/stsai/encoding.py` |
| 计划招式 | **不导出** | 同上（上一轮的删除） |
| 已执行招式 | `previous_move`（名称），由适配器自己按回合跟踪 | `bridge.cpp:194-199, 233-241` |

编码器对敌人当前用的信息：`intent`、`intent_damage`、`hits`、HP/格挡/力量/虚弱/易伤/artifact/half_dead，
以及 `ENEMY_INTENT_<slot>_<intent>` 与 `ENEMY_PREV_<slot>_<previous_move>` 两个 token。
**它不读 `previous_move` 以外的任何历史**，也不读任何引擎内部字段。

### A.2 sampler 生命周期时间线（带源码位置）

```text
① 玩家决策根
   PilotBattle::observe()            bridge.cpp:184-241
     · bc.monsters.arr[i].moveHistory[0] 在此被读到，但只用于适配器自己的
       「上一回合实际观察到的招式」跟踪（:194-199），不进入 observation
② 复制
   PilotBattle::sample(seed)          bridge.cpp:291
     · auto result = std::make_unique<PilotBattle>(*this)  → 整个 BattleContext 深拷贝
③ 重采样（**只换未来随机流**）
   :297-299   aiRng / cardRandomRng / miscRng / monsterHpRng / potionRng / shuffleRng
              全部用 sampler_seed 重新构造
   :303-307   抽牌堆先按跨后端规范键排序，再用同一 rng 洗牌
     · bc.seed=0，仅调试字段
     · **没有**重采样：monsters[].moveHistory[0]、miscInfo、monsterData、
       uniquePower0/1、玩家牌区与状态、cards 队列
④ 当前计划被使用
   Monster::takeTurn()                MonsterSpecific.cpp:335+
     · 该回合执行的是 moveHistory[0]；rollMove 在**本回合动作之后**才被调用
⑤ 下次 rollMove
   Monster::rollMove()                Monster.cpp:629-635
     · const auto move = getMoveForRoll(bc, miscInfoCopy, bc.aiRng.random(99))
     · getMoveForRoll 在这里读 moveHistory[0] / [1]（经 lastMove/lastMoveBefore/
       lastTwoMoves，Monster.cpp:613-627）
     · **此刻 moveHistory[0] 仍是刚刚执行过的那个招式**——计划尚未移位
⑥ setMove
   Monster::setMove()                 Monster.cpp:638-641
     · moveHistory[1] = moveHistory[0]; moveHistory[0] = moveId
     · 移位发生在 ⑤ **之后**
```

**这张时间线回答「当前计划是否在重采样前影响了 rollout」**：

- 复制的 `moveHistory[0]` 在 ② 被保留，但在 ⑤ 被读取时它已经是**刚执行过**的招式；
  真正的新计划由 ⑥ 写入，而它的分布由 ⑤ 基于①—④的公开历史 + 重置后的 `aiRng` 决定。
- 因此 **`aiRng` 被重置**消除了未来随机流对真实隐藏值的依赖；
  `moveHistory[0]` 的残留**只以"刚执行过的招式"身份被读取**，而那是公开的（见 A.3）。
- **仍然属于特权的部分**：第 ⑤ 步 `lastMove(...)` 读到的"刚执行过的招式"如果是
  A.1 里那 19% 的歧义对之一，**引擎用的是真实身份**，玩家只能用更粗的类别。
  这不是 sampler 的 bug，而是**公开意图映射太粗**（§0.2）导致的信息不对等。

### A.3 其他 latent 字段与缓存

| 字段 | 在哪一步被读 | 处理 | 判定 |
|---|---|---|---|
| `moveHistory[0]`（计划） | ⑤ 被读、⑥ 被写 | ② 保留、③ 不重采样 | **公开性取决于意图映射**；细粒度意图下即为公开 |
| `moveHistory[1]` | ⑤ 经 `lastMoveBefore` | 同上 | 上一回合已执行 → 公开 |
| `miscInfo` | ② 复制、⑤ 作 `monsterData` 传入 | 不重采样 | 支撑怪物：GREMLIN_WIZARD（充能）、RED_SLAVER（usedEntangle）—— 两者可见状态都由意图/状态栏公开。读 `miscInfo` 的其他怪物（Champ/Spiker/Writhing Mass/Time Eater/Awakened One/Book of Stabbing）**不在本轮 17 遭遇内** |
| `monsterData` | 同上 | 同上 | 同上 |
| 各 RNG | ③ 全部重置 | 重采样 | 未来随机流不依赖真实值 |
| 抽牌堆顺序 | ③ 规范化后洗牌 | 重采样 | 不依赖真实顺序 |
| 搜索缓存 | 无 | — | `BeliefSearch` 只吃 observation 与 sampler，未缓存引擎字段 |

### A.4 N0 审计脚本、覆盖说明与碰撞键定义

- 脚本：`scripts/native_replay.py`（10⁴ 局随机回放）、`tests/test_native_fairness.py`（变形测试）。
- 碰撞键：`stsai.contracts.observation_key` = `sha256(canonical(obs))`，其中
  `canonical` 是 `json.dumps(sort_keys=True, separators=(",",":"))`；
  **排除的键**：`backend`、`schema_version`。
- **是否混入 episode_id / seed / 实例 ID**：`observation_key` 的输入是 observation 本身。
  observation 里**没有** episode_id、seed、uniqueId、原始指针；
  `FORBIDDEN` 名单（`contracts.py`）在每次校验时拦截 `seed/rng/uuid/unique_id/draw_order/...`。
  所以碰撞键**不含**实例身份。**但**它含 `turn`、牌区、HP 等公开量，因此碰撞是
  「公开状态完全相同」的**充分不必要**条件——两个信息状态相同但公开表现不同的状态不会被它合并。
- 覆盖：扫描全部 **2104** 个已存状态（dev train+val），跨局碰撞 **0**，
  局内重复公开状态也是 **0**。**这只说明该经验检验找不到可比较的状态对，不是安全性证明。**

### A.5 N0「通过」究竟通过了哪几部分（逐项）

| 检查 | 状态 | 依据 |
|---|---|---|
| 观察里不再有隐藏字段 | **通过** | `validate_public` + 7 项 forbidden 名单测试 |
| 计划招式不再导出 | **通过** | `test_planned_move_is_never_exported` |
| 已执行招式语义正确（不是 roll 历史） | **通过** | Cultist 追踪 + `test_previous_move_only_ever_reports_an_executed_move` |
| 采样不依赖真实抽牌顺序 / RNG | **通过** | `test_same_public_history_different_hidden_draw_order_samples_identically` 等 4 项 |
| **采样不依赖真实计划招式** | **未证明** | 无法构造状态对；A.2 的时间线是**代码论证**，不是经验检验 |
| **公开意图粒度与游戏一致** | **未通过** | §0.2：粗两类，19.3% 决策状态受影响 |
| 教师标签未复用泄漏版本 | **通过** | 全部数据在 schema 2 下重采；旧数据因 schema 升级被 `encode()` 拒绝 |

**残余假设（记录在案，未验证）**：已执行招式可由其可见后果事后识别。
若两个招式可见后果完全相同，该招式不可公开识别，本审计不会发现。
§0.2 的细粒度意图修法同时会削弱这个假设的必要性。

---

## B 学生是否已经优于启发式

### B.1 逐种子的配对效用差与胜负交叉（`reports/_review_B_section.txt`）

区间**只对场景重采样**，**条件于当前已训练的这几个 checkpoint**，不重采样训练种子。
配对单位 = 场景（同一 `episode_index` 同初始条件），256 对全部完整，**0 丢弃**。

| 比较 | 均值 | 95% 区间 | A>B | B>A | 平手 |
|---|---|---|---|---|---|
| M128-R0-**s17** − heuristic | +0.02248 | [−0.00247, +0.04793] | 63 | 85 | 108 |
| M128-R0-**s29** − heuristic | +0.02239 | [−0.00061, +0.04730] | 56 | 76 | 124 |
| M128-R0-**s43** − heuristic | +0.02232 | [−0.00411, +0.04926] | 66 | 84 | 106 |
| M192-R1-**s17** − heuristic | +0.01705 | [−0.00512, +0.04030] | 57 | 90 | 109 |
| M192-R1-**s29** − heuristic | +0.02504 | [−0.00211, +0.05281] | 59 | 94 | 103 |
| M192-R1-**s43** − heuristic | **+0.02623** | **[+0.00214, +0.05219]** | 57 | 87 | 112 |
| **search − heuristic** | **+0.06049** | **[+0.03534, +0.08981]** | 78 | 23 | 155 |
| search − M128-R0-s17 | **+0.03801** | **[+0.01833, +0.06136]** | 116 | 41 | 99 |
| search − M128-R0-s29 | +0.03810 | [+0.02046, +0.05874] | 111 | 37 | 108 |
| search − M128-R0-s43 | +0.03816 | [+0.01987, +0.05962] | 112 | 39 | 105 |
| M192-R1-s43 − M128-R0-s17 | +0.00375 | [−0.01492, +0.02349] | 44 | 41 | 171 |

**重要细节（复核要求）**：单个模型相对启发式，**效用均值更高，但正面赢下的场次更少**
（例如 s17：63 胜 vs 85 负）。即模型赢的时候赢得多（存活 HP 高），输的时候输得少。
平手 99–171 场（utility 完全相等，多为双方同 HP 获胜）。
这是「均值高 ≠ 逐场更强的多数」的实例，必须与均值一起读。

**结论**：`model − heuristic` 12 个里 11 个区间跨 0，只有 **M192-R1-s43** 排除 0；
`search` 相对启发式与学生都**稳定**排除 0。**不能称学生已确立优于启发式。**

### B.2 区间口径与配对方式

- 只重采样**场景**（episode），条件于当前已训练模型。**没有**同时重采样训练种子与场景。
- 3 个训练种子 × 256 场景 **不是** 768 个独立场景；2 正则档 × 3 种子 **不是** 6 个独立种子。
  B.1 表里每一行都是**单个 checkpoint 对启发式**，逐种子列出，**没有**把三种子平均写成
  「某个单模型 236/256」。
- 先前报告把 `M128-R0` 写成「236 胜（3 seed 均值）」是**口径混用**，此处更正：
  三种子的胜场分别是 236 / 236 / 236，但那仍是三个不同模型各自的数，不是同一个模型的样本量。
- **种子数只有 3**，跨种子的 sd 尾部估计很脆（Agarwal et al., 2021 的告诫）。

### B.3 两种对比不是一回事

- **宽度主效应**：192 − 128，在**同正则**下配对，6 对（2 正则 × 3 种子），均值 +0.01254（kl_dev）。
- **`M192-R1 − M128-R0`**：这是**跨两种因素的差**，既含宽度也含正则，不是宽度主效应。
  它的效用差 +0.00375 [−0.01492, +0.02349]，与宽度主效应不是同一个量。
- **预先指定 vs 事后**：预先指定的是「4 配置 × 3 种子全部执行、按 kl_dev 选点」；
  **宽度×正则化交互是事后观察到的**（6/6 种子符号一致，但两侧区间均含 0），
  只能标为**探索性提示**。

### B.4 12 个 run 的 KL 与效用对应（`reports/_review_B2_section.txt`）

| cell | kl_dev | kl(decision) | policy_kl | utility | wins | best_step |
|---|---|---|---|---|---|---|
| M128-R0-s17 | 0.11309 | 0.10538 | 0.07887 | 0.82980 | 236 | 225 |
| M128-R0-s29 | 0.12100 | 0.12034 | 0.09007 | 0.82972 | 236 | 400 |
| M128-R0-s43 | 0.11881 | 0.11409 | 0.08539 | 0.82965 | 236 | 400 |
| M128-R1-s17 | 0.11243 | 0.10445 | 0.07818 | 0.82644 | 235 | 225 |
| M128-R1-s29 | 0.11698 | 0.11451 | 0.08571 | 0.82240 | 234 | 400 |
| M128-R1-s43 | 0.11231 | 0.11052 | 0.08272 | 0.82041 | 233 | 400 |
| M192-R0-s17 | 0.13287 | 0.11963 | 0.08954 | 0.82142 | 234 | 225 |
| M192-R0-s29 | 0.11889 | 0.10980 | 0.08218 | 0.82054 | 233 | 375 |
| M192-R0-s43 | 0.12869 | 0.11438 | 0.08561 | 0.82754 | 235 | 375 |
| M192-R1-s17 | 0.13919 | 0.11795 | 0.08829 | 0.82437 | 235 | 225 |
| M192-R1-s29 | 0.12418 | 0.11596 | 0.08680 | 0.83236 | 237 | 225 |
| M192-R1-s43 | 0.12605 | 0.11446 | 0.08567 | 0.83355 | 237 | 225 |

**Spearman ρ(kl_dev, utility) = +0.182，n=12；12 个里只有 2 个排名完全一致。**
复核端要求「一个排序反转不足以证明普遍脱钩」——同意。正确表述是：
**在这 12 个 run 上未观察到 KL 与效用的可靠关联**（ρ 近零，n 很小），
不能说二者普遍无关，也不能用 KL 代替效用做配置选择。

### B.5 训练数据覆盖（不拿开发集规模替代）

| 项 | 值 |
|---|---|
| 独立局数 | 96（starter/swarm/elite/mixed 各 24） |
| 原始状态 | 1774 |
| 决策状态 | 1331（75.0%） |
| 被迫状态 | 443（25.0%） |
| 唯一 `(episode,turn,hp,energy)` 键 | 1747（98.5% of 原始状态） |
| 起始牌组大小 | min 13 / median 14 / max 16 |
| 玩家 HP 分布（状态级） | min 1 / p25 34 / median 48 / p75 58 / max 80 |

遭遇分层（状态数，**明显不均衡**）：
LAGAVULIN 323、SENTRY 280、CULTIST 184、JAW_WORM 160、BLUE_SLAVER 141、SPIKE_SLIME_S 98、
GREMLIN_NOB 84、FUNGI_BEAST 81、ACID_SLIME_S 65、FAT_GREMLIN 64、SPIKE_SLIME_M 64、ACID_SLIME_M 40、
GREEN_LOUSE 38、SNEAKY_GREMLIN 35、ACID_SLIME_L 22、RED_LOUSE 21、SPIKE_SLIME_L 20、RED_SLAVER 18、
MAD_GREMLIN 13、LOOTER 12、GREMLIN_WIZARD 11。

**GREMLIN_WIZARD / LOOTER / MAD_GREMLIN / RED_SLAVER 每类只有 11–18 个状态**，
覆盖率严重不足。「当前不做更多数据实验」**是暂停，不是证伪**：以上覆盖数据恰恰说明
更多数据尚未被检验过。

---

## C 动作价值差的符号、样本来源与精度

### C.1 符号定义

```text
delta(root) = E[U | teacher_action, continuation] - E[U | student_action, continuation]
```

**是 teacher 减 student**（正值 = 教师动作在该 continuation 下更好）。
脚本里写作 `delta = values["teacher"] - values["student"]`（`scripts/action_gap_audit.py`）。

### C.2 权重与算术

- 是否等权：**每根等权**。
- 47 个一致根：**恰记 0.0**（校验过：一致集合的 delta 取值集合为 `{0.0}`）。
- 是否每场最多一根：**是**。根规则 = 每局第一个决策状态，一局一根；
  64 个根对应 **64 个不同 episode**（已核）。
- 是否同一 checkpoint：学生动作与 continuation **同一个** checkpoint
  （`runs/matrix/M128-R0-s17/model/best.pt`）。教师动作来自 64-sim `BeliefSearch`。

| 量 | 值 |
|---|---|
| 全部 64 根均值 | **−0.0098071289** |
| 17 个分歧根条件均值 | **−0.0369209559** |
| 恒等核验 | 47×0 + 17×(−0.036921) = −0.6277 ; /64 = **−0.009807** ✓ |

与复核端的条件算术 **−0.0369317647** 一致（差 1.1e-5，来自我这边 64 根均值本身也是
逐根均值再平均，与「直接除」的浮点顺序不同）。

### C.3 分歧根内部分布（符号是混合的）

| | 值 |
|---|---|
| 分歧根数 | 17 |
| delta > 0（教师更好） | **7** |
| delta < 0（学生更好） | **8** |
| delta = 0 | 2 |
| min / max | −0.44762 / +0.01832 |
| 根内 MC 标准误 | median **0.002968**，mean 0.012628，max 0.062309 |

**均值 −0.0369 主要来自少数几个大负值**（min −0.448），不是普遍方向。
7 正 8 负说明**方向本身在根之间是混合的**。

### C.4 独立审计样本与原搜索随机流的关系

- 分支样本种子：`seed_for("audit-sample", episode_index, label, sample)`
  （`stsai.util.seed_for` = `sha256(canonical(parts))[:15]` 转 int，**跨进程稳定**，不是 Python `hash()`）。
  每条分支 64 个样本，两条分支用**相同的 sample 索引**（共享外生样本以控方差），
  每个样本 `env.sampler()(seed)` 从**同一公开根**重新取 belief。
- 与原 MCTS 随机流的关系：**完全独立**。审计不复用 `BeliefSearch` 内部的 `aiRng`，
  也不读它的 Q；教师动作只用它选出的**动作编号**，其价值由重新采样的分支估计。
- 合法初始 belief：两条分支都从同一 `sim.observe()` 出发，先执行一次指定动作，
  再按冻结 continuation 走到底。**没有**把真实未来结果塞给分支。
- continuation：`runs/matrix/M128-R0-s17/model/best.pt`（固定，未网格搜索）。
- 截断处理：分支未终局则不计 utility，**记为 truncated**（本批两条分支**共 0 条截断**），
  不静默丢弃。
- 根内 MC 误差：见 C.3 的 `mc_se`（按两条分支独立方差和的开方）。
- 跨根不确定性：对 17 个分歧根（或 64 个全根）做 percentile bootstrap 重采样**根**，区间见报告。

**范围限制（必须保留）**：这只是**固定 continuation 下的局部动作效果**，
**不能**据此否定整场 `search` 策略的收益——B.1 里 `search − heuristic` 是 +0.0605
且区间排除 0，与本节的局部动作差是不同的问题。
另外 continuation 本身是**学生模型**，会偏向学生风格的动作，这一点无法从本批数据中消除。

---

## D Brier 数值桥接——逐项对账

### D.1 复核端的条件算术是对的

复核端在「同一 checkpoint、同一标签、同一加权、只换常数」条件下的推算：

```text
new_baseline = 0.1177685950 + (0.24634 - 0.1363636364)^2 = 0.1298633956
model - new_baseline = -0.0397203303
```

我用**旧 checkpoint（dev_base2）**重算，得到 **−0.0397194426**，与复核端一致。
（差异 8.9e-7 全部来自常数取整：复核端用 0.24634，我用从训练分片读出的精确值 0.2463359639。
 把 0.24634 代回即得 0.1298633956。**这条桥是精确的。**）

### D.2 为什么报告里是 +0.0367：三个量同时变了

| 变化 | 从 | 到 | 对「model − baseline」的影响 |
|---|---|---|---|
| **① checkpoint** | dev_base2 | M128-R0-s17 | 模型 Brier 0.0901430653 → 0.1314604199（**+0.0413，变差**） |
| **② 常数** | q_eval = 0.1363636364 | q_frozen = 0.2463359639 | 基线 Brier 0.1177685950 → 0.1298625079（**+0.0121，基线变差**） |
| **③ 加权口径** | 状态加权 | 每局内平均再按局平均 | +0.0016 → **+0.0367** |

**2×2 全表（同一模型预测 / 同一标签 / 同一 330 行 24 局）**：

| checkpoint | 模型 Brier | 基线 @q_eval | 差 | 基线 @q_frozen | 差 |
|---|---|---|---|---|---|
| dev_base2（旧报告用） | 0.0901430653 | 0.1177685950 | **−0.0276255297** | 0.1298625079 | **−0.0397194426** |
| M128-R0-s17（本轮用） | 0.1314604199 | 0.1177685950 | +0.0136918249 | 0.1298625079 | **+0.0015979121** |

所以：
- 复核端推出的 −0.03972 **确实存在**，它是「旧模型 + 冻结常数」的数；
- 本轮的 **+0.0367 既不是那个数、也不是同口径下的状态加权数（+0.0016），而是"每局内平均再按局平均"**；
- 三个变化里**贡献最大的是 ① checkpoint 更换**（模型 Brier 变差 0.041），
  其次是 ③ 加权口径（0.035），② 常数只有 0.012（且方向相反）。

**摘要里把 +0.0367 当作「换了常数基线」的结果是不准确的**，此处更正：
常数替换单独造成的效果是 **−0.0121（模型相对更有利）**，不是 +0.0367。

### D.3 为什么模型 Brier 变差——见 §0.1

不是脚本错误，是**训练目标里的广播 bug** 加上**选点不再看 outcome 头**。
两张表（§0.1）显示这是**系统性的**：全部矩阵 checkpoint 都在 0.131–0.164，
而两个旧 checkpoint 都是 0.089–0.090。

### D.4 逐行可对账的数据

`reports/_tool_brier_input.json`（送入 `tools/diagnostic_stats.py paired-brier` 的原始行）：

每行字段：`cluster_id`（= `episode_id`）、`sample_id`、`y`（0/1 死亡）、`p_model`、`p_baseline`。
外加 `baseline_provenance` 字符串与 `design` 标签。

| 复核端要求 | 本包提供 |
|---|---|
| row_id | `sample_id`（`s<行号>`，330 行唯一） |
| episode_id | `cluster_id`（24 个） |
| checkpoint_sha256 | `reports/_review_D_bridge.json` 的 `table[*].sha` |
| p_model | `p_model`（第 0 类 = 死亡） |
| y | `y` |
| baseline_p | `p_baseline`（冻结常数 0.2463359639） |
| 样本筛选/权重 | 无筛选、**等权**；局部-全局口径见 D.2 |
| 结局产生策略 | 教师轨迹（`stsai collect`，sampler 见 A.2） |
| 是否截断 | 本批 330 行**全部 completed**（`value_mask=1`），无截断 |
| 各口径下模型与基线各自分数 | `reports/brier_paired_difference.json` 的 `components` + `estimands` |
| 常数来源/冻结时刻 | `data/dev/train`（96 局）算术死亡率，在本轮评估前固化于 `scripts/brier_paired.py` 的 `--baseline-data`；无事后调整 |

**旧 `calibration_report.py` 的口径不一致——复核端指出的是事实，已确认**：
`one_state_per_battle` 的点估计用 `death_p[idx]`（每局首状态），
但 `brier_clustered_bootstrap95` 传的是 `(death_p - death_y)**2`（**全部状态**）与 `groups`。
**点估计与区间是两个不同估计对象。**
本轮新的 `scripts/brier_paired.py` **已统一**：`per_battle_first` 与 `per_battle_mean` 各自
点估计与 bootstrap 用同一组值。旧脚本**本轮未改**（避免与已发布报告不一致），
标记为已知问题，下一轮修。

---

## E 数据清洁性与 KL 分解范围

### E.1 教师/训练轨迹、标签、初始化、信息版本对应关系

| 产物 | 生成时机 | 标签来源 | 初始化 | 信息版本 |
|---|---|---|---|---|
| `data/dev/train`（96 局） | schema 2 之后 | 同一适配器构建的 64-sim 教师 | — | schema 2 / encoding 2 / scenario 3 |
| `data/dev/val`（24 局） | 同上 | 同上 | — | 同上 |
| `data/dev/train_256`、`val_256` | 之后 | **重标**（只换标签，observation 逐字节复制） | — | 同上 + `relabel.budget=256` |
| `runs/matrix/*`（12 个） | 之后 | 用 `data/dev/train` | **全部随机初始化**（`torch.manual_seed(init_seed)`） | 同上 |
| `runs/dev_base2`、`dev_relabel`（诊断用） | 更早 | 各自数据 | 随机 | **schema 2 / encoding 2**，但 loss 为改动前版本 |

**「观察字段删除后是否仍复用旧教师标签」**：**没有**。
上一轮的 schema 升级（1→2）使 v0.1 时期的全部 observation 无法通过 `validate_public`，
`encode()` 直接拒绝；那批数据与 checkpoint 已作废，本轮所有轨迹是**重采**的，
不是「删掉 JSON 字段后复用旧标签」。`load_checkpoint` 也会**拒绝**编码语义不同的 checkpoint
（实测旧 checkpoint 报 `encoding_revision=1 but this build uses 2`）。

**但必须补一句**：`data/dev/train_256` 是**在已有 observation 上重标**的
（`scripts/relabel.py` 逐步核对 observation hash，0 次重放失败），
所以它的输入分布与 `data/dev/train` 相同、只有标签不同。这是**有意的对照**，不是清洁数据。

### E.2 KL 原始分布的可核查性

`reports/_tool_kl_input.json`：24 个状态，每个含

- `action_keys`：**共享的动作顺序**（每状态的动作 ID 串，唯一、非空，长度 = 分布长度）
- `teacher_policies`：**4 个** 64-sim…（实为 256-sim）教师分布
- `student_policy`：学生分布
- `score_space`: `"action_id"`（**不是**等价类）
- 归一化：**显式断言**后除以和（`abs(sum-1) < 1e-6` 否则中止），
  工具端也拒绝静默重归一化（一开始就是它报 `student must sum to 1` 才暴露出 float32 求和误差）
- 方向：全部 `KL(teacher ‖ student)`，无 JS、无反向

工具输出 `reports/tool_kl_identity.json`：`identity_residual` 最大 **1.11e-16**，
`is_population_noise_floor: **False**`。

### E.3 关于 10% / 90%

**只是本批 24 个状态的**有限样本经验分解，**不是**「90% 的错误都由泛化造成」的总体因果归因。
`teacher_count = 4`，两项都只是 K=4 的估计。工具自身的 `notes` 也写了
「Empirical decomposition, not a population noise-floor estimate」。
正确的读法是：在这批状态上，学生相对**经验均值教师**的 KL 远大于教师围绕自身均值的离散，
因此**提高教师预算不是首要方向**。

---

## NOT_SAVED 清单

| 项 | 状态 | 说明 |
|---|---|---|
| 动作审计的**逐样本回报** | **NOT_SAVED** | `action_gap_audit.jsonl` 只保存每根的 `teacher_value` / `student_value` / `delta` / `mc_se` 与样本**计数**，未保存 64×2 个逐样本 utility。种子推导已给出（C.4），但**没有**为补这个重跑。 |
| 逐 step 的 `decision_fraction` | **NOT_SAVED** | `losses()` 返回过，但未写入 metrics.jsonl |
| 每个 run 的**全部** checkpoint | **NOT_SAVED**（只存 best/last） | `save_every=25` 覆盖写 `last.pt`，中间点不存在 |
| 中间步的 outcome 校准曲线 | **NOT_SAVED** | 只有 best/last 两个点 |
| `dev_base2` 的 optimizer/RNG 状态在推理权重里 | 已剥离 | 见 `review_weights/README` |
| 旧 `calibration_report.py` 的修正版 | **未修** | 已知口径不一致，本轮只记录 |
| 细粒度 intent 派生实现 | **未实现** | §0.2 只给判定标准与效果证据 |
| `losses()` 的修复 | **未应用** | §0.1，为保持工作区与冻结产物一致 |

---

## 附件索引

见同包 `INDEX.md`（文件→用途→命令）与 `MANIFEST.sha256`（逐文件校验）。
