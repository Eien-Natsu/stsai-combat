# 原版模拟器和实机接口：必须完成的验证工作

## 为什么没有直接使用现成搜索器

上游 README 明确注明现有 tree search 会知道游戏 RNG 状态。因此本项目只复用规则状态转移，不直接拿该搜索器作公平教师。上游现成 Python binding 主要暴露 GameContext / 搜索代理，不能假定有我们需要的稳定战斗 snapshot／step／clone 协议；本包提供独立 pybind 接口。

`native/bridge.cpp` 根据检索到的实际公开头文件编写，不是空函数；但发布环境未能获取依赖进行编译。因此 C++ API 兼容、链接、运行时状态正确性均待目标 AI 验证。发布包不声称绑定已编译通过，不包含预编译库。

## 原版 pilot 卡牌白名单

```text
STRIKE_RED        DEFEND_RED       BASH             ASCENDERS_BANE
POMMEL_STRIKE     SHRUG_IT_OFF     IRON_WAVE        CLEAVE
UPPERCUT         CARNAGE          TWIN_STRIKE      METALLICIZE
IMPERVIOUS       GHOSTLY_ARMOR    DISARM           INFLAME
HEAVY_BLADE      ANGER            WHIRLWIND        THUNDERCLAP
BLUDGEON
```

规则执行委托上游；`hints.py` 只提供模型特征和启发式估计，不替代真实伤害／合法性。新增卡不能仅加入 hints：必须检查是否产生新卡、选择请求、状态、计数或改变抽牌信息。

敌人仅 Cultist / Jaw Worm；遗物仅起始 Burning Blood；native 无药水；不接受复杂选择。reference 里的三种药水和额外状态牌不代表 native 已支持。

所有 native 场景是受控战斗快照，固定 Act 1 / floor 1 / 普通房间。Burning Blood 战后回血是否属于 BattleContext 的终局 HP 需要差分确认；正式战斗指标应固定为同一语义（建议在自动战后回血前），不能把一个后端的战前／战后 HP 混到另一个后端。

## 编译排错步骤

1. `fetch_engine.py` 用 Git 下载、锁定完整 SHA，json 子模块也记录 SHA。不使用上游老 pybind11 子模块，使用当前 venv 的 pybind11。已有未提交改动时拒绝覆盖。
2. `build_native.py` 检查实际 HEAD 等于 lock，构建后强制 import 再执行 native pytest，避免“编译没得到库、测试全 skip 也算成功”。
3. API 差异以锁定 commit 的真实声明为准，重点检查 Action 命名空间／枚举、GameContext 构造、Deck remove/obtain、CardInstance 方法、Monster DamageInfo、BattleContext 队列／复制语义。
4. 不要为过编译而把状态字段设成随意常数。player class、房间／地图条件、起始抽牌、遗物初始化必须根据上游实际流程验证。
5. 本工程修补直接提交；上游修补同时保存 patch 和 base SHA。若提交了本地上游补丁，更新 engine_lock 的 revision 并记录 original_upstream_revision 和补丁 hash。不能让构建记录误称未改动上游。
6. 随机回放发现不支持状态，先加最小复現与测试，再扩展，而不是禁用检查。

## 原游戏差分如何落地

本包的 `compare_traces.py` 接受两个**已经对齐的公开观察 JSONL**，并报告字段路径差异。它并没有实现原游戏任意场景注入、C++ 从任意公开状态恢复、统一两端 action ID。

接手 AI 必须实现一个独立原版夹具／调试 Mod：在合法本地游戏中创建指定战斗初始状态，按动作脚本推进到稳定输入点，导出公开状态；与模拟器执行相同设置并比较。先锁定确定性动作测试，后验证洗牌／随机怪物行为。必要时受控测试可读取真值 RNG 做**规则一致性诊断**，但这些字段不得进入策略／teacher／训练数据；该诊断不算公平实战。

统一两端规范化：card id／升级／变费／X费、牌区多重集与已知顺序、power ID／计数、敌人槽位、伤害取整、阶段终止时机、自动战后回血。C++ 和实机的动作内部 ID 不同，要按 kind/source/target/selection 对齐，不比较原始 bits 与字符串。真实轨迹独立保存证据，不能拿同一模拟器生成两个文件冒充差分。

## CommunicationMod

官方协议是 Mod 启动外部进程，通过 stdin 发送 JSON、从 stdout 读取命令。进程先输出 `ready`；PLAY 手牌索引从 1 开始，敌人索引从 0 开始。游戏本体、ModTheSpire、BaseMod 和 CommunicationMod 须合法安装。版本及源码来源见 SOURCES。

默认只观察：

```bash
python -m stsai bridge --log runs/live/observe.jsonl
```

把上述命令改为目标机解释器和绝对项目路径，配置到 CommunicationMod 启动命令中。**不能凭空假定用户安装目录**；自动检测或查实际配置文件。stdout 只能输出协议命令；日志写文件／stderr。不要在用户主存档上自动测试。

原版训练模型且完成联调后才显式启用：

```bash
python -m stsai bridge --checkpoint runs/native/model_i0/best.pt \
  --device cpu --execute --log runs/live/execute.jsonl
```

该实机桥目前只做**纯模型推理**，不是实机 MCTS。它只接受严格 pilot 白名单，拒绝额外遗物、药水、未知意图、选择界面。游戏返回错误时暂停；只观察模式不发送 PLAY/END。协议已用合成 JSON 测试，尚未在真实游戏验证。

实机 MCTS 的缺口是从合法可观测历史构建 native belief root。现有 NativeBattle 构造器只能从受控初始 scenario 开始，不能任意 load live combat。必须新增、审计该恢复接口后才能把搜索接到实机。不要在实机阶段偷加载含未来牌序的原始存档作为“捷径”。
