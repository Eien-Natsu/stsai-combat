# 本地验证记录

日期：2026-09-16。以下是实际执行记录，不是目标机的预期成绩。

## 结果

**71 项测试通过，0 失败，1 个 native 测试模块因扩展未构建而跳过。** 原始输出见 `pytest.txt`，JUnit 见 `pytest.xml`。跳过不等于通过。

本地环境：Python 3.13.5、PyTorch 2.10.0+cpu、NumPy 2.3.5、pytest 9.0.2，Linux，未检测到 CUDA GPU。目标安装脚本选择 PyTorch 2.9.1+cu128；这一具体目标组合尚未在本地验证，不能混为一谈。

端到端 smoke：参考环境 4 场训练战斗产生 41 条决策记录，2 场验证战斗产生 18 条记录；模型实际完成 8 次优化更新，保存并重新加载；启发式／搜索／纯网络／混合搜索各评测 4 个场景，共执行 16 场评测；整理 12 条失败／价值差异候选病例。

这组数据很小，而且来自工程参考环境。它仅证明训练闭环能运行，**不证明模型比启发式强，不代表原版胜率，更不代表超人类**。无需把 smoke 训练出的权重当成正式模型，本包有意不附带该权重。

## 已执行命令

```bash
PYTHONPATH=src python -m pytest -q --disable-warnings --junitxml=reports/pytest.xml
PYTHONPATH=src python scripts/smoke.py --output /mnt/data/sts_work/smoke_final --device cpu
PYTHONPATH=src python -m stsai doctor --output reports/local_doctor.json
PYTHONPATH=src python scripts/benchmark.py --transitions 200 --simulations 16 --output reports/reference_benchmark.json
```

报告内 `/mnt/data/...` 是交付环境路径，不是用户电脑路径。目标机应使用新的 `runs/` 目录执行，不照搬本地绝对路径。

## 尚未执行

真实 RTX 5070 GPU 前向／反向和目标微批次训练；native C++ 编译与链接；原游戏轨迹差分；CommunicationMod 真实控制；完整卡池／药水／遗物／敌人覆盖；人类强度比较。

源码中的 native 候选按检索的上游 API 编写，但没有编译过，可能需要目标 AI 修复兼容和运行时问题。代码存在、测试模块存在都不能替代实际执行。

## 文件索引

`delivery_status.json` 是机器可读状态；`local_doctor.json` 是真实环境检测；`local_smoke_report.json` 汇总训练与评测；`local_smoke_stdout.txt` 保存完整控制台输出；`local_eval_episodes.jsonl` 是每场评测；`local_training_metrics.jsonl` 是优化日志。`reference_benchmark.json` 只对应本地单进程参考环境，不可外推为 5070 或 native 性能。
