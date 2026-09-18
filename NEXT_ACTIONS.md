# 下一轮执行指令：S2R-REPRO

状态：待执行，不是完成报告。执行者：实施 agent；完成后交 ChatGPT review。
主线与长期约束只见 [PROJECT_MAINLINE.md](PROJECT_MAINLINE.md)。本轮目的：把已有 S2 结果变成有来源、可获取、可在干净环境复核的交付，不启动新的学习实验。
基线：包含本轮文档整理的 `s2/fixed-budget-data` 后续提交；代码/历史证据锚点为 `de266c4cf79fe3543d6fcfc1b69028c702e5d4d0`。不要从仍停在初交付的 main 另起一套实现。
先确认文档 PR 已合入目标开发分支，或由所有者明确指定该文档 PR HEAD；记录完整 SHA。不要自动合并本 PR、旧 PR #1 或实现主线。

## 1. 为什么现在做这个

S2 固定预算对照已报告证据不足；这轮不通过重训、补 seed 或重跑 4096 场改变结论。
本次文档检查发现 `scripts/make_s2_package.py` 的 28 项 FILES 必需输入有 7 项在干净 checkout 缺失。根目录无这些产物可能是交付设计，不等于实验造假；但必须有可访问、锁定的外部来源，不能继续把 checkout 当成完整 review 包。
以下路径是**打包脚本输入契约，不是文件已经存在的声明**：

| 包内目标 | 当前打包脚本查找的缺失来源 |
| --- | --- |
| `data/initial_scenarios.json.gz` | `runs/s2/package_data/data/initial_scenarios.json.gz` |
| `data/composition_and_shards.json` | `runs/s2/package_data/data/composition_and_shards.json` |
| `data/coverage.json` | `runs/s2/package_data/data/coverage.json` |
| `model/D384_s17_selected.pt` | `model/D384_s17_selected.pt` |
| `evaluation/scenarios.json.gz` | `runs/s2/package_data/evaluation/scenarios.json.gz` |
| `evaluation/episodes.jsonl.gz` | `runs/s2/evaluation/episodes.jsonl.gz` |
| `evaluation/decision_latency.jsonl.gz` | `runs/s2/evaluation/decision_latency.jsonl.gz` |

权威 S2 协议是 `reports/s2_volume_protocol.json`，不是较早 louse 修复的 `s2_protocol.json`。历史 SUMMARY/INDEX 内的路径是 ZIP 布局；不可拿缺路径自动替换为 S1/S1R 文件。

## 2. 硬预算与停止条件

新增训练 runs=0、优化 updates=0、新采集=0、整场强度评测=0；不创建/读取最终 P6 manifest，不做 DAgger/hybrid/leaf value/容量/teacher/reward/场景分布修改。
允许读取既有记录、复算统计、离线构建、原有 pytest/定向反事实重放和代表模型的 12 条 CPU smoke。编译并行不超过 2；统计/推理 torch 线程设 1；不使用 GPU 训练、云资源或驱动变更。
完整冷复核最多 2 次（首次及修复后一次），单个外部步骤 timeout 1800 秒，全部完整复核合计最多 90 分钟。不能通过新命令绕过上限；耗尽即带日志交回 review。
缺少真实模型/逐场原始结果、哈希不符、没有隔离环境或需系统级安装时立即停止相关阶段，记录 BLOCKED/NOT_RUN；不得重训“补回同一个权重”、从汇总反造逐场结果或删除失败步骤。

## 3. 按顺序执行

### T1 — 固定基线，盘点并恢复已有输入

