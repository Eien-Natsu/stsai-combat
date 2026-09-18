# EXECUTION — TASK_ID

模板不是执行记录；实际交付须填写所有字段，无资料写 unknown/NOT_AVAILABLE 及原因。
你是全新本地 session；接收者必定是只能读 GitHub repo 的全新 reviewer Chat。

## Snapshot
Task / request / executor_session_id；session ID 来源；plan/control commit；code base；实现代码 SHA；目标分支/依赖。
最终交接 HEAD 在 commit 后写 PR，不在文件内自引用。
## Goal and context
唯一目标、来源计划/REVIEW 的固定提交和路径；必要输入和已知边界，不引用旧聊天。
## Execution
每步命令、cwd、环境、driver 和被测代码 SHA、输入 hash、起止、退出码、完整日志路径。
实际执行/仅转录历史记录/源码推断/未验证分开；所有失败、skip、timeout 保留。
## Claim → evidence
逐项回答任务中的审查问题，链接 EVIDENCE_INDEX.md 与 files.json；本机路径/ZIP 文件名不算可读交付。
## Budget
budget_scope_id；授权上限；进入时已用；本 session 用量；累计/剩余与证据路径。unknown 不填 0。
## Availability and limitations
NOT_AVAILABLE、敏感内容未发布、二进制不可读及其对结论的影响；不通过摘要/hash 假称完整验证。
## Publication
push 的 payload SHA；publish_receipt.json；远端逐文件回读/hash/分页完整性；最终 HEAD 的载荷一致性。
## Exit
DELIVERED_WAITING_REVIEW 或 BLOCKED；待决定问题；下一角色 NEW_CHAT_REVIEWER。
结束当前 session；不等待下一步后继续执行，不代替 reviewer 发布通过。
