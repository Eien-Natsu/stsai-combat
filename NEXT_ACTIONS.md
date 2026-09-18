# 当前单步：GITHUB-HANDOFF-001

- Task ID：`GITHUB-HANDOFF-001`；状态：`DELIVERED_WAITING_REVIEW`（已由本地 agent session 执行并交付；不再是 `READY`，下一个 session 不得重跑本轮）。
- 交付记录：`handoffs/GITHUB-HANDOFF-001/`（EXECUTION、EVIDENCE_INDEX、files.json、budget.json、clarifications、command_versions、publish_receipt）；仓库可读证据在 `reports/github_handoff_001/`。
- 本轮结论：证据已整理、已 push、已从远端回读；缺项如实记为 `NOT_AVAILABLE`（17 项新测试无执行日志、第一次冷复核无逐步骤收据、CI runner CPU 型号未记录）。PR #3 本身**未**被验收、未合并，T0 判据修改仍未决定。
- 来源：所有者本次会话结构调整授权；`handoffs/BOOTSTRAP-GITHUB-ONLY/REVIEW.md` 的可见性核对，不是对 PR #3 的完整 review。
- Plan/control commit：`5c331ca8c043c951b5ea9687fc7b92b3566ee21d`（领取时由所有者指定并记录；本文件不引用自身提交）。
- Code base：`e0fc584d19afe58ac10b65c93c7bcc75a2630f05`（PR #3，`agent/s2r-repro`）。
- 建议实施分支：`agent/github-handoff-001`；PR base：`agent/s2r-repro`，只展示本次补证增量。原 PR #3/#2/#1 不合并、不重置、不强推。
- 下一角色：`NEW_CHAT_REVIEWER`。交接后结束本 session，不等待 reviewer 后原地续跑。

## 目标与背景

下一位 reviewer 是只能读取已推送 GitHub repo 内容、没有前文的新 Chat；你也没有旧 agent 的内存。把 PR #3 的已有代码/运行/数据证据整理成仓库内可读、自包含的交接，使它可以 review 和制定后续一步。
PR #3 已交付 BLOCKED，不重发 S2R T0–T4。它按旧 `4462a7c` 计划执行，本轮不得改历史判断/日志来适配新协议。
先读指定 plan commit 的 AGENTS、PROJECT_MAINLINE、本文，再读固定 code base 下 `reports/s2r/SUMMARY.md`、`input_receipt.json`、`artifact_lock.json`、`ci_failure_analysis.md`、`t3/cold_review.json` 与原始日志。

## 边界与预算

本轮仅已有文件读取、确定性解压/分片/脱敏、索引/文档/清单生成与 Git 交付；新增训练/优化/采集/对局/推理/pytest/冷构建/模型加载/统计 bootstrap 全部为 0。不要加载 pickle/.pt，不调用 torch 读取模型。
不修改 `src/`、`native/`、`review/`、实验 `scripts/`、`tests/`、依赖或 CI；不修改 loss/optimizer/断言/容差。需要修复它们则交新 reviewer 决定。
数据转换最多 1 CPU worker、累计 CPU 处理墙钟不超过 10 分钟、内存目标不超过 512 MiB；流式处理，超限保存部分结果并 BLOCKED。不安装新系统依赖，不启动付费资源。
Budget scope：`HANDOFF-PUBLISH-001` 只授权文本整理。旧 `S2R-REPRO` 按交付已使用定向 2/2、冷复核 2/2，均无新增次数；总耗时据旧日志汇总、缺记录写 unknown，不能用新 scope 重置实验预算。
不读取/输出 SSH、token 值、不访问无关用户目录、不关闭远程服务。不依赖容器里“以前装过什么”。

## P1 — 固定代码与规则，不覆盖旧 session

检查 status/HEAD/remote 和是否已有同 task 的 PR/交付；若已存在，不重复开始。在独立 worktree 从 code base 建分支。
从指定 plan commit **仅导入控制文件**：AGENTS.md、PROJECT_MAINLINE.md、NEXT_ACTIONS.md、SESSION_STATE.json、`.github/` 下本计划的五份模板、`handoffs/README.md` 和 `handoffs/BOOTSTRAP-GITHUB-ONLY/`。先核对路径，不将 main 整支合并进开发代码。
五份模板为 agent_handoff_template.md、review_handoff_template.md、next_actions_template.md、evidence_index_template.md、pull_request_template.md；主线引用的静态审计可通过 plan commit 读取，不要求复制。
记录 executor_session_id（可声明为生成的记录 ID）、task/request、plan/control/code base、实际工作目录与源文件位置；不要假设旧 agent 的目录就是你的目录。

## P2 — 提供下一位 reviewer 必需的信息

建立 `handoffs/GITHUB-HANDOFF-001/EVIDENCE_INDEX.md` 与 `files.json`。下表每个问题要对应固定代码、原始/转换后证据、命令和已知限制；无法获取时填 NOT_AVAILABLE，不以新跑结果填旧洞。

