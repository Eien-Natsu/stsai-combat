# STSAI Combat · RTX 5070 交付工程

**版本：0.1.0｜交付日期：2026-09-16｜交付对象：能够操作目标电脑的编程 AI**

目标是从局内战斗开始，构建不读取隐藏随机数的铁甲战士战斗 AI。主线是：**模拟器 → 公平随机搜索教师 → Entity Transformer 蒸馏 → 模型辅助搜索 → 独立评测**。不包含路线、选牌、商店、整局胜率规划。

> **请先读清验证边界。** 本包有实际 Python/C++ 源码、自动化测试和跑通的训练闭环，不是只有方案；但它不是训练完成的强 AI，也不是已经完整覆盖原版的即用机器人。`reference_v1` 是工程测试环境，绝不能把它的成绩报成《杀戮尖塔》成绩。`lightspeed_pilot` 是原版规则模拟器的有限范围 C++ 接入候选，交付环境无法获取并编译上游，因此目标 AI 必须先完成编译、原版差分与范围扩展。不能在玩具环境里长期训练后宣布完成。

## 交付状态

| 部分 | 代码状态 | 本次验证范围 |
|---|---|---|
| 统一观察／动作协议、隐藏信息隔离 | 已实现 | Python 回归测试 |
| 参考战斗环境 | 已实现 | 自包含规则测试；不是原版复刻 |
| 按观察历史分支的随机 PUCT | 已实现 | 合法性、隐藏状态不变性、采样测试 |
| Entity Transformer、多头监督训练 | 已实现 | CPU 前向／反向、保存／恢复、加载推理 |
| 并行采集、蒸馏、配对评测、失败样本整理 | 已实现 | CPU 端到端测试与多进程测试 |
| 5070 安装脚本、显存档位、自检 | 已实现 | **没有在真实 5070 上执行** |
| `sts_lightspeed` C++ 绑定 | 候选源码已实现 | **尚未编译，不宣称可直接通过** |
| CommunicationMod 控制桥 | 已实现有限范围解析及策略出牌 | 合成 JSON／协议测试；**未接真实游戏** |
| 全铁甲卡池、全敌人、完整遗物与药水 | 下一阶段工程 | 不在当前可用覆盖范围 |

本地实际测试记录在 `reports/`，包括 pytest 原始输出、JUnit、自检、smoke 和评测。包内不提供冒充实战模型的 smoke 权重。

## 交给下一位 AI

把整个目录和 `HANDOFF_PROMPT_zh.md` 一起交付。接手 AI 首先阅读 `AGENTS.md`、`docs/00_ACCEPTANCE.md` 和 `docs/04_NATIVE.md`，按关卡执行并修复源码，而不是向用户再交一份计划。

## 从零启动

推荐在 Linux 或 WSL2 Ubuntu 中运行原版 C++ 部分。Python 3.12 是本项目建议的目标解释器；本次本地测试环境是 Python 3.13.5 / PyTorch 2.10.0+cpu，**与目标 CUDA 锁定组合不同**。

已有 Python、Git、CMake 3.20+、C++17 编译器和正确安装的 NVIDIA 驱动后，在项目根目录：

```bash
bash scripts/setup_linux.sh cuda
source .venv/bin/activate
python -m pytest -q
python scripts/smoke.py --output runs/smoke --device cuda
```

仅调试 Python、机器没有 GPU 时，可用 `bash scripts/setup_linux.sh cpu` 和 `--device cpu`。CPU smoke 通过不替代 GPU 验收。

Windows Python 安装脚本：`powershell -File scripts/setup_windows.ps1 -Mode cuda`。原版编译优先移到 WSL2，不要假定 MSVC 可无修改编译上游。

安装脚本选择 `torch==2.9.1` 的 CUDA 12.8 wheel，**这是有官方安装记录的固定基线，不是“当前最新版”声明**。真正兼容以 `doctor --require-cuda` 中实际模型 CUDA 前向／反向通过为准；仅 `torch.cuda.is_available()` 返回真不算通过。资料见 `docs/SOURCES.md`。

## 原版模拟器关卡

