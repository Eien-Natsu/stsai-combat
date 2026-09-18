# 目标机状态（RTX 5070 · 实际执行记录）

本文件记录在目标机上的**实际执行**。原始日志在 `logs/`，结构化产物在 `runs/`、`reports/`。
未执行的项明确写“未执行”，skip 不计入通过。

平台：Debian 12 (bookworm) / WSL2，12 逻辑核，15 GB RAM，893 GB 可用磁盘。
代码基线：交付包 `STSAI_Combat_5070_v0.1.zip`（commit `e2e58d6`）。

## 关卡总览

| 关卡 | 状态 | 依据 |
|---|---|---|
| G0 工程闭环 | **通过（本机）** | 195 passed, 0 failed, **0 skipped**（含 native 公平性与覆盖测试） |
| G1 5070 GPU | **通过** | `runs/doctor.json`：`cuda_verified=true`，真实前向+反向，BF16 |
| G2 native pilot | **工程部分通过** | 编译、189 项测试实跑、1000 局随机回放 0 异常；**原版差分未做** |
| G3 原版一致性 | **未执行（本机无合法原版游戏）** | 见"阻碍 1" |
| G4 强度进步 | **未达成** | 搜索/混合搜索显著优于启发式；纯网络仍与启发式无法区分；蒸馏瓶颈定位为泛化 |
| G5 完整战斗覆盖 | **部分** | 23 张卡 / 17 个遭遇 / 无药水 / 仅 Burning Blood |

---

## 环境与依赖

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 5070，`compute_capability=[12,0]`（sm_120），12,227 MiB |
| 驱动 | 591.86（未改动、未升级） |
| Python | 3.12.14（项目本地 python-build-standalone） |
| PyTorch | 2.9.1+cu128，`torch.version.cuda=12.8`，arch 列表含 `sm_120` |
| BF16 | 支持；训练 `run.json` 记录 `amp_bfloat16: true` |
| CUDA 自检 | 实际 `CombatNet` 前向 + `loss.backward()`，梯度全部有限 |
| 锁文件 | `requirements/target-resolved.txt` |

### 环境修复（交付机的两个真实阻塞）

1. **没有 `python3-dev`**：`Python.h` 缺失，CMake 报
   `Could NOT find Python (missing: Python_INCLUDE_DIRS Development.Module)`，pybind11 无法编译。
   AGENTS.md 规定系统包需授权，故**未安装任何系统包**：新增
   `scripts/setup_python_local.sh`，用 uv 在项目内 `.python/` 装官方
   python-build-standalone 解释器（自带头文件）；`setup_linux.sh` 检测不到 `Python.h`
   时自动切换。
2. **没有 `cmake`**：apt 源中不存在该包，而 `build_native.py` 直接调用 `cmake`。
   已加入 `requirements/dev.txt`（实装 4.4.3）。

---

## G2 · 原版候选编译与运行

上游锁定（`engine_lock.json`）：

- `gamerpuppy/sts_lightspeed`，revision `7476a81954020087da31d41d16fddf475746ec2d`
- `json` 子模块 `0b345b20c888f7dc8888485768e4bf9a6be29de0`
- 上游 `LICENSE.md` sha256 `accfd224...`

**交付包声明"尚未编译，不宣称可直接通过"。实机结果：`native/bridge.cpp` 未改一行即编译链接成功**，
唯一需要的改动是环境（Python 头文件、cmake），不是 C++ API。

```bash
python scripts/fetch_engine.py                       # 锁定 SHA + 应用补丁序列
python scripts/build_native.py --jobs 8              # 编译 → import → native pytest
python scripts/build_native.py --jobs 8 --sanitize   # UBSan
python scripts/native_replay.py --episodes 1000 --workers 6 --output runs/native_replay_1000.json
```

| 项 | 结果 |
|---|---|
| 编译 | 成功（`src/stsai/_lightspeed.cpython-312-x86_64-linux-gnu.so`） |
| pytest 全量 | **189 passed, 0 skipped**（`tests/test_native.py` 15 + `tests/test_native_coverage.py` 103 + 其余） |
| UBSan | 构建+测试通过，`-fsanitize=undefined -fno-sanitize-recover=all`，无 UB 报告 |
| 随机回放 1000 局 | **0 非法动作被接受、0 崩溃、0 UB 标记、0 采样破坏公开根、0 超预算**（16,413 步，13 种遭遇） |
| 状态转移吞吐 | 8,260 transitions/s（单进程，含 observe 与重置） |
| 搜索吞吐 | 64 模拟 ≈ 0.10–0.14 s/步（单进程） |

