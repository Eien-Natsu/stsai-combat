# 目标机状态（RTX 5070 · 实际执行记录）

本文件记录在目标机上的**实际执行**。原始日志在 `logs/`，结构化产物在 `runs/`、`reports/`。
未执行的项明确写“未执行”，skip 不计入通过。

平台：Debian 12 (bookworm) / WSL2，12 逻辑核，15 GB RAM，893 GB 可用磁盘。
代码基线：交付包 `STSAI_Combat_5070_v0.1.zip`（commit `e2e58d6`）。

## 关卡总览

| 关卡 | 状态 | 依据 |
|---|---|---|
| G0 工程闭环 | **通过（本机）** | `logs/23_pytest_final.txt`：189 passed, 0 failed, **0 skipped** |
| G1 5070 GPU | **通过** | `runs/doctor.json`：`cuda_verified=true`，真实前向+反向，BF16 |
| G2 native pilot | **工程部分通过** | 编译、189 项测试实跑、1000 局随机回放 0 异常；**原版差分未做** |
| G3 原版一致性 | **未执行（本机无合法原版游戏）** | 见"阻碍 1" |
| G4 强度进步 | **未达成** | 搜索显著优于启发式；**蒸馏模型尚未超过启发式**，见下 |
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

### 第 2–3 轮：扩展遭遇 + 调整分布后的完整对照

夹具现在把牌组家族与遭遇家族独立配对（`SCENARIO_REVISION=3`），并加入精英与多敌人。
以下为第 3 轮（覆盖全部 17 个遭遇）`runs/native_hard_i1/`：

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

### 结论：搜索有效，蒸馏尚未成功

1. 夹具现在有区分度：搜索稳定胜过启发式（第 1 轮是 0.0002 的噪声差）。
2. **但蒸馏没有把搜索的优势搬进网络。** 纯网络与启发式统计上无法区分，
   teacher top-1 一致率 0.72，说明网络学到了教师的一部分但不是全部。
   这是本轮最需要修的环节（更多数据 / 更多迭代 / 提高教师预算），不是堆参数能解决的。
3. 纯网络的价值在于**延迟**：2.5 ms vs 搜索 108 ms（≈43×），而 hybrid 反而比纯搜索更慢
   （295 ms）却没换来更高效用 —— 当前预算下 hybrid 不划算。
4. **32 局只是 smoke。** 按 `docs/00_ACCEPTANCE.md`，晋级需要 ≥1000 个固定验证场景的配对结果。
   `evaluate` 本身不给出晋级结论，本轮也**不宣称 G4 达成**。

---

## 能力边界

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

## 阻碍

1. **没有合法原版游戏**（G3 阻塞）。需要合法安装游戏本体 + ModTheSpire + BaseMod +
   CommunicationMod，或授权安装；在此之前原版差分与实机联调无法进行，不会编造通过。
2. **蒸馏未收敛**（G4 阻塞）。教师优势没能搬进网络；需要更多数据/迭代，或提高教师预算。
3. 评测样本量小（32 局），达不到晋级所需的 1000 场景配对。

## 下一步（按优先级）

1. 扩大采集规模（128 → 1024 局）并做第二轮迭代（用上轮 checkpoint 指导搜索、`--init-checkpoint` 保留旧数据），
   观察 model − heuristic 的置信区间是否离开 0。
2. 用 1000 个固定验证场景做正式配对评测，替换 32 局 smoke。
3. 用户提供合法游戏后：实现场景注入 + 原版差分（G3），先做无随机分支的单步测试。
4. 继续补药水与遗物：每项都必须同时增加状态导出、合法动作、采样审计、模型编码和规则测试。