| 审查问题 | 必需仓库可读交付 |
| --- | --- |
| 旧任务到底做了什么、是否越界 | 原计划/实际实现 SHA、任务与依赖；T0–T4 每项完成/失败/未执行及原因，含原始证据引用。 |
| T0 诊断足以支持改断言吗 | 已有两次诊断、gauge 检查的代码/JSON/stdout/退出码，原 CI 失败日志；固定输入/环境与参数/梯度差异来源，不再运行诊断。 |
| 测的是哪个版本 | `command_versions.json`：每条命令的 driver/script SHA、被测 repo SHA、模型/输入 hash、环境与退出码。明确 T3 checkout=253e391 与 PR #3 新校验器的区别。 |
| 新增 17 项测试真的执行了吗 | 既有测试命令、实际代码 SHA、原始 stdout/JUnit/退出码；找不到既有日志则说明缺失，不能只写测试源码存在或套用历史 277 tests。 |
| 隔离说法是否有依据 | `clarifications.md` 区分 cold_review 的 parent environment 与传给 subprocess 的实际字典、文件/凭据可达性以及未实现的隔离层；引用源码，不读取或输出 token 值。 |
| 七项产物如何追溯 | 旧包 MANIFEST/provenance 的可读副本及来源 hash；各产物原文件/解压数据 hash、大小、旧承诺与恢复来源。权重只用既有元数据/检查结果，不必推送或重新加载二进制。 |
| 4096 场复算是否完整 | 原始逐场记录全部转为文本分片，保持全部字段/键/顺序；索引给两个集合×8策略×256 的预期与实际键覆盖、重复/缺失与来源。不得从汇总生成假逐场数据。 |
| 59812 条逐决策是否与对局对应 | 原始逐决策记录的可读分片及顺序/总量/hash，已有对应检查的输入与输出，不只给“已一致”布尔值。 |
| 冷复核两次与预算是否可追溯 | 每次已有命令/起止/退出码/日志；若仅最终一次保留则注明。budget.json 分别列旧范围已用与本次文本整理用量，不把约数伪装精确值。 |

默认查找已知 `reports/s2r/input_receipt.json` 记录的原 S2 工作区/ZIP 路径（历史示例 `/workspaces/stsai_web`）；仅核对已授权项目位置。新 session 路径不可达就报告缺项与所需提供者，不扫描全机、不索取凭据。
逐场/逐决策等文件放 `reports/github_handoff_001/`，可增加仅用于确定性文本转换的脚本在该目录。压缩数据先核对历史摘要并安全读取，不运行归档内程序、不解出路径越界成员。
分片推荐 ≤200 KiB 且 ≤500 行，索引给每片路径/字节/hash/记录范围/数目；规范化只能改变明确声明的文本序列化，不改数值、键、样本选择或丢失败记录。原始压缩 hash 与解压内容 hash 分开。
已入 Git 且可读的证据直接引用 `e0fc584...` 的固定路径，不重复搬运。新索引写完整 SHA；仅本机绝对路径、未上传 ZIP、压缩文件名或 LFS pointer 不算 reviewer 可访问。

## P3 — 发布并从 GitHub 回读

完成 EXECUTION.md、EVIDENCE_INDEX.md、files.json、budget.json 和必要的 clarifications/command_versions；修改本分支的 NEXT_ACTIONS/SESSION_STATE 为 DELIVERED_WAITING_REVIEW 或 BLOCKED，不保留 READY，不自行写下一轮实施计划。
在手工审查确认没有秘密/存档/游戏数据后，检查 `git status`、`git diff --check`、`git check-ignore`、`git ls-files`；小文件和可读分片提交。只提交白名单路径，不用 `git add .` 掩盖意外内容。
commit/push 后通过 GitHub API或读取远端 commit 回读所有新必需文件；核对路径、Git blob、字节摘要、分片计数，输出 publish_receipt.json。收据可在下一提交追加，明确被验证 payload commit；最终 HEAD 的载荷与该 commit 必须一致，避免自引用 hash。
创建本轮 PR，base=agent/s2r-repro，列 PR #3 及旧 #2 依赖，单列 e0fc584..HEAD 的增量；不修改旧 PR #3 已冻结 body，不合并它。新 PR body 写最终 HEAD、plan/control SHA、task/request/session、证据索引和未验证项。
材料齐全用 agent-ready-for-review，否则 agent-blocked；两种都结束 session，下一接收者是新的 Chat。标签不自动创建会话。

## 完成/停止标准与给用户的回复

全新 reviewer 不需要旧 Chat、旧 agent、执行机或本地附件，只凭固定提交与索引能逐项检查上表；可读证据已远端回读，缺项如实注明。材料完整不等于 PR #3 已通过科学/代码验收。
原始报告和实验实现不改，所有新增实验/测试/模型执行为 0，旧 S2R 次数不重置；仅转换/发布操作计本轮小预算。无法满足任一必要项则 BLOCKED，给具体原因和剩余一步，不偷偷跑实验来补。
最终回复只需：PR 链接、完整 HEAD/plan/control/code-base、task/request/session，EVIDENCE_INDEX 路径，逐项完成或缺失，旧/新预算，下一角色 NEW_CHAT_REVIEWER。停止，不等新指令后继续当前 session。
若只读源或 GitHub 发布权限缺失，保留本地已生成文本并明确未发布，向用户请求具体发布步骤；不能把“文件在本机”写为 GitHub 已可读。不得要求用户把 SSH/token 内容发入 Chat。