在实施者自己的干净分支操作，先记录 Git HEAD/base/status、Python/OS/编译器和依赖版本。只在明确授权的原执行目录、已交付 ZIP 或仓库发布附件里找产物；不要扫描无关用户目录，不索取或读取密钥。
新增 `reports/s2r/input_receipt.json`：每个输入记录仓库路径/包内路径/外部来源、可获得性、字节数、期望与实测 SHA256、来源轮次/commit、是否由原包恢复、校验结果。保留原包 manifest/provenance 的来源，不以本轮新算的 hash 冒充旧承诺。
恢复上表 7 项，以及完整包 manifest/provenance。训练分片和另外五个权重不要求全上传；明确区分“逐场记录可复算”和“所有模型已重载”。D384_s17 必须验证推理导出 hash 与 checkpoint hash 的不同语义。
原执行机/ZIP 能提供时只复制并校验，不改内容；来源缺失就列出具体缺项、预期 hash 和所需提供者后停止，不新建样本或选择替代模型。可确定性重建的索引也需记录为重建并对照冻结 hash，不冒充原字节。

### T2 — 明确 checkout 与交付包的契约

只修复 `scripts/make_s2_package.py`、必要的 provenance/路径解析、`review/` 工具及相应测试；不要修改模拟器/训练算法或历史统计。目录分组后的路径以当前树为准，检查 `audit/`→`evidence/`、native 源码和 delivery_docs 的所有引用，不只修一个入口。
建立机器可读的必需输入清单，支持明确指定已验证的 artifact 根目录；不能依赖原执行机的绝对路径、隐式 `runs/` 或已有二进制。可选择仓库可追溯小产物或一个锁定 SHA256 的发布附件，不要求把全部 runs 提交进 Git。
新增 `review/check_review_inputs.py`（这是本轮待实现入口）：接受 `--repo`、`--package`、`--out`，校验来源清单、路径范围和所有必需内容。缺失/摘要不符/错误版本/错误模型须非零退出，不能以可选跳过冒充完整包。
新增输入契约回归：缺权重、缺逐场记录、文件篡改、S1R/旧语义替代、仅汇总文件、路径越界/不安全归档成员分别必须被拒绝；原始异常和失败日志不得抹掉。
当前 `run_review.py` 未转发编译并行参数，而底层默认最多 4。为其新增并测试 `--jobs` 转发给 `offline_native_build.py`，本轮使用 2；不要把下面的新参数误称为旧版已支持。

### T3 — 冷复核与独立复算

使用不挂载 SSH、keyring、GitHub token 的隔离环境；不要在有远程写凭据的 Windows shell 中执行未审项目代码。优先复用已批准的 Debian/Python 3.12/GCC 12 环境，不能把它的结果标成 GCC 14 或原生 Windows/MSVC 结果。
先校验 ZIP 成员和 manifest，再安全解包；从 bundle/指定提交建立全新 checkout，不复用旧 build、third_party 或安装好的 native 模块。依赖安装仍受主线授权约束。
以下是 **T2 实现并通过契约测试后** 的执行模板；PKG、CHECKOUT、OUT 替换为隔离环境内的绝对路径，OUT 必须是新的轮次输出目录：

```bash
python review/check_review_inputs.py --repo "$CHECKOUT" --package "$PKG" --out "$OUT/input_receipt.json"
python review/run_review.py --repo "$CHECKOUT" --package "$PKG" \
  --sources "$PKG/native_sources.tar.gz" --model "$PKG/model/D384_s17_selected.pt" \
  --jobs 2 --timeout 1800 --work "$OUT/work" --receipt "$OUT/review_receipt.json"
python review/recompute_s2.py --package "$PKG" --out "$OUT/recomputed_s2.json"
```