### 发现并修复的两个上游规则错误

模拟器是搜索教师，规则错误会污染它生成的每一条轨迹。两处都用补丁序列落地：

**1. Disarm+ 只减 2 点力量（应减 3）**
`BattleContext.cpp` 的 `CardId::DISARM` 分支硬编码 `-2`，**完全没有使用 `up`**，
升级后行为与未升级完全相同。wiki 与卡面均写明升级后为 3。
→ `native/patches/0001-disarm-upgrade-strength.patch`

**2. A18+ 的 Gremlin Nob 永远不用 Skull Bash**
`MonsterSpecific.cpp` 的 `asc18` 分支条件是 `lastTwoMoves(SKULL_BASH)`，
而 `lastTwoMoves` 要求最近两回合**都是**该招式 —— 在第一次返回 Skull Bash 之前
恒为假，于是永远走 `return RUSH`，第二个分支是死代码。A20 正是我们 pilot 的难度。
wiki 记载 A18+ 为固定循环：Bellow → Skull Bash → Rush → Rush → 重复。
→ `native/patches/0002-gremlin-nob-asc18-pattern.patch`

补丁不直接改工作区，而是记录在案：
`build_native.py` 在编译前要求工作区**恰好等于「锁定 revision + 声明的补丁」**，
`build_info()` 输出 `revision` 与补丁 hash，测试断言二者与 lock 一致 ——
**构建结果不会把打过补丁的树谎报成未改动的上游**。

### 覆盖范围

- **卡牌 23 张**：21 张白名单 + 敌人注入的 2 张状态牌（Slimed 可打出并消耗，Dazed 不可打出且虚无）。
  每张卡 base 与升级形态都断言了已知数值（伤害/格挡/抽牌/易伤/虚弱/力量/金属化/消耗/虚无/X 费/0 费），
  以及"打出后不进牌堆也不消失"的牌堆数量不变量。
- **遭遇 17 个**：Cultist、Jaw Worm、两组 Louse、Blue/Red Slaver、Exordium Thugs、Exordium Wildlife、
  Two Fungi Beasts、Looter、Gremlin Gang、三组 Slime、Large Slime、以及三个 Act 1 精英
  （Gremlin Nob、Lagavulin、Three Sentries）。
- **敌人可见行为分支**：9 个固定阵容遭遇（Cultist、Jaw Worm、Blue/Red Slaver、Fungi Beast、Looter、
  Nob、Lagavulin、Sentry）**逐招全覆盖**并断言；随机池遭遇（Louse/Slime/Gremlin/Thugs/Wildlife）
  断言招式与阵容不越出声明集合。
- **怪物 power 通用导出**：不再只导 RITUAL，而是枚举运行时状态集，新敌人的关键机制不会被静默丢弃
  （已断言 Lagavulin 的 Metallicize 确实被导出）。
- 敌招按上游名称导出（如 `JAW_WORM_THRASH`），不是不透明的 enum 整数。

**仍未覆盖**：药水（native 无药水）、Burning Blood 以外的遗物、复杂选择界面、
非铁甲角色、非 Act 1 场景、Boss 战。

---

## G3 · 原版一致性：未执行

**本机没有《杀戮尖塔》游戏本体、ModTheSpire、BaseMod 或 CommunicationMod，也没有 Steam 安装与任何存档。**
无法生成独立于本模拟器的原版轨迹，因此 G3 保持未通过。
`compare_traces.py` 只是比较器；原版场景注入工具**尚未实现**。

`build_info()` 硬编码 `game_differential_verified=false`，并有测试断言它保持 false。

**在此状态下，以下所有 native 结果都必须读作「未认证模拟器 pilot」，不是《杀戮尖塔》成绩。**
CommunicationMod 实机联调同样**未执行**（仅有合成 JSON 协议测试），实机 MCTS 的
"从任意实况状态重建 native 搜索根"接口也**尚未实现**。

---

## E · native 闭环（三轮，全程锁在目标机上）

三轮都跑同一条有上限命令；差别只有夹具分布。原始日志 `logs/14_*`、`logs/21_*`、`logs/22_*`。

```bash
python scripts/run_iteration.py --output <dir> --config configs/native_pilot.json \
  --train-episodes 128 --val-episodes 16 --eval-episodes 32 --workers 2 --device cuda
```

### 第 1 轮（交付包原分布）：闭环跑通，但没有信号

`runs/native_i0/`｜训练 128 局 **127 胜 1 负**，验证 16 局 16 胜，0 截断。
**四个策略全部 32/32 全胜**，效用差 ≤0.003，置信区间几乎全部跨 0。
`value` 损失低到 **0.0013** —— 价值头只需学会输出常数，这正是"结果全是胜利"的直接证据。

