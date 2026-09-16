# 目标机状态（RTX 5070 · 实际执行记录）

本文件记录在目标机上的**实际执行**。每项的原始日志在 `logs/`，结构化产物在 `runs/`、`reports/`。
未执行的项明确写“未执行”，skip 不计入通过。

平台：Debian 12 (bookworm) / WSL2，12 逻辑核，15 GB RAM，893 GB 可用磁盘。

## 关卡总览

| 关卡 | 状态 | 依据 |
|---|---|---|
| G0 工程闭环 | **通过（本机）** | `logs/13_pytest_provenance.txt`：161 passed, 0 failed, **0 skipped** |
| G1 5070 GPU | **通过** | `runs/doctor.json`：`cuda_verified=true`，真实前向+反向 |
| G2 native pilot | **部分通过** | 编译通过、全 native 测试实跑、1000 局随机回放 0 异常；**非原版差分** |
| G3 原版一致性 | **未执行（无合法原版游戏）** | 见下"阻碍" |
| G4 强度进步 | **未达成** | 夹具分布无区分度，见下"发现" |
| G5 完整战斗覆盖 | **未完成** | 21 张卡 / 2 敌人 / 无药水 / 仅 Burning Blood |

## 环境与依赖

| 项 | 值 |
|---|---|
| GPU | NVIDIA GeForce RTX 5070，`compute_capability=[12,0]`，12,227 MiB（`prop.total_memory=12,820,480,000`） |
| 驱动 | 591.86（`nvidia-smi` 报告 CUDA 13.1 运行时） |
| Python | 3.12.14（项目本地 `python-build-standalone`，见下） |
| PyTorch | 2.9.1+cu128，`torch.version.cuda=12.8`，`compiled_architectures` 含 `sm_120` |
| BF16 | 支持，doctor 中已用 `torch.autocast(bfloat16)` 实测 |
| CUDA 自检 | 实际 `CombatNet` 前向 + `loss.backward()`，梯度全部有限 |
| 锁文件 | `requirements/target-resolved.txt` |

### 环境修复（本机原本无法编译 native）

1. 镜像只有系统 `python3`，**没有 `python3-dev`**，`Python.h` 缺失，CMake 报
   `Could NOT find Python (missing: Python_INCLUDE_DIRS Development.Module)`。
   AGENTS.md 规定系统包需授权，因此**未安装系统包**，改为 `scripts/setup_python_local.sh`
   用 uv 在项目内 `.python/` 装官方 `python-build-standalone` 解释器（自带头文件），
   `setup_linux.sh` 检测不到 `Python.h` 时自动改用该解释器。
2. 镜像**没有 `cmake`**，apt 源里也没有；`build_native.py` 直接调用 `cmake`。
   已加入 `requirements/dev.txt`（`cmake>=3.20`，实装 4.4.3）。

## G2 · 原版候选编译与运行

上游锁定（`engine_lock.json`）：

- 仓库 `gamerpuppy/sts_lightspeed`，revision `7476a81954020087da31d41d16fddf475746ec2d`
- `json` 子模块 `0b345b20c888f7dc8888485768e4bf9a6be29de0`
- 上游 `LICENSE.md` sha256 `accfd224...`

**交付包声称未编译过；实机结果：`native/bridge.cpp` 未改一行即编译通过并链接成功。**
唯一需要的改动是环境（Python 头文件、cmake），不是 C++ API。

```bash
python scripts/fetch_engine.py                 # 锁定 SHA
python scripts/build_native.py --jobs 8        # 编译 + import + native pytest
python scripts/build_native.py --jobs 8 --sanitize   # UBSan
python scripts/native_replay.py --episodes 1000 --workers 6 --output runs/native_replay_1000.json
```

结果：

