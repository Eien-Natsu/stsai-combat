# 技术参考：离线复核入口（S1R / S2）

目标/权限见 [主线](../PROJECT_MAINLINE.md)，下一轮输入修复与执行预算见 [NEXT_ACTIONS](../NEXT_ACTIONS.md)。本页不声明干净 checkout 已有完整 review 包。

## checkout 与 package 是两种布局

仓库已有 `native/native_sources.tar.gz` 和 manifest；历史 ZIP 则将其放在包根。S2 ZIP 还应有代表模型、完整评测和数据组成文件；当前 checkout 缺少其中 7 个打包输入，先按 NEXT_ACTIONS 核对来源，不凭空运行采集/训练补齐。
`--repo` 指代码 checkout，`--package` 指含 MANIFEST.sha256 的已验证解包目录，`--sources` 指对应 PRE_PATCH 归档，`--model` 指该轮声明的代表推理权重；这些位置不能互换。

## 必需顺序

附件完整性 → PRE_PATCH + 声明补丁 → 离线构建 → 真实 import/build_info → 用已验证源码重建意图表 → 全量 pytest/native 零 skip → 公开反事实重放 → 声明模型的 12 条 smoke。
`run_review.py` 当前有 `--repo`、`--sources`、`--package`、`--model`、`--work`、`--receipt`、`--timeout`；缺模型时其 smoke 可被当成可选步骤跳过，因此训练轮验收必须显式要求代表模型，不用省略参数获得通过。
编译的 `--jobs` 目前仅底层 `offline_native_build.py` 接收；NEXT_ACTIONS 要求在编排入口增加转发与测试。未实现前不要声称顶层已支持。

## 结果层级

FAIL 是执行后失败；NOT_RUN 是必需条件缺失；TIMEOUT 是运行超过预算；SKIP 不是 PASS。必需步骤的后三种情况均不得作为完整复核成功。
原有模块、旧 build 或历史 true/false 不替代本轮运行；全流程在隔离测试环境执行，不挂载写凭据。CPU 复核不等于 GPU 重训、GCC 14 测试或原游戏差分。

| 脚本 | 职责 |
| --- | --- |
| `run_review.py` | 编排、收据与退出码 |
| `offline_native_build.py` | 快照校验、补丁、冷构建、import 信息 |
| `counterfactual_replay.py` | 公开轨迹与 louse 反事实 |
| `model_smoke.py` | 明确指定的代表权重与公开观测推理 |
| `recompute_s2.py` | 从完整 S2 逐场数据独立复算；运行前仍需检查记录完整性 |

本页不提供旧版的自动续训/盲测链，也不表示尚待实现的输入预检已经可运行。