按 `AGENTS.md` 步骤 E：全赢且没有难样本时应调整起始 HP／卡组分布，不得把这条曲线当能力进展。
第 1 轮**不产生任何强度结论**。

### 第 2 轮：扩展遭遇 + 调整分布后的完整对照

夹具现在把牌组家族与遭遇家族独立配对（`SCENARIO_REVISION=3`），并加入精英与多敌人。
以下为第 2 轮（覆盖全部 17 个遭遇）`runs/native_hard_i1/`：

| 量 | 值 |
|---|---|
| 训练局 | 128 局，128 完成，**110 胜 18 负**，0 截断，2,374 条样本 |
| 验证局 | 16 局，15 胜，0 截断，246 条样本 |
| 搜索成本 | 340.2 s（训练）+ 40.1 s（验证），64 模拟/步 |
| 优化步 | 500 |
| 参数量 | 1,949,325（d_model 128 / 4 层 / 4 头） |
| 验证损失 | 2.7514；policy 1.0639；outcome 3.1750；**value 0.0999** |
| teacher top-1 一致率 | 0.720 |
| 训练耗时 | 22.5 s |
| **GPU 峰值显存** | **83,436,032 B ≈ 79.6 MiB** |
| checkpoint sha256 | `50003648458973e0fe1c406bcae1394476d86765977dfd04c6b21b9f632fa41e` |

`value` 损失从 0.0013 升到 0.0999：价值头终于有东西可学。

### 评测（32 局/策略，按场景 ID 配对）

| 策略 | 胜/负/截断 | 胜率 | Wilson 95% | 平均效用 | 存活 HP | p50 | p95 |
|---|---|---|---|---|---|---|---|
| heuristic | 30/2/0 | 0.938 | [0.799, 0.983] | 0.8423 | 39.4 | 0.04 ms | 0.1 ms |
| search (64 sim) | 31/1/0 | 0.969 | [0.843, 0.994] | **0.8803** | **43.5** | 108.1 ms | 372.5 ms |
| model（纯网络） | 30/2/0 | 0.938 | [0.799, 0.983] | 0.8413 | 38.9 | **2.5 ms** | **6.9 ms** |
| hybrid | 31/1/0 | 0.969 | [0.843, 0.994] | 0.8740 | 40.9 | 295.5 ms | 556.1 ms |

配对效用差（bootstrap 95%）：

- **search − heuristic：+0.0380，CI [+0.0069, +0.0952]** —— 区间不含 0，搜索**确实**更强
- model − heuristic：−0.0011，CI [−0.0821, +0.0772] —— 与启发式**无法区分**
- hybrid − heuristic：+0.0316，CI [−0.0008, +0.0917] —— 边缘，接近但不含 0

### 第 3 轮：模型指导搜索 + 复用上轮数据（`runs/native_hard_i2/`）

```bash
python scripts/run_iteration.py --output runs/native_hard_i2 --config configs/native_pilot.json \
  --iteration 1 --checkpoint runs/native_hard_i1/model/best.pt --replay runs/native_hard_i1/train \
  --train-episodes 256 --val-episodes 32 --eval-episodes 64 --workers 2 --device cuda
```

教师改用上一轮网络评估叶节点，并把上一轮 train 目录一起训练（`run.json` 记录两个目录的
`scenario_revision` 都是 3，**没有跨夹具版本混数据**）。

| 量 | 值 |
|---|---|
| 训练局 | 256 局（+ 复用的 128 局 = 6,795 条样本），229 胜 27 负，0 截断 |
| 验证局 | 32 局，31 胜 |
| 搜索成本 | 1,391.8 s（训练）+ 88.0 s（验证） |
| 验证损失 | 2.4617；policy 1.0981；outcome 2.6524；**value 0.0374** |
| teacher top-1 一致率 | 0.7225 |
| GPU 峰值显存 | 89,671,680 B ≈ 85.5 MiB |
| checkpoint sha256 | `c5e051fb4fba9cd521a7c3c0ffbd5d5568b012c0e104594a6d429609da44ec94` |

评测（64 局/策略，配对）：

| 策略 | 胜/负 | 胜率 | 平均效用 | 存活 HP | p50 | p95 |
|---|---|---|---|---|---|---|
| heuristic | 59/5 | 0.922 | 0.8320 | 41.0 | 0.04 ms | 0.1 ms |
| search | 61/3 | 0.953 | **0.8678** | **44.2** | 142.2 ms | 574.0 ms |
| model | 60/4 | 0.938 | 0.8411 | 38.9 | **3.4 ms** | **10.2 ms** |
| hybrid | 61/3 | 0.953 | 0.8598 | 40.8 | 416.0 ms | 901.4 ms |

