# 实施交接：<task_id>
<!-- 复制到 handoffs/<task_id>/EXECUTION.md，填写真实值。模板不是新任务/预算。 -->
## 身份与计划
- Task ID / Request ID:
- Executor session ID（新 session；自定义 ID 须注明）:
- Resume from（恢复时引用旧交接，否则 None）:
- Plan commit / Mainline version:
- Source review（路径及完整 SHA；初始任务写 owner bootstrap）:
- Execution start SHA / Implementation SHA:
- Target branch / Base SHA / Implementation PR:
<!-- 最终 handoff HEAD 在 commit 后写 PR，不在本文件自引用。 -->
## 已完成与证据
- 按任务子步骤列实际变更、文件、命令、环境/线程、退出码、证据路径。
- PASS / FAIL / NOT_RUN / TIMEOUT / SKIP 分开；每项说明是新执行还是复用历史。
## 产物与来源
- 每项：路径或可访问附件、来源提交/旧 manifest、大小、SHA256、输入/输出用途。
- 原始日志、JUnit、失败证据及 source/plan/input hash 的位置。
## 预算账本
- Budget scope ID / 原授权来源与上限:
- 进入时累计已用（含其他 agent / reviewer、失败、超时）:
- 本 session 实际调用次数/运行时长/训练与评测用量:
- 新累计 / 剩余 / 不确定项（未知不可按 0 计算）:
## 阻塞与交接
- 结果：READY_FOR_REVIEW 或 BLOCKED；原因与需要 reviewer 决定的事项。
- 尚未执行、根因不确定、不可访问材料；不得自行下发下一步。
- Next role: NEW_CHAT_REVIEWER
- Session disposition: ENDED_AFTER_HANDOFF（发布后结束，不等新计划继续）
- 冻结的 PR/head/request 指针、可供新 Chat 从零读取的证据顺序。
