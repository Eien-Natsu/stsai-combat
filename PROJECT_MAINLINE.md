# STSAI 唯一主线控制文档

文档版本：1。状态核对基线：`s2/fixed-budget-data@de266c4cf79fe3543d6fcfc1b69028c702e5d4d0`。
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

## 7. 实施 agent 与 ChatGPT 的统一协作

所有者决定目标、资源、规则变更和合并；实施者负责独立分支上的代码与实际证据；reviewer 负责固定版本审查和可执行下一轮计划，不默默修改实现或授予新预算。
当前可用的是用户在 Chat 发起的一轮操作，通过已授权 Remote Desktop Commander 调用本机 Git/gh。clone、push、开 PR 已有实测；评论/标签状态转换仍须逐项验证，不能从 PR 创建成功推断全部写操作成功。
期望方案 A 为 `pull_request/labeled` 且标签为 `agent-ready-for-review`。**事件订阅尚未创建、无任务 ID、未端到端验收。** 贴标签或连接设备不自动唤醒 Chat；不擅自改为轮询、daemon、Codex 或付费 API reviewer。

### 7.1 交接与状态

实施者 push 完成后，更新 [.github/pull_request_template.md](.github/pull_request_template.md)：目标、run/request ID、完整 HEAD、目标分支、上一轮计划、验证命令/结果/证据、未验证项和已知问题；最后贴 ready 标签，冻结代码与 handoff。
默认只接收本仓库来源、打开且非 draft 的 PR。文档过渡期允许经所有者授权将 `s2/fixed-budget-data` 作为 base；以后默认 main。目标分支必须在交接中明确，不能隐式重定向。
协议状态标签互斥，其余标签保留：ready → reviewing → needs-work / review-approved / blocked，完整名称均为 `agent-` 前缀（ready 为 `agent-ready-for-review`）。无状态标签表示实施中，不代表通过。
`agent-review-approved` 不是 GitHub APPROVE，不是合并授权，不等于 G0–G5 全过；approved 或 blocked 时停止自动实施。禁止自动 merge、auto-merge、force-push、直接写 main 或反复改标签造成事件风暴。

### 7.2 版本固定、授权与去重

reviewer 先核实请求来源授权，读取当前 PR 状态及已批准基线规则，记录 repo、PR、HEAD、BASE、request ID、主线版本、唯一 run ID；手动运行注明 `manual-chat`，不伪造事件任务 ID。
将 PR body 的 CRLF/CR 归一为 LF，以 UTF-8 计算 SHA256，单独记录 handoff_sha256，不回填 body 造成自引用。handoff 声明的 SHA 不符则阻塞，不自行审另一版本。
检查受信任 reviewer 的认领/完整结果，以 `(repo, PR, HEAD, BASE, request ID, handoff_sha256, 主线版本)` 去重；同一 PR 串行，评论与标签不是原子锁。身份共享时标记不能证明独立审查，仍由所有者确认。
认领需记录 UTC 时间/run ID，再换 reviewing。发布前复查 HEAD/BASE/body/request/开闭状态；变动则旧结果只标 stale，等新的明确交接。实施者执行前也要复核快照，避免检查后更新的竞态。
同快照的正常重复事件不重审；CI 补齐、base 变动或所有者要求复审时使用新 request ID 并写原因。评论成功而标签失败时只修标签，不能重复生成计划。
临时错误、缺权限/证据、超时分别记录，不写完成标记。遗留 reviewing 经确认旧运行停止后恢复；每次交接只做一轮，最多连续 3 轮自动修复，同一阻塞两轮无进展或需扩大权限/资源就交回所有者。

### 7.3 必须交付的 review 与下一轮计划

同一 PR 发布一份完整结果：`Review`（Critical/Important/Minor，路径/行号/条件/影响/证据）→ `Verification`（实际读了什么、CI 被测 SHA、亲自跑的命令、仅观察的结果、NOT_RUN 项）→ `Next Agent Plan`（顺序、文件、改动、预算、验证、完成条件）→ `Completion Criteria` → `Reviewed Snapshot`。
Snapshot 必须含 repo/PR/HEAD/BASE/request/handoff_sha256/主线版本/trigger/run。最终标记格式如下，所有占位符须替换：

```html
<!-- agent-review mainline=1 pr=NUMBER head=SHA base=SHA request=ID handoff=SHA256 status=complete verdict=needs-work -->
```

标记不是签名或授权。blocked/失败/过期不能冒充完成；每条确定缺陷和待验证疑点分开。写回失败则把结果留在 Chat 并明确说明，不把“已经起草”写成“已发到 GitHub”。
最新可信 review 的计划需同步到 NEXT_ACTIONS.md 才成为下一轮执行文档；实施者只在自己分支做该同步，并核对匹配快照。不得自行添加新目标或把这次计划扩展成无限循环。

## 8. 文档生命周期与证据索引

更新本文件的当前状态必须带 SHA、环境、来源路径与证据层级（本次执行/历史记录/源码推断/未验证）；README 和 AGENTS 不复制一份进度。NEXT_ACTIONS 完成后归档该轮结果并替换为下一份经批准计划，不堆积多个“当前任务”。
旧 `HANDOFF_PROMPT_zh.md`、`docs/00_ACCEPTANCE.md`、`docs/05_ROADMAP.md`、`docs/REPORT_TEMPLATE.md` 的有效目标、硬约束、关卡和交付要求已经吸收，删除的是重复控制入口，不是取消验收或删除失败证据；旧内容仍在 Git 历史。
保留 `docs/01_ARCHITECTURE.md`、`02_FAIRNESS.md`、`03_RUNBOOK.md`、`04_NATIVE.md` 作为经修正的技术参考，不再使用“从零首轮安装/训练”指令支配当前工作。
[历史交付说明](delivery_docs/README.md)解释 S1R/S2 包内路径与仓库路径的区别。`delivery_docs/*`、旧协议、JUnit、日志、统计、训练清单、evidence 和 native 源码快照保留原字节，不把旧收据改写成当前版本通过。
模型 hash 必须区分训练 checkpoint、去 optimizer 后的推理导出与文件本身，不能因二者 hash 不同就篡改记录。历史包中的相对路径不等于当前 checkout 里有该文件。
本次整理审计见 `reports/docs_consolidation_audit.json`；它只记录静态文档/来源检查，不代表 S2R 已执行。第三方来源和许可见 [docs/SOURCES.md](docs/SOURCES.md)、[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