配对效用差：

- search − heuristic：**+0.0358，CI [+0.0079, +0.0757]** —— 显著
- model − heuristic：+0.0091，CI [−0.0073, +0.0382] —— **仍跨 0**
- hybrid − heuristic：+0.0278，CI [−0.0013, +0.0695] —— 边缘

### 第 4 轮：同一批数据训练更久 + 128 局评测（`runs/native_hard_i3/`）

第 3 轮的诊断是"数据涨了 2.9 倍但 `max_updates` 没变"。本轮**不加数据**，只把
`max_updates` 从 500 提到 2000（`configs/native_pilot_long.json`），并把评测扩到 128 局/策略：

```bash
python -m stsai train --train-data runs/native_hard_i2/train runs/native_hard_i1/train \
  --val-data runs/native_hard_i2/val --output runs/native_hard_i3/model --device cuda \
  --backend lightspeed_pilot --config configs/native_pilot_long.json
python -m stsai evaluate --output runs/native_hard_i3/eval --count 128 \
  --agents heuristic search model hybrid --checkpoint runs/native_hard_i3/model/best.pt \
  --device cuda --backend lightspeed_pilot --config configs/native_pilot.json
```

| 量 | 值 |
|---|---|
| 优化步 | 2,000（4×） |
| 最优验证损失 | **2.2545**（500 步时为 2.2624 —— 几乎没有变化） |
| teacher top-1 一致率 | 0.7137（500 步时 0.7225，**没有提高**） |
| GPU 峰值显存 | 89.7 MiB |
| checkpoint sha256 | `b7867c04e8752f9d47c2a9f19682a64725121136915827b07d819caaa2c15fef` |

**结论：瓶颈不是优化步数。** 4 倍优化步数既没有改善验证损失，也没有提高与教师的一致率。

评测（**128 局/策略**，配对）：

| 策略 | 胜/负 | 胜率 | Wilson 95% | 平均效用 | 存活 HP | p50 | p95 |
|---|---|---|---|---|---|---|---|
| heuristic | 114/14 | 0.891 | [0.825, 0.934] | 0.8029 | 40.6 | 0.04 ms | 0.1 ms |
| search | 124/4 | 0.969 | [0.922, 0.988] | **0.8754** | **41.4** | 149.1 ms | 599.8 ms |
| model | 117/11 | 0.914 | [0.853, 0.951] | 0.8207 | 39.2 | **3.6 ms** | **9.7 ms** |
| hybrid | 123/5 | 0.961 | [0.912, 0.983] | 0.8649 | 40.0 | 437.3 ms | 912.4 ms |

配对效用差（bootstrap 95%，128 对）：

- **search − heuristic：+0.0724，CI [+0.0382, +0.1128]** —— 显著
- **hybrid − heuristic：+0.0620，CI [+0.0294, +0.1016]** —— **显著**
- model − heuristic：+0.0178，CI [−0.0076, +0.0482] —— 几乎但不含 0

### 结论：搜索与混合搜索显著更强，纯网络仍未分离

1. 夹具现在有区分度：搜索和混合搜索都**显著**优于启发式（第 1 轮只有 0.0002 的噪声差）。
2. **纯蒸馏网络仍未能与启发式区分。** 它的点估计在改善（32 局 −0.001 → 64 局 +0.009 →
   128 局 +0.018），区间也在收窄，但 128 对样本下 CI 仍跨 0。**不得据此宣称模型更强。**
3. **优化步数不是瓶颈**：4× 优化步数没有改变验证损失或教师一致率。
   下一步该查的是数据多样性／模型容量／教师目标质量，不是继续加步数或加数据。
4. 纯网络的价值在**延迟**：3.6 ms vs 搜索 149 ms（≈41×），而效用只差 0.055。
   需要低延迟时用纯网络；追求强度时 hybrid 已能追上搜索（0.8649 vs 0.8754），
   代价是 3× 延迟。
5. **样本量仍未达到晋级要求。** `docs/00_ACCEPTANCE.md` 要求 ≥1000 个固定验证场景的配对结果，
   本轮只有 128，且重复使用了同一批 val 场景（`evaluate` 固定取 val 前 N 个）。因此这只是开发信号，
   **不宣称 G4 达成**；正式结论需要模型选定后的新 test manifest。

---