| 项 | 结果 |
|---|---|
| 编译 | 成功，`src/stsai/_lightspeed.cpython-312-x86_64-linux-gnu.so` |
| native 测试 | 15 passed（`tests/test_native.py`） |
| UBSan | 构建+测试通过，`-fsanitize=undefined -fno-sanitize-recover=all`，无 UB 报告 |
| 新增卡牌/敌人定向测试 | `tests/test_native_coverage.py`，75 passed |
| 随机回放 1000 局 | **0 非法动作被接受、0 崩溃、0 UB 标记、0 采样破坏公开根、0 超预算**（16,577 步） |
| 状态转移吞吐 | 8,260 transitions/s（单进程，含 observe 与重置） |
| 搜索吞吐 | 32 模拟 / 0.076 s ≈ 420 模拟/s（单进程） |

### 发现的上游规则错误（已修复，带出处）

`CardId::DISARM` 在上游 `src/combat/BattleContext.cpp` 中硬编码 `-2`，**完全没有使用
`up`（升级标志）**，因此升级后的大砍刀（Disarm+）仍然只减 2 点力量。原版应减 3 —— 见
Sources 的 wiki 佐证。模拟器是搜索教师，规则错误会污染它生成的每一条轨迹。

修复以**补丁序列**形式落地，而不是直接改工作区：

- `native/patches/0001-disarm-upgrade-strength.patch`（sha256 `6494c601...`）
- `engine_lock.json` 记录补丁 hash；`scripts/build_native.py` 在编译前要求工作区
  **恰好等于「锁定 revision + 声明的补丁」**，否则拒绝构建
- `build_info()` 输出 `revision` 与 `patches`，测试断言二者与 lock 一致 ——
  **构建结果不会把打过补丁的树谎报成未改动的上游**

### 覆盖范围（仍有限）

- 卡牌 21 张（打击/防御/痛击/登峰造极之灾 + 17 张），**每张 base 与升级都断言了
  已知数值**（伤害/格挡/抽牌/易伤/虚弱/力量/金属化/消耗/虚无/X 费/0 费）。
- 敌人 2 个：Cultist（INCANTATION、DARK_STRIKE）、Jaw Worm（CHOMP、THRASH、BELLOW），
  **可见行为分支已全覆盖**。敌人招式现按上游名称导出，不再是不透明的 enum 整数。
- **多敌人（`monsterCount > 1`）路径完全没有被夹具覆盖** —— 当前只有单敌人战斗。
- 遗物仅起始 Burning Blood；**无药水**；不接受复杂选择。

## G3 · 原版一致性：未执行

**本机没有《杀戮尖塔》游戏本体、ModTheSpire、BaseMod 或 CommunicationMod，
也没有 Steam 安装与任何存档。** 无法生成独立于本模拟器的原版轨迹，
因此 G3 保持未通过。`compare_traces.py` 只是比较器，场景注入工具尚未实现。

`build_info()` 硬编码 `game_differential_verified=false`，并有测试断言它保持 false。

**在此状态下，所有 native 结果都必须读作「未认证模拟器 pilot」，不是《杀戮尖塔》成绩。**

## E · 小规模 native 闭环（第 0 轮）

命令（`docs/03_RUNBOOK.md` / README 原文）：

```bash
python scripts/run_iteration.py --output runs/native_i0 --config configs/native_pilot.json \
  --train-episodes 128 --val-episodes 16 --eval-episodes 32 --workers 2 --device cuda
```

原始日志 `logs/14_native_i0.log`，产物 `runs/native_i0/`。

| 量 | 值 |
|---|---|
| 训练局 | 128 局，128 完成，**127 胜 1 负**，0 截断，1,702 条样本 |
| 验证局 | 16 局，16 胜，0 截断，140 条样本 |
| 搜索成本 | 196.4 s（训练收集）+ 16.9 s（验证收集），共 64 模拟/步 |
| 优化步 | 500 |
| 参数量 | 1,949,325（d_model 128 / 4 层 / 4 头） |
| 验证损失 | 2.2210；policy 0.9916；outcome 2.4562；**value 0.00133** |
| teacher top-1 一致率 | 0.871 |
| 训练耗时 | 31.8 s |
| **GPU 峰值显存** | **61,502,976 B = 58.7 MiB**（`peak_allocated_bytes`） |
| checkpoint sha256 | `1a85f8474c861a5bf01a9c3695f8d47a0b37410914b2f9ae4b74b98685e172b6` |

