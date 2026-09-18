# 跨会话交接索引

规则只见 [PROJECT_MAINLINE.md](../PROJECT_MAINLINE.md) 第 7 节；当前任务见 [NEXT_ACTIONS.md](../NEXT_ACTIONS.md)。本文件仅索引已知记录，不重新定义目标或预算。
新 reviewer：指定待审 PR → 历史 plan/current control → EXECUTION → EVIDENCE_INDEX → 仓库可读原始证据/预算 → REVIEW/下一步。
新本地 agent：指定 plan commit → 主线/当前任务 → 来源 REVIEW/固定输入 → 自己的新 session 执行和发布。

| 记录 | 来源与状态 | 下一接收者 |
| --- | --- | --- |
| [S2R-REPRO-001](S2R-REPRO-001/INDEX.md) | PR #3/e0fc584；旧计划 4462a7c 已交付 BLOCKED，session 信息旧协议未记录；不是 v3 执行失败 | 等待补齐仓库可读证据后由全新 Chat review |
| [BOOTSTRAP-GITHUB-ONLY](BOOTSTRAP-GITHUB-ONLY/REVIEW.md) | 当前 Chat 的结构初始化与证据可见性核对；不是完整科学 review | GITHUB-HANDOFF-001 的全新本地 session |

每新 task 发布 EXECUTION.md、EVIDENCE_INDEX.md、files.json、budget.json；新 reviewer 发布 REVIEW.md 与下一计划。
最终含交接文件的 SHA 在提交后写 PR；索引在后续提交记录已知 SHA，避免自引用。
状态快照落后于 owner 给的 PR 时，以核实后的固定指针为准，不按最大 PR 编号/最近时间猜测或重复领取。
旧会话不作为必要资料；必要证据缺失要成为下一任务明确补证项。main 控制文件存在不表示开发实现已合并。
