# EVIDENCE_INDEX — TASK_ID

读者：没有旧 Chat/本地工具的全新 reviewer。只索引已经 push 且可分页读取的 GitHub repo 文本。
Snapshot：task/request、历史 plan/current control、实现 SHA、证据 payload SHA（发布后在 PR/收据提供）。
阅读顺序：EXECUTION → 关键问题表 → 原始文本/逐项记录 → 预算 → publish_receipt。

| claim_id / 审查问题 | 固定提交与路径/行范围 | 命令、driver/被测代码 SHA、输入 | 结果/证据层级 | 限制 |
| --- | --- | --- | --- | --- |
| 实际填写 | 实际填写 | 环境/退出码 | 实跑/历史报告/推断/NOT_AVAILABLE | 未知明确写 |

files.json 每项：路径、来源轮次/提交、原文件及解压内容 SHA256、字节数、转换规则、记录数、键范围、分片顺序与 Git blob。
大文本建议 ≤200 KiB/500 行分片；索引覆盖全部片，不遗漏失败/截断。不得用少数样例替代完整性要求。
二进制仅存元数据/hash 不能宣称 reviewer 读过模型；相应已有检查须有可读输出，不强求上传权重/游戏/secret。
本机路径只作来源说明，不作阅读入口；必要信息只存在于未推送文件、压缩包、Release、LFS 或旧聊天时标 NOT_AVAILABLE。
脱敏不可抹掉失败原因；注明影响验证的缺口，不上传原秘密以证明脱敏。安全扫描不输出 secret 值。
