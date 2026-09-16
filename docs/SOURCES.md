# 已核查的一手资料

查阅日期：2026-09-16。下列网址是公开项目或官方文档。上游可能变化；目标机必须固定实际 commit。网页上游功能声明不是本项目验证结果。

## 引擎

- gamerpuppy/sts_lightspeed：<https://github.com/gamerpuppy/sts_lightspeed>
  - README 描述 C++17、规则模拟、载入战斗存档及现有搜索知道 RNG 状态；因此不能直接把其搜索当公平教师。
  - 上游声称覆盖所有 Ironclad 卡／敌人／遗物；本项目自己的 adapter 只允许有限白名单，二者不能混淆。
  - MIT 授权见上游 LICENSE.md；本包不再分发其源码，fetch 后保留许可证。
- 实际接口检索：
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/combat/BattleContext.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/src/combat/BattleContext.cpp>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/combat/CardInstance.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/combat/CardManager.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/combat/Monster.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/combat/Player.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/game/GameContext.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/include/sim/search/Action.h>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/src/sim/search/Action.cpp>
  - <https://raw.githubusercontent.com/gamerpuppy/sts_lightspeed/master/bindings/slaythespire.cpp>

其中 BattleContext 初始化的随机流关系、Monster 隐藏字段、Action 多选枚举均需要在锁定版本再审计。检索阅读不替代构建和运行验证。

## 游戏控制

- CommunicationMod：<https://github.com/ForgottenArbiter/CommunicationMod>
- 协议原文：<https://raw.githubusercontent.com/ForgottenArbiter/CommunicationMod/master/README.md>

官方 README 定义依赖、`ready` 握手、JSON 消息、PLAY/END/POTION/WAIT 等命令。项目 bridge 的合成测试依据该协议，未声称完成真实游戏联调。

## GPU / PyTorch

- PyTorch 2.7 官方发布说明：<https://pytorch.org/blog/pytorch-2-7/>
  - 官方说明新增 Blackwell 支持和 CUDA 12.8 wheel。
- PyTorch 官方历史版本安装：<https://pytorch.org/get-started/previous-versions/>
  - 提供 2.9.1 + cu128 组合。此处固定一个有据可查的目标基线，不主张它是当前最新版。
- NVIDIA GeForce RTX 5070 系列官方页：<https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/>
  - 实际目标机容量以 driver 查询为准；不从产品名推断移动／桌面版本。

本项目对算法和硬件资源的配置是工程选择；没有把任何上游营销吞吐数字当成本机测量。
