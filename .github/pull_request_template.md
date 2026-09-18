## Goal / Role
<!-- 规则只见 PROJECT_MAINLINE.md §7：新 Chat review/规划 → 新 agent session 单步实施。 -->
- PR role: implementation / planning / protocol-bootstrap
- Task ID / Mainline version:
- 本任务唯一目标 / NEXT_ACTIONS 来源:
## Snapshot / Session
- Executor session ID（实施 PR） / Reviewer session ID（规划 PR）:
- Plan commit（领取时的完整 SHA） / Source review:
- Execution start / Implementation SHA / 最终 HEAD SHA（完整）:
- Target branch / BASE SHA / 依赖 PR:
- Request ID / Resume from / Re-review reason:
- Trigger: manual-chat
## Repository handoff
- 实施：handoffs/<task_id>/EXECUTION.md（固定 HEAD 下的路径）。
- 规划：handoffs/<task_id>/REVIEW.md + NEXT_ACTIONS.md；最终 plan_commit 发布后回读验证。
- 首次规则初始化写 protocol-bootstrap，不伪造独立 review 或新执行 session。
## Evidence / Budget
- 实际改动、验证命令/环境/退出码、原始日志/收据/附件大小与 SHA256。
- Budget scope ID / 原授权上限 / 进入时已用 / 本次实用 / 累计 / 剩余。
- FAIL / NOT_RUN / TIMEOUT / SKIP、已知问题与未验证项；不要用历史结果替代本轮。
## Handoff checklist
- [ ] 已按固定 plan_commit 阅读规则/任务/来源 review，角色和单步范围明确。
- [ ] 本次使用新的 Chat 或本地 agent session；恢复任务明确记载旧交接与消耗。
- [ ] 全部提交已 push，HEAD/BASE/依赖核验，未合并或直接写目标主线。
- [ ] 持久交接、证据和预算齐全；会话更换不重置上限。
- [ ] 交接后结束本 session，下一角色必须新建 session；不原地等待下一步。
- [ ] ready/blocked 状态准确且其他标签保留；标签不是自动唤醒证明。
<!-- 规划没有成功写回仓库不能标作已下发；纯规则 bootstrap 对不适用项明确标 N/A。 -->
