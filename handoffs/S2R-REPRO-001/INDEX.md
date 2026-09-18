# S2R 旧协议交付定位（只读迁移记录）

这是当前结构维护者从 GitHub 读取后建立的索引，不是冒写上一位 agent 的 EXECUTION 或对它的验收。
- 实施 PR：[PR #3](https://github.com/Eien-Natsu/stsai-combat/pull/3)，仍 OPEN/unmerged，agent 标记 BLOCKED。
- 固定 HEAD：e0fc584d19afe58ac10b65c93c7bcc75a2630f05；实际 PR base：de266c4cf79fe3543d6fcfc1b69028c702e5d4d0。
- 历史计划：4462a7c048beebd1caed82a7c0ba1fc80d0cb16b（主线 v1）。
- 原 request：manual-chat-s2r-repro-001；executor session ID 当时未记录，不伪造。

## 固定阅读入口

[交付摘要](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/SUMMARY.md)
[CI 诊断](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/ci_failure_analysis.md)
[输入收据](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/input_receipt.json)
[冷复核](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/t3/cold_review.json)
[复算差异](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/t3/comparison.json)

上述多数为 agent 的执行报告，须与源码/原始记录核对；不能认为全文链接就等于已独立运行。
旧包/执行机上文件及 gzip/模型二进制不能当成下一 Chat 必然可读。当前补证要求由 NEXT_ACTIONS 的 GITHUB-HANDOFF-001 执行，不再运行旧 S2R 计划。
预算继承：按交付定向 2/2、冷复核 2/2，新增次数为 0；其他用量需文本总账核对。