## 诊断轮（第二轮任务书）

基线 `reports/baseline_freeze.json`（`baseline_id = ec5bef08…`）。详细报告见
`reports/distillation_diagnosis.md` 与 `reports/hybrid_profile.md`。

### 收益：三处已修的缺陷

1. **公平性泄漏（我上一轮引入的）**。上一轮把敌人"计划招式"的上游名称写进 observation。
   实测在 17 个遭遇上，(怪物, intent, 伤害, 命中数) 有 **9 组对应两个不同招式**
   （Jaw Worm Chomp/Thrash、Lagavulin Sleep/Siphon Soul、Looter Escape/Smoke Bomb、
   Acid Slime Corrosive Spit/Tackle）。玩家看不出区别，模型却拿到了确切身份。
   **计划招式已不再导出**，并加了回归测试。
2. **`moveHistory` 语义错误**。它记录的是"最近两次 roll 过的招式"，不是"执行过的"。
   一个每回合都攻击的 Cultist，`previous_move` 永远停在 `INCANTATION`。
   适配器改为自己跟踪上一回合实际观察到的招式（并处理 Looter 逃跑这类
   "敌人行动导致战斗结束"的情形）。
3. **top-1 指标错误**。旧指标比的是 `policy.argmax()`，而搜索在访问并列时用 Q 打破并列
   （实测 2.8–3.8% 的决策状态两者不同）；更严重的是它把 **25% 只有唯一合法动作的状态**
   算进了均值。**决策状态下与教师实际动作的一致率是 0.587，不是 0.69–0.72。**
   训练日志现在同时报告旧指标、与教师实际动作的一致率、仅决策状态的一致率、策略 KL 与教师熵。

### 诊断结论：瓶颈是泛化，不是容量也不是教师噪声

| 检验 | 结果 | 说明 |
|---|---|---|
| 输入冲突 | **0 组** | 编码后逐字节相同却标签不同的状态不存在 |
| 最小可拟合（256 固定状态） | **训练 KL 7.63e-06** | 网络能近乎完美拟合教师 |
| 教师自洽性（同批 24 状态，4 种子） | self-KL **0.0228**，类一致 **0.882** | 噪声下限 |
| 学生相对教师 | KL **0.0885**，类一致 **0.698** | **是噪声下限的 3.9 倍** |
| 高预算重标实验 | KL 0.1354 → **0.1290**，一致率 0.5547 → **0.5304** | **负结果，重标无效** |

即：教师噪声只占学生误差约四分之一，网络又能拟合教师，
剩下的是**泛化问题**（模型在第 100 步达到最优验证损失后开始过拟合，
而开发集只有 96 局 / 1331 个决策状态）。

> **过程更正**：本轮中途曾据不可比的两个数字得出"学生已到噪声下限"，
> 受控重测后该结论不成立，已在诊断报告中撤回。

### 成本分解（`reports/hybrid_profile.md`）

- 每次 simulation 调用一次完整 evaluator（64 sims → **65 次调用/决策**），
  且 `use_leaf_value=false` 时其 value 输出被丢弃。
- **batch=1 时 CUDA 前向比 CPU 慢**（CPU 1.3 ms vs CUDA 2.0–8.2 ms），
  因此本机上所有使用网络的搜索模式都比 CPU 慢。GPU 收益需要批处理，尚未实现。
- `hybrid` p50 约为 `search` 的 3 倍且不更强，按任务书判据**不晋级为默认策略**。

### 结局校准（与效用分开）

死亡概率取 11 类 outcome softmax 的第 0 类（`value` 是战斗效用，不是存活率）：
Brier **0.0901** 对常数基线 0.1178（skill 0.235），ECE 0.093；
按战斗聚类（24 场）Brier 0.0509，95% 区间 **[0.015, 0.188]** —— 太宽，不足以下结论。

### 本轮**没有**做的事（明确记录）

- **没有**做 128 vs 192 维对照 —— 诊断结论指向"下一轮做多训练种子对照"，本轮不越级宣称。
- **没有**生成最终测试 manifest，**没有**跑 1000 场正式配对评测，**没有**创建最终结果报告。
  开发模型选择尚未完成，提前使用 test 会让它变成开发集。
- **没有**实现墙钟预算接口，因此不能声称满足任何时限约束。
- **没有**做独立动作价值审计（`estimated_action_gap`），
  因此"跟随教师是否真的更好"仍未证明。
- 逐字段覆盖表尚未机器可读化；token 碰撞未取证；等价类失败案例未沉淀成测试。



**已经能做**

