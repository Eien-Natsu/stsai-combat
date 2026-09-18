# Review：<task_id>
<!-- 新 Chat 填写，保存到 handoffs/<task_id>/REVIEW.md；不得用聊天摘要替代源码/证据审查。 -->
## Reviewed Snapshot
- Repo / Task ID / Request ID / Mainline version:
- Reviewer session ID（新的 Chat；自定义 ID 须注明）:
- Reviewed executor session ID / Source plan commit:
- Implementation PR / Implementation SHA / Reviewed HEAD / BASE:
- Handoff SHA256 / Execution record（固定提交下的路径）:
- Trigger: manual-chat
## Review
- Verdict: needs-work / accepted / blocked
- Critical / Important / Minor：路径、行号、条件、影响、证据；确定缺陷与疑点分开。
## Verification
- 实际读过的代码/范围；观察到的 CI 链接及被测 SHA。
- 亲自运行的命令、环境、输出、退出码；仅阅读的历史报告；未验证项。
- Budget scope ID / 原授权 / 进入时已用 / 本次实用 / 累计 / 剩余。
## 下一步决定
- 本任务结论、候选问题、选定的一个 next_task_id 及理由；不自行增加资源。
- 完整执行指令只写 NEXT_ACTIONS.md；无可执行下一步则 WAITING_OWNER / STOP。
- Completion criteria：下一次交接的可检查条件；需要所有者授权的事项。
## Publication / Session handoff
- 文档规划分支 / 目标分支；实现基线必须是本次已审的明确 SHA。
- 本文件与 NEXT_ACTIONS 同次提交；最终 plan_commit 在 commit 后写 PR/发布回复，不能自引用。
- 内容推送后回读核验；失败写 PLAN_NOT_PUBLISHED，不让新 agent 依聊天草稿运行。
- Next role: NEW_LOCAL_AGENT_SESSION（仅计划为 READY 且 owner 指定时）；否则 OWNER。
- Session disposition: ENDED_AFTER_PUBLICATION_OR_BLOCKED
- 发布前复查快照；stale/blocked 不写 status=complete 成功标记。
