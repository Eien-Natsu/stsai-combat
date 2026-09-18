## Role / Task
<!-- IMPLEMENTATION / PLAN / PUBLISH_ONLY / PROTOCOL_BOOTSTRAP；接收者是全新 Chat，不能假定它有前文或本机权限。 -->
Task ID / request ID / executor_session_id / reviewer_session_id（适用时）：
Plan/control commit（完整 SHA）：
Code base / 最终 HEAD / PR BASE（分开）：
依赖 PR 与本任务增量范围：

## Goal / Source
<!-- 唯一目标、来源 NEXT_ACTIONS/REVIEW 的固定路径；不引用旧聊天作为必要输入。 -->

## Handoff and evidence
EXECUTION / REVIEW 路径：
EVIDENCE_INDEX / files.json / budget.json / publish_receipt 路径：
<!-- 审查所需内容必须已 push 为可读文本。模型/ZIP/本机路径/hash 本身不代替内容证据。 -->

## Verification / limits
<!-- driver SHA、实际被测代码 SHA、环境/命令/退出码；本轮执行、历史记录、未验证分开。 -->
失败/skip/timeout/缺失/待 reviewer 决定：
旧预算已用/本次/累计/剩余：

## Publication / next role
- [ ] push 后从 GitHub 固定提交回读必需文本，未追踪或压缩包独占内容已列为缺项。
- [ ] 规则、任务、实现与证据 SHA 分清；没有用旧版本测试替代新实现验证。
- [ ] 没有合并/强推/扩大实验预算/泄露凭据，未把缺项写成通过。
- [ ] 状态已从 READY 改为交付或 BLOCKED；下一角色为全新 Chat，发布后结束 session。
<!-- 计划 PR 则给真实已发布 plan commit 和下一角色 NEW_LOCAL_AGENT；没有写权限时不得宣称已发布。 -->
