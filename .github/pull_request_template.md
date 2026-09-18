## Goal / 当前执行指令

<!-- 对应 NEXT_ACTIONS.md 的轮次/任务编号；规则只见 PROJECT_MAINLINE.md。 -->

## Handoff

- Agent run ID:
- Review request ID:
- HEAD SHA（完整）:
- Target branch / BASE SHA:
- Mainline version:
- Previous review / plan:
- Re-review reason: N/A
- Trigger: manual-chat（事件订阅未验收前不得填 verified-event）

## Completed / Evidence

<!-- 实际改动、验证命令/环境/退出码、原始证据路径或附件 hash。区分本轮执行与历史记录。 -->

## Not verified / Known issues / Out of scope

<!-- 原游戏、CUDA、native、输入缺失、失败/skip/timeout 逐项如实写；不删掉不利结果。 -->

## Handoff checklist

- [ ] 已读 PROJECT_MAINLINE.md，任务与预算符合当前 NEXT_ACTIONS.md。
- [ ] 全部提交已 push，HEAD 与 GitHub 一致，目标分支获授权。
- [ ] 证据与未验证项齐全；本轮交接后冻结代码及 body。
- [ ] 清理旧协议状态，最后贴 agent-ready-for-review；已知标签本身不保证自动送达。
