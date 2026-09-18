# STSAI 唯一主线控制文档

文档版本：2。状态核对基线：`s2/fixed-budget-data@de266c4cf79fe3543d6fcfc1b69028c702e5d4d0`。
本文件集中定义目标、当前证据、验收、优先级、资源边界及双方协作。它不是“本轮所有检查已通过”的证明。

## 1. 入口与权威

阅读顺序：本文件 → [NEXT_ACTIONS.md](NEXT_ACTIONS.md) → 本轮明确引用的代码和证据。
`AGENTS.md` 只负责引导；README 只负责导航；`docs/` 是技术参考；`reports/`、`delivery_docs/` 是带版本的历史记录，不另行发号施令。
当前执行指令只有 NEXT_ACTIONS.md。历史计划、旧包内指令、聊天中的旧任务不得自动续跑；变更目标或预算必须明确更新当前指令。
同一轮代码以完整 Git SHA 为准。reviewer 从本轮已批准的基线读取规则，PR 中对规则的修改是待审内容，不会自行授权。

## 2. 目标与非目标

最终目标：在用户的 RTX 5070 资源条件下，做出使用合法公开信息的《杀戮尖塔》铁甲战士局内战斗 AI，逐步追求可与顶尖人类比较的表现，并留下可复现代码、模型、评测和实机证据。
本阶段不做路线、选牌、商店和整局规划；不能用限定战斗夹具胜率推断 A20H 整局胜率。训练完成、低 loss 或赢过启发式都不等于达到最终目标。
技术路线是经过审计的模拟器 → 公平但明确声明近似的搜索教师 → 蒸馏学生 → 经独立验证后才考虑网络辅助搜索。路线中的后续环节不是本轮启动许可。
最终覆盖应包括完整铁甲卡池、生成卡、升级/变费/X 费、选择与多选、药水、遗物计数、多敌人/复活/分裂、精英/Boss/Heart，以及从受支持实机战斗状态接入。每项都要有能力矩阵和规则证据。

## 3. 当前状态：分清记录、代码与本次实测

### 3.1 Git 基线与环境

核对时 `main` 仍为初始交付 `e2e58d61c9bf9fde6ff18448ce44880549c99464`，不是最新实验版本；开发分支已到上述 de266c4。本次文档整理基于开发分支，不把旧 main 的状态当现状，也不自动合并实现到 main。
旧配置 PR #1（`chatgpt/agent-review-protocol@0036a39`）基于初始版，其分散文档方案由本文件收拢。不要在本次整理后再机械合入旧入口；PR 的关闭/合并由所有者决定。
当前 Chat 的 reviewer clone 是独立 Windows checkout；S2 历史执行记录为 Debian 12、Python 3.12.14、GCC 12.2、PyTorch 2.9.1+cu128、RTX 5070。当前 Windows 的全局 Python 不是该历史训练环境，不得混称“同环境重现”。

### 3.2 当前代码与历史验证

- 引擎已锁定 `7476a81954020087da31d41d16fddf475746ec2d`，顺序应用 5 个补丁，见 [engine_lock.json](engine_lock.json)。已含离线 PRE_PATCH 源码及 manifest，不再是“无上游 SHA、尚未编译”的初交付状态。
- 当前版本：schema 4、encoding 5、loss 2、scenario 3、utility 1；sampler 为 `public_history_candidate_sampling/2`。来源为 `src/stsai/` 对应常量及 [S2 固定预算协议](reports/s2_volume_protocol.json)。
- native 白名单已有 23 个卡牌 ID（包括 SLIMED/DAZED）与 17 种遭遇，含多敌人与 Act 1 精英；仍不是全卡池/全敌人覆盖。以 `native/bridge.cpp` 白名单及 `src/stsai/scenarios.py` 为准，不能继续写“只有 Cultist/Jaw Worm”。
- [S2 JUnit](reports/s2_junit.xml) 保存了 277 tests、0 failures、0 errors、0 skipped；[构建日志](reports/s2_build_and_test.log)和[历史小结](delivery_docs/s2/SUMMARY.md)记录了干净目录构建、定向重放、模型 smoke 和训练。这里是读取既有证据，不是本次 Chat 重跑这些实验。
- `game_differential_verified=false`。原游戏差分、真实游戏联调、完整卡池/药水/遗物/Boss 覆盖尚未完成；历史执行环境没有合法游戏副本，不代表已检查当前 Windows 是否装有游戏。

