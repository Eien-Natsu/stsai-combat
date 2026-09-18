# 技术参考：native 与实机接口

当前目标、验证层级与授权见 [主线](../PROJECT_MAINLINE.md)。本页以 `s2/fixed-budget-data@de266c4` 的接口为参考，不再描述初交付的“尚未编译候选”。

## 锁定与白名单

锁定引擎与 5 个顺序补丁见 [engine_lock.json](../engine_lock.json)。[离线源码 manifest](../native/native_sources_manifest.json)声明 PRE_PATCH 快照；复核先校验再应用补丁，不能重复应用到已打补丁的源码。
`native/bridge.cpp` 的 23 个卡牌 ID 为：STRIKE_RED、DEFEND_RED、BASH、ASCENDERS_BANE、POMMEL_STRIKE、SHRUG_IT_OFF、IRON_WAVE、CLEAVE、UPPERCUT、CARNAGE、TWIN_STRIKE、METALLICIZE、IMPERVIOUS、GHOSTLY_ARMOR、DISARM、INFLAME、HEAVY_BLADE、ANGER、WHIRLWIND、THUNDERCLAP、BLUDGEON、SLIMED、DAZED。后两项包括遭遇生成的状态牌，不等于 23 种常规可选卡。
17 种遭遇包括 CULTIST、JAW_WORM、TWO_LOUSE、THREE_LOUSE、BLUE_SLAVER、RED_SLAVER、EXORDIUM_THUGS、EXORDIUM_WILDLIFE、TWO_FUNGI_BEASTS、LOOTER、GREMLIN_GANG、SMALL_SLIMES、LOTS_OF_SLIMES、LARGE_SLIME、GREMLIN_NOB、LAGAVULIN、THREE_SENTRIES；不再只有两种单敌人。
场景生成器见 `src/stsai/scenarios.py`：starter/swarm/elite/mixed 与独立卡组族组合，受控 A20、Act 1/floor 1、无药水。只涵盖适配器允许的资源/阶段，不是自然整局分布或完整铁甲能力。
规则状态转移由锁定引擎执行，`hints.py` 只提供公开估计；扩大 hints/枚举不能替代状态、选择阶段、采样与规则回归。

## 构建与证据

S2 保存了 GCC 12.2 的构建/import/pytest/反事实证据，见主线索引；不是所有机器开箱即用，也不是 GCC 14/MSVC 已验证。源码扫描不能代替真实工具链构建。
保持 base revision、补丁顺序与逐补丁 SHA 清晰。不要为过编译把真实状态置为常数，不以 native skip 掩盖缺模块；构建成功须真实 import 并核对 build_info。
敌人隐藏字段与公开历史候选模型见 [信息边界](02_FAIRNESS.md)；目前仍声明近似，不是原游戏联合后验。

## 原游戏差分与桥接缺口

`compare_traces.py` 只比较已经对齐的公开轨迹，不实现任意场景注入、公开状态恢复或两端 action ID 映射。须独立合法原游戏夹具，统一初始状态、动作脚本、稳定输入点、取整、牌区、阶段和战后回血语义。
确定性与受控随机轨迹分开，真实游戏日志不能由同一模拟器生成两份冒充。规则诊断可隔离使用真值，但不能进入策略/teacher。没有这些证据时 `game_differential_verified=false`。
CommunicationMod 相关入口在 `src/stsai/bridge.py`，协议测试不是实机联调。默认观察；开启执行、配置游戏路径或触碰存档均需明确授权，stdout 只用于协议而非日志。
实机桥与 native 白名单不是同一覆盖保证；不得把模拟器支持 17 遭遇解读为真实游戏已全部支持。桥接目前是受限纯模型推理，不是实机 MCTS。
`NativeBattle` 从受控初始 scenario 构造，缺少经审计的任意实机公开历史到 belief root 的恢复接口。未来搜索接入不能通过读取真实未来牌序/完整存档绕过这个缺口。
