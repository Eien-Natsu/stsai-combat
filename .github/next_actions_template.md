# NEXT_ACTIONS — ONE_TASK

Task ID；状态 READY/WAITING_OWNER/STOP；owner 授权来源；source REVIEW 固定路径/提交；下一接收角色。
Plan/control commit 在领取时固定；code_base_commit、target branch、依赖 PR 必须分别明确。
你是无前文的新本地 agent；接收你的交付的是无前文且仅看 GitHub repo 的新 Chat。
## Context and inputs
必要背景、已验证/未验证状态、输入路径/固定来源/hash、前任务遗留；不得写“按上次讨论”。
## One objective
唯一目标；范围内外；允许改动的文件；不改动的实现/规则/验收。
## Steps
依赖顺序、可运行命令或待实现入口、环境、失败处理；无本机访问的 reviewer 不能代替 executor 运行。
## Evidence for the NEXT reviewer
| 审查问题 | agent 必须执行的检查 | repo 文本路径/必要字段 | 判定与缺证据处理 |
| --- | --- | --- | --- |
| 必填 | 必填 | 必填 | 必填 |
EXECUTION/EVIDENCE_INDEX/files.json/budget.json/publish_receipt 必须交付；只给 summary、二进制或本机路径不合格。
## Budget and gates
budget_scope_id、父范围/累计剩余、次数/时长/worker/内存；失败/超时也消耗；换会话不清零。
## Acceptance and stop
可检查的完成条件；不能安全执行的前置；必要项缺失就 BLOCKED。
## Publish and exit
只用获授权分支；push 后远端回读；状态 DELIVERED_WAITING_REVIEW/BLOCKED；发 PR/最终 SHA，下一角色 NEW_CHAT_REVIEWER。
结束本 session，不等下一计划再继续。
