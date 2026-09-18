# ChatGPT reviewer：运行方式与启用状态

## 当前配置（2026-09-18）

目标仓库：`Eien-Natsu/stsai-combat`。本 PR 固定协作协议，不实现游戏功能。

- 当前执行路径：普通 Chat → 已授权 Remote Desktop Commander → 本机 Git / GitHub CLI。
- 认证使用本机已有 Git/gh 凭据，不读取或输出 SSH 私钥/token；不更改全局 Git、SSH 或 app 权限。
- 协议、模板由独立配置分支提交；创建 PR 不等于合入 main。最终 commit、PR、写回验证见配置 PR 的实际记录。
- 状态标签按下一节初始化；是否成功以 GitHub 标签列表和配置 PR 记录为准。
- 方案 A 的事件任务：**未创建 / 未验收**；Task ID：无。
- 期望事件：`pull_request / labeled`，标签 `agent-ready-for-review`；当前没有已注册的接收端。
- 未部署定时轮询、自建公网 webhook、GitHub Actions reviewer、Codex 自动化、API reviewer 或本地守护进程。

**现在可在 Chat 发起单次操作；还不能宣称“agent 贴标签后 ChatGPT 会自动运行”。** 本地设备在线只提供工具访问，不等于拥有事件调度。

## 仓库标签

按协议使用 `agent-ready-for-review`、`agent-reviewing`、`agent-needs-work`、`agent-review-approved`、`agent-blocked`。同一 PR 只保留其中一个状态，保留其他普通标签。

初始化时先列出现有标签，仅创建缺少的标签，不覆盖既有配置：

```sh
gh label list --repo Eien-Natsu/stsai-combat --limit 100
# 以下命令仅对不存在的对应标签执行：
gh label create agent-ready-for-review --repo Eien-Natsu/stsai-combat --color 0E8A16 --description 'Agent handoff awaiting review'
gh label create agent-reviewing --repo Eien-Natsu/stsai-combat --color 1D76DB --description 'Review in progress for a fixed snapshot'
gh label create agent-needs-work --repo Eien-Natsu/stsai-combat --color FBCA04 --description 'Execute the matching Next Agent Plan'
gh label create agent-review-approved --repo Eien-Natsu/stsai-combat --color 0E8A16 --description 'No review blockers; owner decides merge'
gh label create agent-blocked --repo Eien-Natsu/stsai-combat --color B60205 --description 'Human input, permission or evidence required'
```

配置 PR 使用 `documentation` 标签，不加 ready 标签假装测试了事件触发，也不将配置自检作为独立代码审查的通过证明。

## 当前可用：Chat 发起单轮审查

所有者确认并合并本协议后，实施者完成 PR handoff、验证并贴 ready，随后由所有者在 Chat 明确发起本轮审查。例如：

```text
使用 Remote Desktop Commander 审查 Eien-Natsu/stsai-combat 的 PR #<number>。
本轮由我手动发起，不创建定时任务，不调用 Codex 或外部模型 API。
读取 main/base 版本的 AGENTS.md 和 .github/agent-review-protocol.md。
使用独立 reviewer 工作副本，记录并核对 HEAD/base/request ID/handoff 摘要。
只做静态审查和读取 CI 证据；未另行授权不执行 PR 代码或本地测试。
将完整 Review、Verification、Next Agent Plan、Completion Criteria 和快照
写回该 PR，并按结果更新状态标签；不改实现代码、不合并、不启动训练。
```

这条路径需要 Chat 当前可调用该 app，且授权设备在线、GitHub 认证有效。没有连接或写操作待审批时应停止并报告，不能默默把失败说成成功。

reviewer 工作副本不要与实施者共用。开始前检查 Git 状态；已有改动时停止，不 reset/clean/stash。可 fetch 获取版本，但只审查记录的 SHA，不直接 pull 改变实施者分支。

## 方案 A：尚缺的事件接收端

GitHub 的 `pull_request` webhook 与“ChatGPT 已订阅该事件”是两件事。当前 Chat 没有可调用的事件 schema discovery/注册入口；Remote Desktop Commander 也不是已配置的 ChatGPT 唤醒服务。

OpenAI 当前官方说明将原生事件任务的创建入口列为 Work，并要求受支持的活动、账号和授权。本项目当前按所有者要求留在 Chat，不切换 Work/Codex，不假定有可用额度，也不部署另收费的 API reviewer。

后续只有获得所有者批准且存在受支持的接收端时，才配置以下要求；不能凭本文捏造 API 或公网 webhook URL：

```text
Trigger: GitHub pull_request / labeled（须先核实接收端实际 schema 支持）
Condition: repo=Eien-Natsu/stsai-combat, label=agent-ready-for-review,
           PR=open/non-draft, base=main, head=同仓库, 触发者有写权限。
Action: 单 PR 串行认领 → 固定快照 → 审查 → 写回计划 → 更新状态。
Safety: 不合并、不改 main、不 force-push、不启动训练、不放宽权限。
Failure: 无法注册则保持未启用；不以轮询或模拟点击 ChatGPT UI 代替。
```

自动任务能否调用此设备及本机 gh 必须单独验收，不能从交互 Chat 的连接状态推断。实施 agent 如何接收计划和恢复运行也需单独配置；写 PR 评论不会启动已退出的 agent。

## 真正启用的验收条件

1. 记录真实 Task ID/订阅标识、触发条件、权限、reviewer 身份和单 PR 串行保障。
2. 用低风险测试 PR 的真实 ready 标签事件产生任务运行，而非人工在 Chat 发起。
3. 对准确 HEAD/base/handoff 发表 review 和可执行计划，成功更新标签并通知所有者。
4. 重复事件不重复审查；审查中快照变化时旧结果标 stale；CI 未完成、缺机器验证和写入失败均显式暴露。
5. 检查本地 agent 对应轮次的接收/恢复；审批暂停、设备离线等人工步骤如实保留。

验收成功后再经 PR 更新本文件的启用状态和真实证据。不提交凭据、本机个人路径、私密聊天链接或无关用户文件。

## 官方参考

以下资料用于核对接口边界，不构成账号已开通能力的证明（核对日期：2026-09-18）：

- [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-chatgpt-tasks)
- [GitHub webhook events](https://docs.github.com/en/webhooks/webhook-events-and-payloads#pull_request)
- [gh pr create](https://cli.github.com/manual/gh_pr_create)
- [gh label create](https://cli.github.com/manual/gh_label_create)
