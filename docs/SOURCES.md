# 历史来源索引与当前源码清单

公开资料为初交付时（2026-09-16）的检索入口，本次文档整理没有重新核验这些网页的最新内容。当前目标和状态只见 [主线](../PROJECT_MAINLINE.md)；网页声明不替代本项目实测。

## 引擎与当前离线快照

上游项目：<https://github.com/gamerpuppy/sts_lightspeed>。本项目使用锁定规则状态转移，而不直接采用知道真实 RNG 的上游搜索器作公平教师；上游覆盖声明不等于本适配器白名单覆盖。
实际 revision、子模块与补丁见 [engine_lock.json](../engine_lock.json)。当前仓库**已分发** [native/native_sources.tar.gz](../native/native_sources.tar.gz) 中的离线最小源码，逐文件来源/许可证/摘要见 [manifest](../native/native_sources_manifest.json)，不再使用初交付的“本包没有上游源码”声明。
历史接口检索涉及 BattleContext、CardInstance、CardManager、Monster、Player、GameContext 以及 sim/search/Action 和 bindings/slaythespire.cpp；以快照的锁定版本核对，不把漂移的 master 视为已验证依赖。
修补、构建和隐藏字段审计都需绑定该版本；读取头文件或一次构建成功不等于原游戏差分。

## 游戏控制（历史参考）

CommunicationMod：<https://github.com/ForgottenArbiter/CommunicationMod>，协议入口为其 README。桥接基于 ready/JSON/动作命令协议，但本项目的合成协议测试不是原游戏联调证据。

## GPU / PyTorch（历史参考）

- PyTorch 2.7 发布说明：<https://pytorch.org/blog/pytorch-2-7/>。
- 历史版本安装页：<https://pytorch.org/get-started/previous-versions/>。
- RTX 5070 系列产品页：<https://www.nvidia.com/en-us/geforce/graphics-cards/50-series/rtx-5070-family/>。

本项目历史记录采用 2.9.1+cu128，而不是宣称它是当前最新版；实际兼容、显存和吞吐以对应环境的前后向/测量日志为准。不能用上游营销数字填本机性能表。
第三方许可与分发说明见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。本次仅修正文档库存与角色，不修改归档源码或许可证。
