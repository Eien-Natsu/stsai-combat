# STSAI Combat — 从这里开始新会话

**每轮是全新 reviewer Chat → 全新本地 agent Chat/session → 全新 reviewer Chat。**
双方均无前文；reviewer 只能依赖已推送到本 GitHub repo 的可读信息，不能依赖执行机或聊天附件。

| 入口 | 作用 |
| --- | --- |
| [PROJECT_MAINLINE.md](PROJECT_MAINLINE.md) | 唯一目标、验收、会话/证据/权限规则（版本 3） |
| [NEXT_ACTIONS.md](NEXT_ACTIONS.md) | 当前唯一单步任务与下一 reviewer 必需材料 |
| [SESSION_STATE.json](SESSION_STATE.json) | 本次初始化的任务/实现/交付指针；不是第二份规则 |
| [handoffs/README.md](handoffs/README.md) | 固定提交的历史交接索引 |

新 Chat：读取所有者给的待审 PR/完整提交及 plan/control 指针，按主线第 7 节审查和发布下一步。
新本地 agent：读取所有者指定的 plan commit，按其中任务执行、提交可读证据并结束。
没有必要指针、已有同任务在运行或预算不明时先核实，不从旧 READY 重新跑实验。

## main 与开发实现的过渡

main 本次仅提升控制文档。其运行代码仍为初交付 e2e58d6，不代表 S2/S2R 实现已验收或合并。
上一轮实施是 [PR #3](https://github.com/Eien-Natsu/stsai-combat/pull/3)，固定 HEAD e0fc584d19afe58ac10b65c93c7bcc75a2630f05；已交付 BLOCKED，未合并。
后续实际代码基线按 NEXT_ACTIONS 指定，不能用旧 main 重做 S2R。旧 PR #1/#2 是历史方案来源，不再作为并行活动规则。
当前本地写能力用于一次性协议初始化；未来 reviewer 不应假定同样权限。标签/设备连接没有自动启动新 Chat 的效果。
