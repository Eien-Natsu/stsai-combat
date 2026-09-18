# STSAI 唯一主线控制文档

规则版本：3。所有者本次明确指定：每轮新 reviewer Chat、每步新本地 agent Chat/session；reviewer 的可见信息上限为已推送到本 GitHub repo 的内容。
本文件定义目标、验收、职责和权限。当前任务只见 [NEXT_ACTIONS.md](NEXT_ACTIONS.md)；定位快照见 [SESSION_STATE.json](SESSION_STATE.json)，不能把定位状态当验收或扩大权限。

## 1. 入口与权威

新 reviewer 和新 executor 均按零记忆启动：AGENTS → 本文件 → 指定 plan commit 的 NEXT_ACTIONS → 来源交接与可读证据；不得假定知道上一 Chat 的讨论、执行机状态或未提交产物。
main 提供唯一默认入口，具体实现和证据可在本仓库的固定开发提交；control commit、plan commit、code base、待审 HEAD 必须分清。main 的控制文档更新不是实现自动合并或 S2R 审查通过。
优先采用所有者指定的固定任务/PR 指针；多个候选计划、过期索引、缺来源或预算不明时先核实，不按最新分支猜测。历史 NEXT_ACTIONS 从其原提交读取，不能重跑旧 READY。
PR 对规则的修改是待审内容，不自动授权。当前结构初始化的明示授权只适用于第 7.7 节；后续 reviewer 不能自行扩大权限、预算或测试范围。

## 2. 目标与非目标

最终目标：在用户的 RTX 5070 资源条件下，做出使用合法公开信息的《杀戮尖塔》铁甲战士局内战斗 AI，逐步追求可与顶尖人类比较的表现，并留下可复现代码、模型、评测和实机证据。
本阶段不做路线、选牌、商店和整局规划；不能用限定战斗夹具胜率推断 A20H 整局胜率。训练完成、低 loss 或赢过启发式都不等于达到最终目标。
技术路线是经过审计的模拟器 → 公平但明确声明近似的搜索教师 → 蒸馏学生 → 经独立验证后才考虑网络辅助搜索。路线中的后续环节不是本轮启动许可。
最终覆盖应包括完整铁甲卡池、生成卡、升级/变费/X 费、选择与多选、药水、遗物计数、多敌人/复活/分裂、精英/Boss/Heart，以及从受支持实机战斗状态接入。每项都要有能力矩阵和规则证据。

## 3. 当前状态：实施已交付，审查尚未通过

本次从 GitHub fetch 核对：main 的实现仍是初交付 `e2e58d61c9bf9fde6ff18448ce44880549c99464`；开发基线为 `de266c4cf79fe3543d6fcfc1b69028c702e5d4d0`。本次只向 main 提升会话控制文件，不代表 S2 实现已合并或 main 代码已经可复现 S2。
上一轮实施 PR #3：`agent/s2r-repro@e0fc584d19afe58ac10b65c93c7bcc75a2630f05`，目标 `s2/fixed-budget-data`。实施已交付，PR 仍 OPEN、未合并，agent 标记 BLOCKED；执行计划来源为旧 `4462a7c048beebd1caed82a7c0ba1fc80d0cb16b`，不是后出的会话规则版本 2。
PR #1/#2 是控制结构的历史演化分支。本次 main 上的新入口取代其活动规则；不能再机械合入旧入口，也不能把 PR #3 的“交付完成”解释为验收或合并完成。

### 3.1 已有工程与实验记录

开发代码锁定引擎 `7476a81954020087da31d41d16fddf475746ec2d` + 5 补丁，schema 4 / encoding 5 / loss 2 / scenario 3 / utility 1，sampler `public_history_candidate_sampling/2`；有限 native 范围为 23 卡牌 ID、17 遭遇，不是全游戏覆盖。
S2 历史 JUnit 为 277 tests、0 failed/errors/skipped；这是历史记录，不是当前 Chat 实跑。`game_differential_verified=false`，原游戏、完整覆盖与正式晋级证据仍缺。
S2 固定数据量对照的权威文件是 `reports/s2_volume_protocol.json`，不是早期同名 louse 修复协议。D384−D96 主集合联合均值 0.0093522135，95% 条件场景区间 [-0.0034831543, 0.0233042806] 跨零，结论仍是固定预算下证据不足。
三个 D384 模型相对 heuristic 的限定结果不等于达到 search/人类基准；两个开发集合已用，不再当全新留出集。self-KL 不可作为可直接相减的噪声下限。