```bash
python scripts/fetch_engine.py
python scripts/build_native.py --jobs 4
python -m pytest -q tests/test_native.py
python scripts/benchmark.py --backend lightspeed_pilot --output runs/native_benchmark.json
```

首次下载时解析上游 `master` 为完整 commit，并写入 `engine_lock.json`；之后复用锁，不自动更新。**发布包没有已验证的预置上游 SHA**。接手 AI 必须审核实际解析版本、修复 API 差异并记录修改。构建失败是待解决的开发任务，不可改成静默回退 reference。

本版 native 范围：铁甲战士、Cultist／Jaw Worm、21 种卡牌（含打击／防御及进阶诅咒）、起始 Burning Blood、无药水、普通出牌阶段。只生成 Act 1 / floor 1 的受控战斗夹具。它不是整局自然分布，也不是全 A20 战斗覆盖。完整清单在 `docs/04_NATIVE.md`。

## 首轮原版训练

完成 native 编译／基本测试，先做受控模拟器实验；原版游戏一致性未通过时，结果必须标注“未认证模拟器 pilot”。

```bash
python scripts/run_iteration.py \
  --output runs/native_i0 \
  --config configs/native_pilot.json \
  --train-episodes 128 --val-episodes 16 --eval-episodes 32 \
  --workers 2 --device cuda
```

脚本只运行一轮有上限实验，不自动晋级、无限重跑或使用最终测试集。后续迭代用上轮模型指导搜索，保留旧数据：

```bash
python scripts/run_iteration.py \
  --output runs/native_i1 \
  --config configs/native_pilot.json \
  --iteration 1 --checkpoint runs/native_i0/model/best.pt \
  --replay runs/native_i0/train \
  --train-episodes 256 --val-episodes 32 --eval-episodes 128 \
  --workers 2 --device cuda
```

同一系列必须保持模型结构一致；切换 128 维与 192 维配置后，旧 checkpoint 不能直接 warm-start。训练恢复用 `--resume`，新数据迭代用 `--init-checkpoint`，两者不要混用。完整命令见 `docs/03_RUNBOOK.md`。

## 5070 配置

| 配置 | 用途 | 网络 | 微批次 × 累积 |
|---|---|---|---|
| `smoke.json` | 工程验证 | 48 维、1 层、4 头 | 4 × 1 |
| `native_pilot.json` | 第一次原版 pilot | 128 维、4 层、4 头 | 16 × 2 |
| `rtx5070_8gb.json` | 检测到较小显存时的候选 | 128 维、4 层、4 头 | 16 × 8 |
| `rtx5070_12gb.json` | 检测到较大显存时的候选 | 192 维、4 层、6 头 | 32 × 4 |

这些是**启动参数，不是已经实测的显存适配保证**。doctor 检查真实显存，不从“5070”名字推断容量。先做目标批次的短训练，记录峰值；OOM 时减半微批次、增加累积，保留相同有效批次。CPU 搜索多进程和 GPU 学习分阶段运行，首版没有分布式集群或跨进程 GPU 推理服务。

## 目录

```text
AGENTS.md                  接手 AI 的硬约束和执行顺序
HANDOFF_PROMPT_zh.md        可直接复制的委托任务
configs/                   smoke、native pilot、8GB/12GB 配置
src/stsai/                 环境、协议、搜索、模型、采集、训练、评测、控制桥
native/                    C++17 / pybind11 原版接入候选
scripts/                   安装、锁定上游、构建、smoke、迭代、基准、差分比较
requirements/              建议依赖；目标执行后记录 target-resolved.txt
tests/                     Python 与可选 native 测试
reports/                   本次真实本地验证证据
docs/                      验收、架构、公平性、运行、原版接入、扩展、来源
```

## 成功是什么

先证明 **G0 工程闭环 → G1 5070 可运行 → G2 native pilot 可复现 → G3 指定范围原版一致 → G4 战斗强度提升 → G5 扩展覆盖**。达到 G0 不等于达到 G3；模拟器通关不等于人类比较；低交叉熵不等于更会打。没有严谨评测，不使用“超人类”描述。

源码采用 MIT；上游、游戏与 Mod 的版权和安装前提单独处理。项目包不包含游戏本体、存档、上游源码或显卡驱动。
