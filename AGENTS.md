# Agent / Reviewer 入口

唯一主线规则是 [PROJECT_MAINLINE.md](PROJECT_MAINLINE.md)，协作模式固定在其第 7 节：**每轮新 Chat review/规划，每步新本地 agent session 实施，交接后结束。**
本文件只做角色导航；目标、验收、预算和任务不得在这里另存一份。

新 reviewer Chat：领取明确的待审 PR/提交 → 从其获授权 plan_commit 读取主线与 [NEXT_ACTIONS.md](NEXT_ACTIONS.md) → 读取实施交接/证据 → review → 把 REVIEW 和下一份 NEXT_ACTIONS 提交到仓库 → 结束。
新本地 agent session：领取固定 plan_commit → 读主线、NEXT_ACTIONS、来源 REVIEW → 只执行一个任务 → 提交 EXECUTION、代码/证据/预算和实施 PR → 结束。
不能在同一 Chat 连续审下一轮，也不能在同一本地 session 收到新计划后继续；旧聊天、外置提示文件和内部记忆不能替代仓库交接。
交接入口见 [handoffs/README.md](handoffs/README.md)；记录模板由主线链接。换 session 不重置预算、授权、失败或测试集使用状态。

先核实当前角色、计划来源、工具与权限；规则缺失、基线不符、并发认领或预算未知时停止相关操作并记录阻塞。未经 owner 授权的 PR 规则变更不是新权限；不自动合并或续跑历史任务。