### 3.2 上一轮交付的可读部分与缺口

从 PR #3 固定 HEAD 可读 `reports/s2r/SUMMARY.md`、CI 诊断、输入/构建/模型 smoke/复算收据及 step_logs。原计划到实现 HEAD 的差异为 58 文件；未据此授予通过。
agent 报告已恢复 7 项输入、两次冷复核和两次 T0 定向运行，T0 的判据问题交 reviewer 决定；本次观察 PR #3 的两个 CI check 均 FAILURE。不能继续写“尚待执行 S2R”，也不能因局部收据 PASS 忽略失败。
关键复核问题：cold_review.json 的被测 checkout 固定为历史 `253e3914a2da95bd5984b45c1559635f5f1621c3`，而新的校验器来自实施分支；须给每项命令标明实际代码 SHA，不能用历史 277 tests 替代新代码测试。
隔离报告涉及空 HOME/显式环境，但收据 environment 列出 token 变量名称；字段来自父进程还是子进程、凭据可达性如何证明须提供可读说明。变量名称不等于 secret 值，本次未读取或索取任何值，也未认定发生泄露。
模型、S2 4096 条逐场/59812 条逐决策等原产物仍主要引用执行机或 ZIP；有 hash 不等于新 Chat 能读内容。完整新测试 stdout、两次运行对应证据和预算总账也应由索引串起；缺项明确 NOT_AVAILABLE，禁止从汇总反造。
**当前下一步是 GITHUB-HANDOFF-001：仅把已有交付转为 GitHub 仓库可读、自包含的证据与会话交接。不是重新执行 S2R，不修训练判据，不追加冷跑。**

### 3.3 固定来源