- 在本机从零建立隔离环境并通过真实 CUDA 前向+反向自检（含 BF16）。
- 锁定上游、编译 C++ 桥、跑 UBSan、跑 1000 局随机回放并全绿。
- 对 23 张卡（含升级）与 17 个 Act 1 遭遇做定向断言，9 个固定阵容敌人逐招全覆盖。
- 端到端 native 闭环：采集 → 蒸馏 → 加载 → 四策略配对评测 → 失败样本整理。
- 记录并公开两处上游规则补丁，使构建可追溯到「base + patches」。

**尚不能做**

- **没有任何原版游戏一致性证据**，模拟器规则保真度未经原版校验。
- 药水、Burning Blood 以外的遗物、复杂选择、非铁甲角色、非 Act 1、Boss。
- 从任意实机战斗状态重建 native 搜索状态；实机 MCTS。
- CommunicationMod 联调（未接真实游戏）。
- **强度结论：没有。** 蒸馏模型未超过启发式。

## 泛化实验轮（第三轮任务书）

详细报告：[generalization_experiment.md](generalization_experiment.md)。协议：
[generalization_protocol.json](generalization_protocol.json)（开跑前写入，未改写）。
基线 `parent_baseline_id = ec5bef081d64e1b399d89a18c70f341c17387669c2fe51857f0030c707771379`。

### 两处过强推断已修正

1. **self-KL 不是可减去的噪声下限**。按有限样本恒等式
   `mean_k KL(p_k‖q) = mean_k KL(p_k‖p_bar) + KL(p_bar‖q)` 重算（用任务书附带的
   `tools/diagnostic_stats.py` 复核，`identity_residual = 1.1e-16`，工具显式标注
   `is_population_noise_floor: False`）：教师离散 **0.008192**、学生项 **0.088512**（旧学生）
   / **0.073804**（本轮候选）。份额约 **90% 是学生**、10% 是教师离散。
   此前用 pairwise KL 当第一项得出的 `3.88×` **已撤回**；两项本身也只是 K=4 的估计。
2. **高预算重标是混合结果**：KL 降（0.1354→0.1290）但动作一致率也降（0.5547→0.5304），
   没有同一冻结参考下的显著性检验，也**不能**说它在效用上更好。操作结论：**冻结教师**。

### N0 门槛：通过（sampler 状态 = 已审计、未经经验证明）

四类产物均在修复后生成；12 次训练**全部随机初始化**。
sampler 会复制 `moveHistory[0]`（未执行的计划招式），但代码路径核查显示
`rollMove` 在 `setMove` **之前**读取历史，读到的因此是**刚执行过**的招式（公开）。
决定性经验测试无法构造：扫描全部 **2104** 个已存状态，**跨局公开状态碰撞为 0**。
残余假设（已执行招式可由可见后果事后识别）记录在案。

### N1 矩阵：12/12 执行，宽度与正则化都没有可靠收益

**kl_dev**（每战斗决策 KL 再对战斗平均）配对差：
**192−128 = +0.01254**（sd 0.01006，6 对中 5 对更差）；**R1−R0 = −0.00037**（sd 0.00516）。
成本：参数 1.95M → 3.59M（1.84×）。**128 与 192 不是相同 FLOPs。**

### N2 开发闭环（256 冻结场景，完整配对 256/256，0 截断）

| 策略 | 胜 | 平均效用 | p50 |
|---|---|---|---|
| random | 120 | 0.4085 | 0.00 ms |
| heuristic | 228 | 0.8073 | 0.03 ms |
| search (64 sim) | 245 | **0.8678** | 128.3 ms |
| M128-R0（3 seed） | 236 | **0.8297** | 1.31 ms |
| M192-R1（3 seed） | 236 | **0.8301** | 1.55 ms |

- search − heuristic **+0.0605 [+0.0347, +0.0875]**（显著）
- 12 个模型相对启发式点估计全为正，11/12 区间跨 0
- **192−128（效用）+0.00023 [−0.0095, +0.0098]**；**R1−R0 +0.00015 [−0.0063, +0.0065]**
- 疑似**宽度×正则化交互**（R1 伤 128、利 192，6/6 种子一致），两侧区间仍含 0 → 只是提示

**KL 与效用排名不一致**：M128-R1 的 kl_dev 最好但效用更低；更接近教师没有转化为更好的对局。

### 独立动作价值审计

64 根（重放失败 0），一致 47 / 分歧 17，共用冻结 continuation，各 64 个独立 belief 样本：
delta = **−0.00981 [−0.02703, +0.00045]**（分歧子集 −0.03692 [−0.09551, +0.00162]），
根内 MC 标准误中位数 0.003，截断分支 0。
**在这个 continuation 下没有证明跟随教师更好**（区间含 0，且 continuation 本身是学生模型）。