每步必须检查退出码；前置失败不继续启动后续步骤。每条命令保留 cwd、解释器、开始/结束、退出码、完整 stdout/stderr，PASS/FAIL/NOT_RUN/TIMEOUT 分开。
复核顺序保持附件校验→PRE_PATCH+5 补丁冷构建→真实 import/revision/hash→意图表→全量 pytest→公开反事实→12 条模型 smoke；代表权重是本轮必需项，不通过省略 `--model` 获得成功。
原 277 项测试不删、不 skip 以降低门槛；新增测试使数量可增加，但 PASS 总数不是唯一标准。检查 native/回归测试确实执行，失败与必需 NOT_RUN/TIMEOUT 均使本轮不通过。
复算前先检查两个集合×8 个策略×256 场的键集合完整且无重复，共 4096 条，不允许缺对后只统计剩余样本。核对场景清单、胜/负/截断、效用、动作哈希与延迟输入对应关系。
按原协议复算 seed 内配对及先跨 seed 平均再按场景 bootstrap 的联合区间（20,000 次，seed 20260920）；与 `reports/s2_paired_summary.json` 比较并输出数值差异。不得改阈值、剔除不利场景、把三 seed 当独立 768 场或改变“不足”判定。
GCC 14.2 若在已有授权环境可用，可用于第二次完整复核；不可用就明确 NOT_RUN，不能从源码扫描或 GCC 12 成功推断其通过。不是为得到绿灯购买机器或安装系统编译器的许可。

### T4 — 形成可审查交付

写 `reports/s2r/SUMMARY.md`、`input_receipt.json`、`review_receipt.json`、`recomputed_s2.json`、`comparison.json`、JUnit 和压缩完整日志，更新主线“当前状态”但不覆盖历史 S2 证据。未执行项保留；输入缺失时也要交付阻塞清单，不能写空白成功收据。
交付一个有来源清单的复核包，或固定版本的 GitHub 附件与 hash；小文件留 Git、大产物按清单取用。不把本轮新代码/文档 hash 填回旧包 manifest，新的 manifest/provenance 单独生成。

## 4. 完成标准

输入闭环：7 项缺失输入各有真实来源与旧摘要验证；不能仅“已生成文件”。外部附件缺失时结论为 blocked，保留原 S2 记录但不宣布已复现。
工程闭环：新输入契约的负例都被拒绝；干净环境完整链路成功、native 零 skip、代表模型 12 条 smoke 通过，完整命令/失败/超时记录可取。
统计闭环：4096 条键完整无重复；独立复算与原记录在预先声明的数值容差内一致；任何不一致保留差异与调查结论，不静默改历史值。容差只能覆盖数值舍入，不能跨过零改变判定。
范围闭环：新训练/优化/采集/整场强度评测均为 0；引擎、语义版本、数据、teacher、模型选择规则和最终 P6 状态不变。GCC 14、CUDA/原游戏的未执行项仍明确列出。
交接闭环：PR 指向经批准的实际基线分支，完整 HEAD/request/证据链接齐全；review 未完成前冻结本轮。ready 标签目前只表示交接，由用户在 Chat 发起 review，不承诺自动唤醒。

## 5. 给 reviewer 的最终回复模板

```markdown
## 本轮结论
S2R-REPRO: ready-for-review 或 blocked；固定 HEAD / base / request ID。
## 恢复了什么
7 项输入逐项列真实来源、旧/新 hash 核验和外部存放位置。
## 改了什么
文件与缺陷对应；为什么不改变 S2 的实验语义。
## 实际验证
环境、命令、退出码、完整日志；构建/import/pytest/native skip/模型 smoke/独立复算。
## 没验证什么
GCC 14 / CUDA / 原游戏 / 另外五个模型的加载，逐项写实际状态。
## 统计结论
复算是否仍是固定预算下证据不足；不一致项及原因。
## 资源和交付
本轮实际次数/耗时；PR 链接、commit、附件文件名/字节数/SHA256、读取顺序。
```

以 GitHub PR 为主要交付，Chat 中不散贴大量日志。需要聊天上传时，优先一个 ZIP + 一份简短 SUMMARY；沿用原 S2 项目预算不超过 40 MB / 40 包内文件，但这不是对当前 Chat 上传上限的保证。先压缩日志，超出时使用已授权附件存放方式，不删失败证据；不上传游戏/存档/密钥/venv/编译产物/optimizer。
到此停止并交回 review。后续优化预算或数据实验只列为候选问题，不能自行开始训练。
