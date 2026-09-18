# 所有新会话的入口

唯一规则：[PROJECT_MAINLINE.md](PROJECT_MAINLINE.md)；唯一当前任务：[NEXT_ACTIONS.md](NEXT_ACTIONS.md)。
**reviewer 每次都是全新 Chat；执行计划的本地 agent 也每次都是全新 Chat/session。两边都没有前文。**
Reviewer 仅依赖本 GitHub repo 已推送的代码和可读证据；不要要求它访问本机、旧聊天、未上传 ZIP/权重或上一 session 内存。
每位 reviewer 必须提前要求 agent 执行并提交下一位 reviewer 所需的全部审查材料；每份执行任务必须自包含，让没有背景的新 agent 可以从固定指针开始。
先核对角色、规则/计划提交、实现基线、上次交付与累计预算；不得按“最新”猜任务或因换 session 清零预算。
主线第 7 节规定发布、回读、退出与失败恢复；模板仅规定字段，历史报告不发号施令。材料缺失就阻塞，不臆造通过。
当前 Chat 的本地写/结构初始化例外见主线第 7.7 节，不传递为后续 reviewer 的权限。
