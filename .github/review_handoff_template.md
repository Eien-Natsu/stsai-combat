# REVIEW — TASK_ID

你是全新 Chat，无前文；下一 reviewer 也是全新 Chat，执行你指示的也是全新 agent Chat/session。
只能依赖固定 GitHub repo 内容；缺信息须让下一新 agent 执行/提供，不能依赖执行机或旧会话补记忆。
## Snapshot and scope
reviewer_session_id/source；task/request；control/历史 plan/code base/HEAD/BASE；handoff 摘要；实际读过的证据范围。
## Review
结论 needs-work / accepted / EVIDENCE_BLOCKED / WAITING_OWNER；确定缺陷与疑点分开，文件/行号/条件/影响/证据。
## Verification
逐项列已读代码/原始记录；agent 声称执行与 reviewer 亲自验证分开；未读取/二进制/缺失项与结论边界。
## Budget
进入时已用、当前用量、累计/剩余、来源；不清零、不新增实验授权。
## Next single task
选定一步与理由；其他候选非执行许可。范围/输入/文件/步骤/命令/预算/验收/停止条件必须完整。
## What the NEXT reviewer will need
审查问题 → agent 必须执行的检查 → 推入 repo 的文本证据路径与字段 → 判定/缺失时处理。
不能只给实现目标而遗漏审查所需材料；不把下次 reviewer 能解压/加载模型/访问本机当条件。
## Publication and exit
在独立规划分支保存本 REVIEW，更新 NEXT_ACTIONS 与状态索引；提交/推送/远端回读，实际 plan commit 在外部交接指针提供。
无写权限则 PLAN_NOT_PUBLISHED，向 owner 提供新 PUBLISH_ONLY session 的原样落库指令；发布确认后再开新 executor。
没有安全可执行任务则 WAITING_OWNER/STOP；不能残留旧 READY。计划发布后结束当前 Chat。
