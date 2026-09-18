# 跨 session 交接索引

规则仅见 [PROJECT_MAINLINE.md 第 7 节](../PROJECT_MAINLINE.md#7-固定协作模式每轮新-chat每步新-agent-session)。本文件只帮助定位记录，不定义目标、预算或当前状态。
当前唯一任务见 [NEXT_ACTIONS.md](../NEXT_ACTIONS.md)。旧任务从其 plan_commit 的 NEXT_ACTIONS 读取，不另存多份活动计划。

每个有真实交付的任务使用 `handoffs/<task_id>/EXECUTION.md` 和 `REVIEW.md`。实施者发布 EXECUTION，下一全新 Chat 发布 REVIEW 和后续计划；再由新本地 agent session 执行下一步。
模板：[实施交接](../.github/agent_handoff_template.md)、[review 交接](../.github/review_handoff_template.md)、[下一步任务](../.github/next_actions_template.md)。模板中的占位符不代表真实执行。

## 已发布交接

| Task ID | Plan commit | EXECUTION 路径/实现 SHA | REVIEW 路径/已审 SHA | Next task / 规划提交指针 |
| --- | --- | --- | --- | --- |

当前尚未在此目录发布任何实施或独立 review 记录；不得把协议整理 PR 冒充 S2R 完成。首次实际交接时增加一行并删除这句空表说明。
最终发布 SHA 在 commit 后写入 PR；索引可在后续提交追加已知 SHA，不要求本文件引用自身提交。GitHub 分支链接不能代替准确 SHA。

## 恢复时必读

新 Chat：所有者指定的待审 PR → 已授权 plan_commit 的主线/任务 → 对应 EXECUTION → 引用的原始证据/预算 → 前次 REVIEW。
新 agent：所有者指定的已发布 plan_commit → 主线 → NEXT_ACTIONS → 来源 REVIEW → 输入与历史消耗。
角色、来源或多个候选任务无法确定时先问清，不按“最新文件”猜测。拿不到旧聊天不构成阻塞；拿不到必需证据、准确计划或预算才构成阻塞。