### 配对 Brier 差（一处更正）

基线死亡率**从训练分片冻结** = 0.24634，评估集死亡率 0.13636。
差值 **+0.03673 [−0.04909, +0.13160]**（`tools/diagnostic_stats.py` 复核一致）。
此前"skill 0.235"的对比用的是**评估集自己**的死亡率当基线 —— 那是用评估集拟合基线。
**死亡概率预测未被证明优于常数基线。**

### 本轮未做

P6 正式测试（未生成/未解封 manifest）、hybrid 未晋级、墙钟预算接口未实现、
数据扩容与学生状态重标**均未启动**（本轮没有证据支持启动，且不应同时改变数据量与分布）、
未盲增优化步数。`game_differential_verified` 保持 `false`。

## S1 轮（输入语义与训练归一化）

交付包 `stsai_s1_review_feb8a46.zip`（8.40 MB / 31 文件）。详细见包内 SUMMARY.md。
基线 `79f42fc`，本轮 3 个 commit：`f689ce4`（有效 batch 计数）、`dbb4204`（公开意图）、
`feb8a46`（同规模重建 + 一个新基线）。

### S1-A 计数规则

一个 optimizer update 内的所有微批次合起来是有效 batch：
`L_policy = Σ d_i·CE_i / Σ d_i`，outcome/value 同理，总数由三项聚合重构。
复核对数 `[1,0,3,5]`/`[1,0,1,1]` 分两批：旧规则 **2.5**，新规则 **3.0**。
partition 不变性由真实 trainer 验证（32×1 / 16×2 / 8×4 参数相同），
把循环改回旧规则该测试**会失败**（已验证）。验证聚合全量累加后归一，
批大小 1/2/3/7 结果一致（旧实现 2.5→3.0）。新增 `LOSS_REVISION = 2`。
尾部不足窗口仍丢弃（本轮 144 行）并记录。

### S1-B 公开意图

`intent` 从两类扩到 **10 个公开类别**：50 招式 / 22 怪物，7 行 wiki 核对、43 行由上游效果
推导（CSV 内附行号与 URL）。**0 行原游戏核对**，`game_differential_verified` 保持 false。
表由 `native/intent_table.def` 单一来源生成，测试重跑生成器比对防漂移。
`previous_move`（身份）改为 `previous_intent`（类别）。schema 2→3、encoding 2→3。

**采样审计**：`moveHistory[0]` 为 PUBLIC_DETERMINED —— **3584 个可达状态、93 个公开签名、0 碰撞**，
即意图类别 + 显示伤害足以确定持有的招式（Looter Mug/Lunge 同类不同伤害）。
RNG 六路与抽牌堆顺序为 RESAMPLED；不可达怪物的 latent 字段为 UNSUPPORTED。

### S1-C/D/E

- 数据同规模重建：96/24 初始场景不变（可逐字节复现），
  **轨迹完全一致**（action/policy/outcome 逐行相同）而 **observation 全部不同** —— 隔离出的正是输入语义。
- 只训练 `M128-R0-s17-S1` 一个 run：selected step 400（kl_dev 0.10678）、last step 500，
  policy_loss 1.4275，`CE = KL + H` 恒等式成立。
- 256 场开发评测（完整配对 256/256，0 截断，20,000 次 bootstrap seed 20260918）：
  student − heuristic **+0.01479 [−0.01033, +0.04104]**（跨 0），
  student − search **−0.04570 [−0.06955, −0.02432]**（排除 0），
  search − heuristic +0.06049。pooled 决策 p50 1.245 ms 对 151.881 ms。

### 未做 / 阻塞

未训练 192、未跑多种子、未加数据、未 DAgger、未改 teacher 预算或 utility、未解封 final test。
G3 原游戏差分仍未执行（本机无合法游戏）。跨 continuation 的 Brier 只作诊断（模型 0.21150 对
常数基线 0.12986）。

## S1-B 轮（隐藏状态与生命周期修复）

交付包 `stsai_s1b_review_1d49eec.zip`（2.28 MB / 25 文件）。**0 新训练、0 新采集、0 次 256 场评测、未动 P6。**
基线 `c09167b`，本轮 5 个 commit。

### 虱子预生成攻击值（复核发现，已修）