### 评测（32 局/策略，配对，同一场景种子）

| 策略 | 胜 | 负 | 截断 | 平均效用 | 存活 HP | p50 延迟 | p95 延迟 |
|---|---|---|---|---|---|---|---|
| heuristic | 32 | 0 | 0 | 0.9068 | 42.7 | 0.041 ms | 0.106 ms |
| search (64 sim) | 32 | 0 | 0 | 0.9070 | 42.8 | 100.0 ms | 226.4 ms |
| model（纯网络） | 32 | 0 | 0 | 0.9038 | 41.5 | 3.50 ms | 8.00 ms |
| hybrid | 32 | 0 | 0 | 0.9048 | 41.9 | 360.5 ms | 554.9 ms |

配对效用差（bootstrap 95%）：

- search − heuristic: `+0.00023 [-0.00047, +0.00117]`
- model − heuristic: `−0.00305 [−0.00578, −0.00078]`
- hybrid − heuristic: `−0.00195 [−0.00445, +0.000002]`

### 结论：闭环跑通，但这一夹具分布没有区分度

四个策略 **全部 32/32 全胜、零截断**，效用差在 0.003 以内，置信区间几乎全部跨 0。
`value` 损失低到 0.0013，正是"结果全是胜利、价值头只需学会输出常数"的直接证据。

按 `AGENTS.md` 步骤 E：**全赢且没有难样本时，应调整起始 HP／卡组分布，而不是把这条
训练曲线当能力进展。** 本报告不据此宣称任何强度提升。

**因此这里不宣称 G4。** 小样本只验证了流程可运行。

## 能力边界（能 / 不能）

**已经能做**

- 在本机从零建立隔离环境并通过真实 CUDA 前向+反向自检（含 BF16）。
- 锁定上游、编译 C++ 桥、跑 UBSan、跑 1000 局随机回放并全绿。
- 对 21 张白名单卡（含升级）与 2 个敌人的可见行为做定向断言。
- 端到端 native 闭环：采集 → 蒸馏 → 加载 → 四策略配对评测 → 失败样本整理。
- 记录并公开上游规则补丁，使构建可追溯到「base + patches」。

**尚不能做**

- 没有任何原版游戏一致性证据（G3 未执行）；模拟器规则的**保真度未经原版校验**。
- 多敌人战斗、药水、除 Burning Blood 外的遗物、复杂选择、非铁甲角色、非 Act 1 场景。
- 从任意实机战斗状态重建 native 搜索状态（实机 MCTS 缺口）。
- CommunicationMod 联调：**未接真实游戏**，仅有合成 JSON 协议测试。
- 强度结论：无。当前夹具下所有策略并列。

## 阻碍

1. **没有合法原版游戏**（G3 阻塞）。需要用户合法安装游戏本体 + ModTheSpire + BaseMod +
   CommunicationMod，或授权安装；在此之前原版差分与实机联调都无法进行，不会编造通过。
2. **夹具分布过易**（G4 阻塞）。单只 Cultist / Jaw Worm 对搜索与启发式都不构成挑战，
   无法区分策略。下一步需要扩展敌人（尤其精英与多敌人遭遇）并下调起始 HP/卡组强度。
3. 磁盘与时间：本机 893 GB 可用，不是瓶颈。

## 下一步（按优先级）

1. 扩展遭遇覆盖到多敌人与 Act 1 精英（`GREMLIN_NOB`/`LAGAVULIN`/`THREE_SENTRIES`、
   `GREMLIN_GANG`、`EXORDIUM_THUGS` 等），同时**导出全部可见怪物 power**（当前只导出 RITUAL），
   并按 `docs/04_NATIVE.md` 逐敌做隐变量审计。
2. 调整起始 HP／卡组分布，制造有败局的训练信号，再重跑闭环并观察是否出现区分度。
3. 用户提供合法游戏后：实现场景注入 + 原版差分（G3），先做无随机分支的单步测试。
