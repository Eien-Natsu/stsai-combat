> 开发技术参考，来源固定为 `d2e1f0f1449e880af21912b17687d9527dfc49f6`；内容描述开发实现而非当前 main 的旧运行代码。执行权限/准确代码基线只见根 PROJECT_MAINLINE.md 与 NEXT_ACTIONS.md。
> [原参考文件](https://github.com/Eien-Natsu/stsai-combat/blob/d2e1f0f1449e880af21912b17687d9527dfc49f6/docs/03_RUNBOOK.md)。

# 技术参考：环境与命令入口

本页不是按顺序执行的工单，也不授权训练/采集/盲测。当前只执行 [NEXT_ACTIONS.md](../NEXT_ACTIONS.md)，目标与限制见 [主线](../PROJECT_MAINLINE.md)。

## 环境

S2 历史环境见 `reports/s2_commands_and_limits.md` 与 `requirements/target-resolved.txt`，不是当前机器已经配置好的保证。Python/编译器/CUDA wheel 应从实际执行环境记录；Windows 全局 Python 不应代替项目虚拟环境。
安装限制在获准项目环境；不自动改驱动、重启或装系统编译器。读取到 RTX 5070 不等于正式模型 CUDA 前后向/显存验收通过。OOM、非有限损失、非法动作必须停止并留证，不静默改后端。

## 入口索引（阅读源码后按当轮指令运行）

| 入口 | 作用/前提 |
| --- | --- |
| `python -m stsai doctor` | 环境与实际模型自检；需匹配解释器与输出路径；不自动给所有 G1 证据。 |
| `scripts/fetch_engine.py` / `scripts/build_native.py` | 已存在 engine_lock 时复用锁定上游与补丁，不自动升级；构建失败不回退 reference。 |
| `review/run_review.py` | 离线复核编排，参数/前置与真实状态见 [review/README.md](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/review/README.md)。 |
| `review/recompute_s2.py` | 从完整 S2 包的逐场记录独立复算，不从汇总反推原始对局。 |
| `scripts/smoke.py` | 工程收集/训练/重载/评测；会执行优化，不可在“零训练”的 S2R 中顺手运行。 |
| `scripts/s2_*` | 已完成 S2 的采集/训练/统计工具，许多依赖原执行机产物；不是当前待执行清单。 |
| `scripts/run_iteration.py` / `src/stsai/cli.py` | 通用迭代、train/evaluate/mine/bridge 的实现参考；存在入口不代表当轮获准。 |

## 保存、恢复与故障

每轮使用独立 output 与来源清单，不覆盖旧日志/模型。训练恢复先核对数据指纹、结构/语义与优化上限；`--resume` 与 `--init-checkpoint` 不混用；单纯改数据目录不能假装连续恢复。
CPU 搜索和 GPU 学习分阶段；不要让每个 worker 各自建大 GPU 副本。微批次/累积、CPU 线程和 worker 都要在本轮预算中明确，不以默认配置悄悄扩大资源。
保留完整 stdout/stderr、cwd、退出码、时间、实际设备与依赖；FAIL、NOT_RUN、TIMEOUT、SKIP 不得压成一个 pass。原生 Windows、WSL/Linux、不同 GCC 版本分开报告。
最终盲测入口仍在代码中，但本页不提供可误执行的首轮训练/最终测试命令链。是否创建最终 manifest、是否开实机执行，以主线及当轮显式授权为准。
