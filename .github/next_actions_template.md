# 当前唯一任务：<task_id>
<!-- reviewer 选择一个下一步并用本模板更新根目录 NEXT_ACTIONS.md；不要创建第二份活动计划。 -->
## 领取信息
- Task ID（新且唯一）:
- Status: READY / WAITING_OWNER / STOP
- Source review：handoffs/<previous_task>/REVIEW.md；reviewer session ID；已审 HEAD。
- Mainline version / Implementation base SHA / Target branch / 依赖 PR:
- Plan commit：最终提交后由发布回复提供，领取时核验；不在此自引用。
- Execution mode: NEW_LOCAL_AGENT_SESSION_ONCE
## 唯一目标与边界
- 一个有界可验收目标、前置条件、允许改动的文件、明确不做的内容。
## 实施步骤
1. 读取指定主线/来源 review/输入，确认无人重复执行及预算余量。
2. 在独立工作区完成本目标；必要内部子步骤逐项写，不能附带多个后续实验。
3. 验证、留证据、提交交接并结束。
## 预算继承
- Budget scope ID / owner 授权来源 / 父范围上限:
- 既有累计 / 本任务分配 / reviewer 核验预留 / 剩余:
- 编译/worker/线程、次数、单步超时、总时长及例外：全部明确。
- 未知消耗不按 0；换 session、task/request ID 不能刷新父预算。
## 验收与停止
- 每项验收命令和所需证据；失败、缺输入、超时或超范围的停止条件。
- 需要新增预算/语义修改时先 BLOCKED，不先运行再补批准。
## 必须交付
- handoffs/<task_id>/EXECUTION.md、实际实现与证据、预算账本及 PR。
- 附件存放位置、来源/大小/SHA256；失败/未运行项如实保留。
- Next role: NEW_CHAT_REVIEWER；交接后结束，不在原 session 领取下一计划。