`Monster.cpp:118-120` 出生时把基础攻击写入 `miscInfo`，`MonsterSpecific.cpp:745/:1006` 的攻击直接用它。
c09167b 的 `sample()` 整体复制而不处理 → rollout 用了玩家看不见的数。
现在按槽位维护**只由公开历史决定**的候选区间（出生范围 → 每显示一次攻击就收窄 → 唯一即保留 → 多解即保留不确定性），
每次 simulation 抽一次并保持，真实值从不读取；区间经 `attack_base_low/high` 导出。
`tests/test_louse_hidden_base.py` 6 项：固定 sampler 在 5 个 seed 上一致、
**修复前的 sampler 在同一对根上全部分叉**（负对照）。

### 真实执行事件（已修）

不再用 `bc.turn` 变化推断。上游补丁 `0003-combat-event-log.patch`（只做观测，无规则读取）
在 `doMonsterTurn` 真正执行前记录 `EXECUTED`，在 `createMonster` 与 `largeSlimeSplit` 记录 `SPAWNED`。
适配器按序消费：被杀未行动 = NONE、Looter 逃跑仍计入、重复 observe 幂等、**分裂的新实体不继承旧槽历史与记忆**。
覆盖了 LARGE_SLIME 分裂（已在范围内，不再写作"扩范围后验证"）。
负对照测试固定了旧规则的反例：它会给**从未出手**的第三只虱子发 `ATTACK`、给 Sentry 发 `DEBUFF`。

### 审计与证据等级（已改）

删掉 `public_determined = not collisions and checked > 2000`：扫描只作 **coverage 统计**，
类别由逐字段声明给出（写入点/读取点/可见性/依据/测试）。
12 字段：6 PUBLIC_DETERMINED / 4 RESAMPLED / 2 UNSUPPORTED，另设 `incomplete_evidence`。
意图映射 43 行 `ENGINE_DERIVED_ONLY`、7 行 `UI_SOURCE_VERIFIED`、**0 行原游戏核对**；
`UNKNOWN` 的两种原因（游戏真显示 unknown / 我们不知道）分开记录。

### 四个契约（已修）

生产路径 shape 校验（先前 (B,1) decision 被接受，2.2377→7.5941）；三个入口共用版本检查；
尾部计数用实际缓存行数（**S1 run 正确值 126，与复核的 16126−16000 精确吻合**，原 144 是错的）；
`losses()` 恢复可微。顺带修掉 `effective_batch_samples` 记名义值的问题。

### 离线 native

`native_sources.tar.gz`（128 文件，0.62 MB，POST_PATCH，含三份许可证）
+ `review/offline_native_build.py`：校验全部哈希后 cmake 配置/编译/导入，
`build_info` 报告**三个**补丁，并断言 `game_differential_verified=false`。
**已在干净克隆上实跑通过**；`review/run_review.py` 七个步骤全 PASS。

**过程中修掉一个 provenance 缺陷**：事件日志补丁已提交但 `engine_lock.json` 未提交，
会使该 commit 的检出少报补丁；已修并加测试要求 lock 与 `native/patches/` 一致。

## 阻碍

1. **没有合法原版游戏**（G3 阻塞）。需要合法安装游戏本体 + ModTheSpire + BaseMod +
   CommunicationMod，或授权安装；在此之前原版差分与实机联调无法进行，不会编造通过。
2. **蒸馏未收敛**（G4 阻塞）。教师优势没能完整搬进网络：4× 优化步数无效，
   说明瓶颈在数据多样性／模型容量／教师目标质量，而非训练长度。
3. 评测样本量小（32 局），达不到晋级所需的 1000 场景配对。

## 下一步（按优先级）

1. **查蒸馏瓶颈**（不是加步数/加数据）：先测教师 top-1 一致率为何卡在 0.72 ——
   分别看策略头容量、编码是否丢掉了决策所需信息（`docs/05_ROADMAP.md` 的 profiler 顺序），
   并考虑扩大 `d_model`（`configs/rtx5070_12gb.json` 的 192 维）与更高的教师模拟预算。
2. 用 1,000 个固定验证场景做正式配对评测（`make-test-manifest`），替换 128 局开发信号。
   注意：先要用新数据、新 output 目录，不能与已看过的 val 混用。
3. 用户提供合法游戏后：实现场景注入 + 原版差分（G3），先做无随机分支的单步测试。
4. 继续补药水与遗物（roadmap P4/P5）：每项都必须同时增加状态导出、合法动作、采样审计、
   模型编码和规则测试。当前 native 仍无药水、遗物只有起始 Burning Blood。
5. `docs/05_ROADMAP.md` 要求的校准指标（Brier / ECE / reliability bins / 分难度分层）尚未实现，
   outcome head 的输出**不能**当成校准过的概率。