### 3.2a 文档 PR 暴露的当前 CI 阻塞

[PR #2 的 CPU CI](https://github.com/Eien-Natsu/stsai-combat/actions/runs/35369602279) 在文档 HEAD `2cc0c759a4900bb3822a47609bdf6a0a62f824b8` 的测试合并提交 `3eb32ec766476016964248ee0b9791a17c3da72e` 上失败：111 passed、1 failed、6 skipped，后续 CPU smoke 跳过。
失败位于 `tests/test_training_loss.py:199` 的 `test_effective_batch_partition_invariance_end_to_end`：batch=8 / accum=4 时 `policy.2.bias` 不满足原 allclose 断言。日志环境为 Ubuntu 24.04、Python 3.12.14、torch 2.9.1+cpu。这是本次读取的新 CI 证据，不是对历史 S2 277 项记录的改写；根因未确定，不能未经排查归因于数值噪声或宣布实现正确。
这次 PR 未改变实现/测试/CI；新 CI 暴露的问题必须保留并作为 NEXT_ACTIONS 的 T0 先行排查。不直接放宽容差、删除/skip 用例，完整复核仍有失败时不得通过。

### 3.3 S2 的科学结论

本轮指“固定预算数据量对照 S2”，不是早先同名的 louse 修复轮。权威预注册文件是 `reports/s2_volume_protocol.json`；`reports/s2_protocol.json` 与 `reports/s2_freeze.json` 属于较早修复，保留但不得当作本轮协议。
S2 固定 M128、有效 batch 32、最多 500 updates，比较 D96 与 D384；init_seed 为 17/29/43，data_seed=42。新增采集 288 局，新训练 5 runs，D96_s17 复用 S1R；六个逻辑 runs 不等于六个新 runs。
选点用 V24 的逐战斗决策 KL，并列取较早 step，不按开发对局挑 seed/checkpoint。教师一致率用真实教师动作、仅决策状态；单动作状态和 legacy visit-argmax 不混入主指标。self-KL 不能作为可直接相减的噪声下限。
[配对汇总](reports/s2_paired_summary.json)记录：DEV_PROBE256 上 D384−D96 的联合均值为 **0.0093522135**，95% 条件场景区间 **[-0.0034831543, 0.0233042806]**，跨零；结论是固定预算下证据不足，不是“更多数据无效”。历史 SUMMARY 的近似展示数不优先于结构化统计。
三个 D384 学生在该 probe 上相对 heuristic 的区间下界为正，但相对 search 仍差约 0.034–0.045 效用。这只适用于这些训练结果、场景和预算，不覆盖训练随机性，也不是原游戏/超人类结论。
DEV_OLD256 与 DEV_PROBE256 都已经使用；不能再包装成新留出集。3×256 不是 768 个独立场景。两种数据配置都保留，不通过补 seed、换 checkpoint 或改判据追求显著。

### 3.4 当前阻塞：干净仓库不等于完整交付包

本次对 `scripts/make_s2_package.py` 的 FILES 常量做静态存在性核对，28 项必需输入中有 7 项不在干净 checkout，见 [文档整理审计](reports/docs_consolidation_audit.json)。这些可能保留在原执行机/历史 ZIP；缺文件不证明原实验没跑过。
缺项包括 D384_s17 推理权重、S2 逐场结果/延迟、物化场景与数据组成/覆盖文件。不能仅凭汇总 JSON 声称当前 clone 可重打包、复算全部 4096 场或加载六个模型。
**当前首要任务是 S2R-REPRO：恢复可追溯的交付与复核闭环。新增训练、采集和整场开发评测暂不启动。** 下一轮具体范围只见 NEXT_ACTIONS.md。

## 4. 不可突破的边界

1. 策略、搜索特征和网络不得使用真实未来牌序、隐藏随机决策、真实 seed/RNG、卡牌 UUID。真实环境保存 RNG 和隔离的规则诊断可用真值，但不得流入公平 teacher/训练；合法已观察历史和已知牌顶允许使用。
2. `reference_v1` 只证明工程联通；不得将其成绩或权重改称 native。native 失败须显式失败，不静默替换后端；未知卡、药水、遗物、阶段或动作不得伪装为 END。
3. 新能力必须同步状态导出、合法动作、采样审计、模型编码与规则测试。sampler 的独立流/候选集是近似，不是原游戏联合后验；碰撞扫描或字段黑名单不构成公平性证明。
4. 不删除失败测试、失败日志、负结果或降低验收标准；PASS/FAIL/NOT_RUN/TIMEOUT/SKIP 分开，skip 不算 pass。接口 Protocol 的省略号和范围外显式错误不是待伪造的实现。
5. 不用最终盲测训练、调参、选模型或挖掘失败；开发集使用状态必须记录。不同语义版本/目标/teacher 的旧数据和权重未经兼容证明不得混用或重标记。
6. 不读取/输出私钥、token，不改 SSH/驱动/安全设置，不重启，不覆盖存档，不上传无关用户文件，不购买云算力。允许的 Git 文档/代码交付不等于授权上传整台机器的数据。
7. 安装仅限项目虚拟环境；系统依赖、游戏安装或权限扩大需要授权。默认 2 CPU workers，其他数量/时长以当轮更严格上限为准；单卡预算不是无限训练许可。
8. reviewer 只在自己的 clone/worktree 操作，不重置、清理或切换实施 agent 的工作目录。测试需在隔离且不挂载写凭据的环境执行；不在有 keyring/SSH 凭据的环境运行不可信 PR 代码。

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

当前只执行 S2R-REPRO。其后先审查复核材料，再决定下一份单轮计划；下表是长期顺序，不是可自行并行启动的任务单。

| 后续阶段 | 进入条件与方向 |
| --- | --- |
| 可复现基线 | 先补齐交付来源、代表模型、逐场原始结果、冷构建和独立复算；保留 S2 的负/不确定结果。 |
| 限定分布学习诊断 | 复核通过后，预注册一个问题；例如固定数据检查优化预算是否不足。不能同时换数据/容量/teacher/目标；是否做、步数/seed/评测上限须另定。 |
| 规则与能力扩展 | 原游戏夹具与差分、单选/多选、状态/生成卡/费用链、药水、遗物公开计数、更多敌人与隐藏变量逐项扩展；每项同步接口、采样、编码与回归，不能只扩大枚举。 |
| 实机与搜索性能 | 先实现合法公开历史到 belief root 的恢复；叶值先做 Brier/reliability/ECE 等校准与独立验证，再开 hybrid/leaf value；profiler 证明热点后再做批处理、树复用、宏动作等。 |

数据按整场/近重复快照分组，分别记录训练与目标分布，不按决策行随机切分；探索性分层结果必须带 n，不据此临时改采样或判据。长期资源（药水、永久成长等）不由当前单战效用自动完整表示。

## 7. 固定协作模式：每轮新 Chat，每步新 agent session

这是强制协作规则，不是可选建议。一次循环定义为：

```text
新 Chat R_n：读取仓库与 Task_n 交付 → review → 拆出一个 Task_(n+1) → 写回仓库 → 结束
新本地 agent session A_(n+1)：读取已发布任务 → 执行一个有界目标 → 写回证据 → 结束
新 Chat R_(n+1)：重新读取仓库并审查该交付 → 再决定下一步
```

每次 review/规划必须新建 Chat，每个新任务必须新建本地 agent session。上一位 reviewer 不在原 Chat 继续下一轮审查；上一位 agent 不等待新计划后原地续跑。一个任务可以有必需的内部子步骤，但不能把整个路线图当成一次 session 的授权。
同一 session 内允许完成本任务的工具调用、已批准次数内的诊断/修复和交接；收到下一轮计划、增加目标或超出边界即为下一步，必须换新 session。成功、失败、BLOCKED 或预算耗尽都要持久化交接并结束。
新会话不保证审查天然正确，也不改变证据标准。不能把“另一个 Chat 看过”当独立实验、测试通过或合并授权。

### 7.1 仓库是跨会话记忆

新 session 不以旧聊天记忆、项目记忆、上一位 agent 的内部状态或本地临时文件作为执行前提。恢复上下文只依赖获授权的固定提交、仓库交接记录、对应 PR 与可校验产物。
`PROJECT_MAINLINE.md` 是唯一规则来源；`NEXT_ACTIONS.md` 是唯一当前任务单；[handoffs/README.md](handoffs/README.md) 只是历史交接索引。旧计划从其固定 Git 提交读取，不复制多个可执行“当前计划”。
每个任务使用不可复用的 `task_id`，每次交接使用 `request_id`；Chat 与本地 agent 分别记录新的 `reviewer_session_id`、`executor_session_id`，不能冒用上轮 ID。工具没有原生 session ID 时可生成并明确标为本地记录 ID，不要求上传私密聊天链接/全文。
交接记录位于 `handoffs/<task_id>/EXECUTION.md` 和 `handoffs/<task_id>/REVIEW.md`；原始日志/收据可保留在 `reports/<round>/`，通过文件路径、完整提交或附件 SHA256 引用，不重复搬运大文件。
[实施交接模板](.github/agent_handoff_template.md)、[review 交接模板](.github/review_handoff_template.md)、[下一步任务模板](.github/next_actions_template.md) 只规定字段，不是额外任务单；提交的交接不得留占位符。

### 7.2 新 Chat 的启动与职责

所有者提供仓库及待审实施 PR/完整提交，指定这是 reviewer 角色即可；不需要再粘贴上一段长聊天。新 Chat 先实际核实工具、仓库与产物权限，不推断上一 Chat 的连接、文件和执行权限自动可用。
先读取交接中的已授权 `plan_commit` 版本的 AGENTS/主线/NEXT_ACTIONS，再读 EXECUTION、前次 REVIEW、预算记录和被引用证据；核对 PR 当前 HEAD/BASE/request。待审 PR 自行修改的规则只能作为改动审查，不自动获得授权。
reviewer 必须审查代码与证据并决定一个下一步，不仅复述 agent 的结论。缺输入或计划版本不明时先写 BLOCKED，不凭聊天补造任务、测试或预算。只有明确的初始启动可用所有者指令代替前次 REVIEW，须注明 bootstrap。
reviewer 可在既有授权与剩余预算内核验；不接管实施者目录、不修改业务实现、不开展下一轮训练。输出 Review（分级问题及文件/行号/条件/证据）、Verification（亲自执行/仅阅读/未验证）、结论、一个 Next Agent Plan、完成条件及完整快照。
结论区分 needs-work、accepted、blocked；accepted 仅表示本任务审查结论，不是 G0–G5 全过，不授权合并。BLOCKED 仍应保存诊断与所需决定，不伪装成功。

### 7.3 reviewer 必须把下一步写回 Git

在独立的 reviewer 规划分支（例如 `chatgpt/plan/<next_task_id>`）从明确审查的代码 HEAD 建立文档提交，保存本任务 REVIEW，并更新 NEXT_ACTIONS 为一个下一任务。允许写控制文档和交接记录，不顺便改实现。不要改动或重置实施者冻结的分支。
NEXT_ACTIONS 必须写 task_id、状态、来源 review/session/已审 HEAD、代码基线、目标分支、唯一目标、文件范围、步骤、预算继承、验收、交付与停止条件。先列候选再选择一步；其他候选不得成为并行执行许可。
没有可安全执行的下一步时，把 NEXT_ACTIONS 置为 WAITING_OWNER 或 STOP 并写原因；不能保留上一任务的 READY 状态让新 agent 重跑。此时结束 reviewer session，等待所有者决定后另开新 Chat。
提交并 push 后，将真实的 `plan_commit` 完整 SHA 和分支/规划 PR 写到当前实施 PR 的交接回复或索引；自引用的提交 SHA 不写进它自身。读回 GitHub 验证内容与 SHA 后才算已发布。规划提交可以在未合并分支上，由所有者指向新 session；不自动合并来发布计划。
PR 评论可链接仓库 REVIEW/NEXT_ACTIONS，但不能代替仓库文件。评论失败而文件已发布时，向所有者提供可核验的规划提交；文件写回失败则仅为 PLAN_NOT_PUBLISHED，当前 Chat 的草稿/下载文件不能算新 agent 的执行依据。
若需受限的中转写入，由所有者或独立的发布 session 原样落库并回读验证；不得让已结束的实施 session 接着承接下一步。所有者确认选定已发布计划后，创建新的实施 session。reviewer 到此结束，不在本 Chat 审查后续交付。

### 7.4 新本地 agent session 的启动与退出

新 session 领取指定的 plan_commit，读取 AGENTS → 主线 → NEXT_ACTIONS → 来源 REVIEW 与相关证据；核对任务为 READY、版本一致、前次任务未在运行且本任务尚未交付。只有仓库名而有多个候选计划时先询问，不按最新分支或 PR 编号猜测。
在自己的独立 branch/worktree 工作，记录新 executor_session_id、task_id、plan_commit、执行起点 SHA、目标分支及已消耗预算。不清理/切换其他 session 的工作目录；新的 session 可以使用已校验的已有产物，无须重做全部实验。
仅执行这一个任务及其必要子步骤，按 NEXT_ACTIONS 的范围、次数和停止条件运行。遇到必须改验收/训练语义/目标/预算的问题，交付 BLOCKED；不能自行充当 reviewer 批准扩大范围。
结束前提交 EXECUTION、实际代码/文档、原始证据与预算用量，push 并创建/更新本轮实施 PR。模板见 [.github/pull_request_template.md](.github/pull_request_template.md)。记录计划来源、实现提交、最终交接 HEAD、request_id、所有失败/未运行项和下一角色为 NEW_CHAT_REVIEWER。
EXECUTION 记录已知的实现代码 SHA；含交接文件的最终 HEAD 在 commit 后写入 PR，避免文件自引用。新 Chat 要固定最终 PR HEAD，并分清实现 SHA 与文档提交；原始实验绑定的 SHA 不因后补文档而改写。
最后发布 ready 或 blocked 状态、冻结分支和 PR body、向所有者返回 PR/提交/交接路径，结束 session。不得在同一 session 等 review 后继续修复；修复也必须由下一新 Chat 制定任务，再由新的 agent session 执行。

### 7.5 预算、失败恢复与单步门禁

预算绑定 `budget_scope_id` 和任务来源，不绑定会话寿命。每份 EXECUTION/REVIEW 写清授权上限、进入时已用、本 session 实用、累计及剩余，包含失败、超时和 reviewer 复跑。换 Chat、换 session、换分支或 request_id 均不清零。
有父范围上限时，各子任务共享该上限；剩余额度无法核实时阻塞相关运行。新 Chat 可以提出新增预算，但必须获得所有者明确授权并写进计划后生效，不自动授予自己或 agent。
崩溃/中断后先确认旧 session/命令已停止，保存部分交接；恢复必须新建 session、记录 resume_from 和剩余预算。同任务续接可沿用 task_id，但新 session/request_id 不复用；先前证据和消耗必须保留，不重复执行已完成步骤。
同一任务同一时刻只允许一个执行者/审查者认领。标签/评论不是原子锁，无法保证单消费者时由所有者串行发起，不并发抢任务。重复通知只返回已有结果，不重新规划。
不再采用“同一个 agent 连续自动修复 3 轮”的约定。每完成一步都强制经过新 Chat，再启新 agent；同一阻塞在连续两次交接中无实质进展，停止并请所有者决策。

### 7.6 快照、去重与 PR 状态

每次认领记录 repo、task_id、plan_commit、PR、实现 SHA、当前 HEAD/BASE、request_id、两个角色的 session ID、主线版本和唯一 run ID；未知项写明原因，不伪造。
PR body 先将 CRLF/CR 归一为 LF，再以 UTF-8 计算 handoff_sha256；摘要不回填 body。按 `(repo, task_id, HEAD, BASE, request_id, handoff_sha256, mainline_version)` 去重，先查受信任来源的既有结果/认领。
发布 review 前复查 HEAD/BASE/body/request/开闭状态；变化时旧结论仅标 stale，不能当当前通过。新 agent 开始前再次核对 plan_commit 与 source_review 的已审 SHA，不把规划文档提交误当已审实现提交。
同快照正常重复事件不重审；CI 补齐、base 变化或所有者指定复审，须新 request_id 和新 Chat，并写理由、继承消耗。session ID 和机器标记不是签名/独立性证明；共用 GitHub 身份时仍需核对所有者授权链。
只接收明确目标分支、本仓库来源、打开且非 draft 的实施 PR。当前过渡允许经所有者指定的 s2/fixed-budget-data 或规划分支；其他目标不得隐式重定向。未合并的依赖 PR 必须列出，并单列 plan_commit..HEAD 的实施差异。
五个状态标签互斥并保留其他标签：agent-ready-for-review → agent-reviewing → agent-needs-work / agent-review-approved / agent-blocked。需求修复必须等新计划和新 session；review-approved 不等于 GitHub APPROVE 或合并授权。
完整且非 blocked/stale 的 review 发布成功后可用下列标记；所有占位符须替换。标签写回失败只修状态，不生成第二份计划。

```html
<!-- agent-review mainline=2 task=TASK_ID pr=NUMBER head=SHA base=SHA request=ID handoff=SHA256 reviewer=SESSION_ID status=complete verdict=needs-work -->
```

### 7.7 手动换会话与未来触发器

当前运行方式：所有者在 Chat 发起一次操作，双方工具权限每个新 session 实际核实。设备连接/标签都不能自行新建 Chat 或启动本地 agent；本协议不是已部署的调度器。
期望通知仍可用 pull_request/labeled + agent-ready-for-review，但事件订阅未创建、无任务 ID、无端到端验收；不得宣称无人值守或静默改用轮询、daemon、Codex、外部收费模型 API。
未来任何自动化也必须创建新 reviewer Chat 与新 executor session，携带仓库/固定提交/任务指针且保持单消费者；只能通知旧 session 的 hook 不满足本协议。发布文件不等于已经执行这一步，结束 session 是流程交接，不是关机或停止远程连接服务。

### 7.8 本次过渡

本修改由所有者明确要求设定协作方式，属于规则初始化，不冒充一次独立 S2R 审查。当前 NEXT_ACTIONS 的 S2R-REPRO 是一份有界任务，T0–T4 为内部子步骤；实验范围、停止条件和总预算不因该修改扩大。
若 agent 尚未领取，使用本协议所在的固定规划提交新建 session。若已经按旧 4462a7c 计划开工，不热替换其任务或并行再开一份；先让它保存实际进度、证据、消耗与阶段交接并结束，再由新 Chat 决定剩余一步。
旧 4462a7c 是可追溯的任务来源，不被悄悄改写。旧下载开场文件不再作为控制入口；未来只需给新角色仓库、指定规划提交或待审 PR，它应按仓库规则恢复上下文。

## 8. 文档生命周期与证据索引

更新本文件的当前状态必须带 SHA、环境、来源路径与证据层级（本次执行/历史记录/源码推断/未验证）；README 和 AGENTS 不复制一份进度。NEXT_ACTIONS 完成后归档该轮结果并替换为下一份经批准计划，不堆积多个“当前任务”。
旧 `HANDOFF_PROMPT_zh.md`、`docs/00_ACCEPTANCE.md`、`docs/05_ROADMAP.md`、`docs/REPORT_TEMPLATE.md` 的有效目标、硬约束、关卡和交付要求已经吸收，删除的是重复控制入口，不是取消验收或删除失败证据；旧内容仍在 Git 历史。
保留 `docs/01_ARCHITECTURE.md`、`02_FAIRNESS.md`、`03_RUNBOOK.md`、`04_NATIVE.md` 作为经修正的技术参考，不再使用“从零首轮安装/训练”指令支配当前工作。
[历史交付说明](delivery_docs/README.md)解释 S1R/S2 包内路径与仓库路径的区别。`delivery_docs/*`、旧协议、JUnit、日志、统计、训练清单、evidence 和 native 源码快照保留原字节，不把旧收据改写成当前版本通过。
模型 hash 必须区分训练 checkpoint、去 optimizer 后的推理导出与文件本身，不能因二者 hash 不同就篡改记录。历史包中的相对路径不等于当前 checkout 里有该文件。
本次整理审计见 `reports/docs_consolidation_audit.json`；它只记录静态文档/来源检查，不代表 S2R 已执行。第三方来源和许可见 [docs/SOURCES.md](docs/SOURCES.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
