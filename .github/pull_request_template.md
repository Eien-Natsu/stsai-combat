## Goal

<!-- 本 PR 的目标、当前 A–F 阶段、涉及的 G0–G5 验收关卡。 -->

## Agent handoff

- Agent run ID:
- Review request ID:
- HEAD SHA:
- Previous review / plan:
- Re-review reason: N/A
- Trigger mode: manual-chat / verified-event

<!-- SHA 填完整 GitHub PR HEAD；request ID 使用字母、数字、点、下划线或连字符。同 SHA 复审须说明原因。人工 PR 可将此节标为 N/A，且不加 agent-ready-for-review。 -->

## Completed

<!-- 本轮实际完成的改动；与上一轮计划编号对应。 -->

## Validation

| 命令 / 检查 | 环境与 backend | 实际结果 | 日志 / CI / 报告链接 |
| --- | --- | --- | --- |
| | | 通过 / 失败 / skip / 未执行 | |

<!-- 区分 CPU smoke、native、CUDA 和原游戏差分；skip 不是 pass。适用时更新 reports/target_status.md。 -->

## Known issues / uncertainties

<!-- 没有已知问题写 None；尚未验证的内容必须列出。 -->

## Out of scope

<!-- 明确本轮没有实现/验证的能力，不能借此降低原有验收标准。 -->

## Handoff checklist

- [ ] 本轮预期提交已全部 push，以上 SHA 与 GitHub HEAD 一致。
- [ ] 相关验证已执行，失败、skip、未执行和证据均如实记录。
- [ ] 已阅读 AGENTS.md 和 .github/agent-review-protocol.md。
- [ ] PR 打开且非 draft，目标 main，来自本仓库分支。
- [ ] 已注明由所有者在 Chat 发起审查，或提供已验收事件任务的真实标识；没有把标签当成送达证明。
- [ ] 已清理旧状态标签；交接后冻结本轮代码和 handoff。

最后添加 `agent-ready-for-review`。仅在已验收的事件订阅支持该动作时自动触发审查；普通 push 不代表完成交接。