[PR #3 交付](https://github.com/Eien-Natsu/stsai-combat/pull/3)、[历史执行计划](https://github.com/Eien-Natsu/stsai-combat/blob/4462a7c048beebd1caed82a7c0ba1fc80d0cb16b/NEXT_ACTIONS.md)、[固定实现及证据树](https://github.com/Eien-Natsu/stsai-combat/tree/e0fc584d19afe58ac10b65c93c7bcc75a2630f05)、[S2R 小结](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/SUMMARY.md)、[冷复核记录](https://github.com/Eien-Natsu/stsai-combat/blob/e0fc584d19afe58ac10b65c93c7bcc75a2630f05/reports/s2r/t3/cold_review.json)。
来源仅表示定位和已读取记录，不等于本次独立科学复现；当前本地写能力只用于协议初始化，不作为未来 reviewer 的环境保证。

## 4. 不可突破的边界

1. 策略、搜索特征和网络不得使用真实未来牌序、隐藏随机决策、真实 seed/RNG、卡牌 UUID。真实环境保存 RNG 和隔离的规则诊断可用真值，但不得流入公平 teacher/训练；合法已观察历史和已知牌顶允许使用。
2. `reference_v1` 只证明工程联通；不得将其成绩或权重改称 native。native 失败须显式失败，不静默替换后端；未知卡、药水、遗物、阶段或动作不得伪装为 END。
3. 新能力必须同步状态导出、合法动作、采样审计、模型编码与规则测试。sampler 的独立流/候选集是近似，不是原游戏联合后验；碰撞扫描或字段黑名单不构成公平性证明。
4. 不删除失败测试、失败日志、负结果或降低验收标准；PASS/FAIL/NOT_RUN/TIMEOUT/SKIP 分开，skip 不算 pass。接口 Protocol 的省略号和范围外显式错误不是待伪造的实现。
5. 不用最终盲测训练、调参、选模型或挖掘失败；开发集使用状态必须记录。不同语义版本/目标/teacher 的旧数据和权重未经兼容证明不得混用或重标记。
6. 不读取/输出私钥、token，不改 SSH/驱动/安全设置，不重启，不覆盖存档，不上传无关用户文件，不购买云算力。允许的 Git 文档/代码交付不等于授权上传整台机器的数据。
7. 安装仅限项目虚拟环境；系统依赖、游戏安装或权限扩大需要授权。默认 2 CPU workers，其他数量/时长以当轮更严格上限为准；单卡预算不是无限训练许可。
8. 本地执行/发布只在自己的 clone/worktree 操作，不重置、清理或切换其他 session 的工作目录。获授权的测试需在隔离且不挂载写凭据的环境执行；不在有 keyring/SSH 凭据的环境运行不可信 PR 代码。未来 reviewer 不依赖本机执行能力。

## 5. 长期验收：保留标准，不机械重走旧安装流程

G0–G5 是长期验收，不是 reports/s1r_gates 下同名 G1–G4 的局部修复检查；局部 gate 通过不得自动升级长期关卡。
以下为验收要求。本轮文档整理没有重新执行这些项目；已有证据必须逐条映射到要求，不能用一个 PASS 替代整张表。

| 关卡 | 必需证据与边界 |
| --- | --- |
| G0 工程闭环 | 完整 pytest 原始输出；参考规则、观察隔离、采样、mask、梯度、并行采集、split、恢复、桥接拒绝未知状态；smoke 实际收集→训练→重载→评测，记录 backend。只证明已测范围可执行。 |
| G1 目标 GPU | `doctor --require-cuda` 退出 0；GPU/显存/驱动/wheel 与依赖锁；真实 CUDA 前后向、有限梯度，选定模型/微批次至少 10 次优化步和显存峰值。BF16 仅在支持时启用，否则 FP32；不静默 CPU 回退。 |
| G2 native pilot | 锁定上游及补丁；真实 import；native 测试实际执行；至少 1,000 个限定场景/动作序列回放，0 非法动作/崩溃/未解释 UB；逐卡/升级及敌人可见行为分支定向覆盖；截断单列，搜索不改真实环境或公开根状态。1,000 不是穷尽证明。 |
| G3 原游戏一致性/公平性 | 独立原游戏轨迹；相同初始状态与动作脚本、明确受控随机机制；版本/Mod/引擎/场景注入/原始与规范化轨迹/差异报告；最低 100 条短规则轨迹 + 100 场完整 pilot。区分规则错与随机耦合不同，不普遍放宽容差；保留 sampler 近似声明。 |
| G4 强度进步 | 冻结分布和算力；比较 heuristic、无网络搜索、纯网络、网络辅助搜索；正式晋级至少 1,000 个固定验证场景的独立整场结果，按场景配对效用/胜负区间；0 非法/崩溃、截断透明、死亡率无不允许退化、HP/效用提升且延迟符合预算。小样本和监督 loss 不替代。 |
| G5 完整战斗能力 | 本文最终覆盖的每项都有 capability matrix 与原游戏证据；从任意“已声明支持”的实机战斗状态接入。讨论超过人类须固定合法观察、难度/卡组/HP/资源、思考预算、指标与真实人类基准。 |

S2 有真实实验记录和受限正向信号，但缺 G3、完整覆盖及正式 G4 晋级证明；本次未补充新的验收。G1 历史训练不能代替新环境 CUDA 检查，277 tests 也不能单独证明 G2 全部要求。
G3 缺游戏时允许明确标注“未认证 simulator pilot”的有界研发；不因此声称通过 G3。最终盲测仅在选定模型、满足前置并经明确授权后创建，不能把历史路线表里的 P6 敌人扩展编号与最终测试混淆。

## 6. 从当前状态向最终目标推进

当前只执行 NEXT_ACTIONS 中的 GITHUB-HANDOFF-001；旧 S2R 已交付，不重做。其后先审查复核材料，再决定下一份单轮计划；下表是长期顺序，不是可自行并行启动的任务单。

| 后续阶段 | 进入条件与方向 |
| --- | --- |
| 可复现基线 | 先补齐交付来源、代表模型、逐场原始结果、冷构建和独立复算；保留 S2 的负/不确定结果。 |
| 限定分布学习诊断 | 复核通过后，预注册一个问题；例如固定数据检查优化预算是否不足。不能同时换数据/容量/teacher/目标；是否做、步数/seed/评测上限须另定。 |
| 规则与能力扩展 | 原游戏夹具与差分、单选/多选、状态/生成卡/费用链、药水、遗物公开计数、更多敌人与隐藏变量逐项扩展；每项同步接口、采样、编码与回归，不能只扩大枚举。 |
| 实机与搜索性能 | 先实现合法公开历史到 belief root 的恢复；叶值先做 Brier/reliability/ECE 等校准与独立验证，再开 hybrid/leaf value；profiler 证明热点后再做批处理、树复用、宏动作等。 |

数据按整场/近重复快照分组，分别记录训练与目标分布，不按决策行随机切分；探索性分层结果必须带 n，不据此临时改采样或判据。长期资源（药水、永久成长等）不由当前单战效用自动完整表示。

## 7. 固定协作：全新 reviewer Chat ↔ 全新本地 agent session

每次 reviewer 都是没有前文的新 Chat；执行它的指示的也必定是没有前文的新本地 agent Chat/session。两边都必须按零会话记忆设计交接，不能写“接着上次”“按之前讨论”而不提供仓库指针。

```text
新 Chat R_n：读 GitHub 已发布代码/证据 → review → 选择一个下一步 → 发布计划 → 结束
新本地 agent A_(n+1)：读指定计划 → 执行一个有界任务 → 将审查必需证据推入仓库 → 结束
新 Chat R_(n+1)：只凭仓库重新审查 → 决定下一步；不找旧 Chat 补上下文
```

### 7.1 角色与可见性

| 角色 | 可依赖的信息与职责 |
| --- | --- |
| Reviewer：全新 Chat | 只依赖本仓库已推送的固定提交中的代码、UTF-8 文本证据和交接；负责判断及拆分一步。不假定能访问执行机、终端、ZIP、模型二进制、历史聊天或项目记忆。 |
| Executor：全新本地 agent session | 无前 session 的内部状态；读取自包含计划，在已授权本地环境实施/验证，主动提供下一位 reviewer 所需材料。 |
| Owner | 指定角色、计划/待审 PR 指针，授权额外预算/权限和合并；不能用“已做完”替代证据验收。 |

reviewer 可读的本地 clone 也只能代表已推送内容；执行机未提交文件不算交付。PR/CI 链接用于定位，必要的日志和结论依据仍要进入仓库，不能只依赖会过期的 CI artifact、Release/LFS 指针或聊天附件。
二进制、压缩包和大数据的 hash 只能证明所指文件身份，不能替代内容审查。agent 必须提供可分页读取的文本结果、元数据和来源映射；未独立加载模型/复跑实验的 reviewer 必须写“读取 agent 证据”，不能写“本人验证通过”。
需要本地实验、解压分析、模型检查或额外诊断时，reviewer 将其写进下一任务的证据要求，让新 agent 执行并回传到 Git；不得把下一 Chat 拥有本机权限作为前置。当前拥有写工具不代表下一个 Chat 同样拥有。

### 7.2 仓库布局与启动

唯一规则：PROJECT_MAINLINE.md；唯一当前任务：NEXT_ACTIONS.md；SESSION_STATE.json 只作定位快照，不另定义规则。handoffs/ 是历史记录而非多份当前任务。
新角色先读取所有者指定的固定 control/plan commit 的 AGENTS → 主线 → NEXT_ACTIONS → 来源 REVIEW/EXECUTION 与证据索引。只有仓库名时从 main 的入口定位；多个候选或索引落后时核实用户指定 PR，不按最新时间/最大 PR 号猜。
控制提交与 code_base_commit 可以不同；计划必须分别给出。main 的控制文档已更新不代表开发实现已合入，不能从旧 main 重新训练或把 main 合并进开发分支来“同步”。
每任务有 task_id、每交接有 request_id、每新角色有新 session_id；拿不到原生 ID 时声明为人工记录 ID。不能伪造旧 session ID，不要求私密聊天链接。
同任务只允许一个执行者/审查者；状态标签、JSON 和评论不是原子锁，当前由所有者串行发起。开始前查询已有同 task 的交付，重复通知不重做。

### 7.3 每份下一任务都必须为下一个 reviewer 设计证据

reviewer 选择一个任务，并在动手前列“审查问题 → agent 要执行的检查 → 必须提交的路径/字段 → 判定与失败条件”。不能等下一 Chat 缺资料后再假定原 agent 还在线补充。
任务必须自包含：task/plan/source_review、control commit、code base、目标分支与依赖、输入路径及来源/hash、已知状态与不确定性、唯一目标、允许/禁止修改的文件、步骤/实际可用命令、验收、预算、交付/停止条件。
引用旧记录必须给固定提交和路径，并解释为何相关；只写“同上”“上一轮报告”“本机有”不合格。尚未实现的脚本/参数要标明待实现，不给伪可运行命令。
每份任务的必需交付至少包括 EXECUTION.md、EVIDENCE_INDEX.md、budget.json，以及所有审查问题需要的文本证据。模板在 .github/，模板字段不是另一份控制规范。
EVIDENCE_INDEX 每项列 claim_id、问题、路径/提交、原来源与轮次、字节数/hash、记录数/键范围、执行命令/代码 SHA/环境/退出码、证据类型、限制；明确哪些只来自既有报告。
原则上证据用 Markdown/JSON/CSV/JSONL/纯文本，不把关键内容仅藏在 .gz/.zip/.pt。大文本确定性分片，建议每片不超过 200 KiB/500 行；索引给顺序、完整性和总量。保留所有失败/截断/反例，不只选好看的样本。
可先发布大文件的完整文本统计、逐项结果和元数据；若审查问题必须看原始内容，就提交可读分片，否则标 EVIDENCE_BLOCKED 并缩小可作结论。不能要求秘密、用户存档、游戏本体或敏感原日志入库。
数据转换需记录原压缩文件和解压内容的不同 hash、转换脚本及规范；不把新计算 hash 冒充历史承诺。文本证据无法证明的事项如实列未验证。

### 7.4 新 executor 的执行与结束

新 session 核对指定任务为 READY、基线和输入可用、前任务已结束且没有同 task 交付。使用独立 branch/worktree，不清理/切换其他 session 目录。
从 code_base 建分支，按计划明确的路径导入 control commit 的文档；不把旧主线代码整支混入。只执行一个任务的必要子步骤，不修改规则来给自己扩权。
交接前检查 git diff/check、git ls-files 与 .gitignore；未追踪文件、仅本地路径、无法读取的压缩包和过期链接不算提交。push 后从远端固定提交回读文件，记录实际 Git blob 与字节摘要、索引行数和失败原因。
EXECUTION 记录实现代码 SHA、plan/control SHA、执行者 ID、输入/操作/结果/证据/已知问题；最终含交接文件的 HEAD 在 commit 后写进 PR，不要求文件自引用自身 SHA。远端回读收据可后续追加，验证其载荷与最终 HEAD 一致。
结束时将本分支 NEXT_ACTIONS/SESSION_STATE 标为 DELIVERED_WAITING_REVIEW 或 BLOCKED，注明 NEW_CHAT_REVIEWER；不把旧 READY 留给下一个 session 重跑。根 main 的定位快照可能滞后，交付 PR 的固定快照必须提供。
成功、失败、预算耗尽或缺资料均写交接并结束；之后修复也必须经过新 Chat 计划，再开新 agent。不为了给回复补一句话在原 session 接着接下一步。

### 7.5 新 reviewer 的审查、发布与结束

新 Chat 核对 plan/source/input/HEAD/BASE/request/handoff 内容，分页读取所有关键证据；仓库缺资料则结论为 EVIDENCE_BLOCKED，并拆出补证一步，而不是猜测本地状态。
从历史 plan_commit 评价旧任务是否越界，从当前获授权 control commit 制定未来规则；不把新模板反向当作旧执行违约。Summary 的通过、CI 绿灯、换 Chat 本身都不证明独立复现。
REVIEW 区分确定缺陷/疑点、路径/行号、证据层级、验收与剩余风险；只用仓库可见信息作结论。记录代码/规则/证据/计划版本和已有预算；不因本地报告声称成功就忽略实际测的可能是旧代码。
在独立规划分支提交 REVIEW、更新 NEXT_ACTIONS 为一个自包含下一任务、更新定位索引；不得修改已冻结实施分支。没有可安全下一步则写 WAITING_OWNER/STOP，不能保留旧 READY。
具备写权限时 push 后回读确认，才叫 PLAN_PUBLISHED。不假定 GitHub app 或下一 Chat 有写权限；写入不可用时给所有者原样落库指令，使用单独全新 PUBLISH_ONLY agent session 只发布文件、不实施任务，验证后才能另开 executor。
发布者可用已授权本地 Git/gh，不能把凭据发给 reviewer；计划尚仅在 Chat/下载文件时为 PLAN_NOT_PUBLISHED。PR 评论仅是文件索引，不能代替仓库计划与 REVIEW。
发布完成后 reviewer 结束；不得在同一个 Chat 审下一轮。review accepted 只表示该任务判断，不授权合并、改预算或宣称全部 G0–G5 通过。

### 7.6 预算、版本与状态门禁

预算绑定 budget_scope_id，不随 Chat/session/分支/request 变化清零；EXECUTION/REVIEW 必须记录授权、进入时已用、本次用量、累计、剩余和来源，包括失败/超时/复跑。未知不填 0，暂停相关操作。
子任务继承父范围；新增预算须所有者批准。旧任务次数耗尽即便分钟数有余量也不能再跑。崩溃恢复须先确认旧命令停止，新 session 记录 resume_from，保留已消耗用量。
发布前复查 HEAD/BASE/body/request/开闭状态；变化则旧结论只标 stale，等新交接。handoff_sha256 用 PR body CRLF/CR→LF 后 UTF-8 SHA256，不回填 body；按任务/HEAD/BASE/request/摘要/规则版去重。
状态标签互斥、保留其他标签：agent-ready-for-review → agent-reviewing → agent-needs-work / agent-review-approved / agent-blocked。缺证据/发布失败/过期不写完成标记，标签不是授权或原子锁。
禁止自动合并、auto-merge、force-push、删除失败证据；普通 reviewer/executor 不能直接写 main。一次合并需所有者明确授权和核对准确 HEAD；协议初始化的特定授权不是后续常驻权限。
连续两次交接在同一阻塞无进展则交回所有者；没有同 agent 连续三轮自动修复的例外。会话结束不表示关机或终止远程连接服务。

### 7.7 当前 Chat 的一次性初始化例外

所有者明确要求当前 Chat 持续到仓库会话结构调整完成，并允许必要的开发分支部分内容进入 main。当前角色为 BOOTSTRAP_MAINTAINER，可用已授权 Remote Desktop Commander 在本地写控制文档并发布；不冒充全新独立 reviewer。
本次只提升已检查的主线、入口、任务/交接模板和静态状态记录到 main，不合并 PR #3 的 S2/S2R 实现，不改训练/测试/引擎，不追加实验。保留准确来源与变更清单。
本例外止于本次结构落地；需要原执行机资料时给所有者一份新 agent 的自包含任务。不能延续成当前 Chat 长期审所有轮次，也不能据此承诺下个 Chat 能读取本地。
PR #3 已按旧 4462a7c 计划交付；不得重发旧 S2R-REPRO。当前初始化之后的第一步以 NEXT_ACTIONS 为准；旧 PR #1/#2 只作方案演化记录，不再当作并行活动规则。
未来 hook 只有能串行创建新 Chat/新 agent 并携带固定指针才符合本协议。当前尚无已注册事件任务，不把贴标签或设备连线当成自动唤醒。

## 8. 生命周期与历史

主线当前状态更新须注明来源提交、读取/执行层级；NEXT_ACTIONS 只保留当前一步，旧计划从 Git 历史读取。handoffs 保存 EXECUTION/REVIEW/证据索引与预算，不复制多份活动任务。
历史 reports/evidence/模型清单与失败日志不改写；旧安装/路线/交接入口的有效限制保留在主线，旧文件可从 Git 历史恢复。技术参考不授予当前执行权限。
本次结构核对记录在 handoffs/BOOTSTRAP-GITHUB-ONLY/REVIEW.md 和 reports/session_structure_v3_audit.json；它是迁移及可见性检查，不是对 S2R 实现的完整验收。
