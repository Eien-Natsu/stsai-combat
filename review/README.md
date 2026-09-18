# 离线复核入口（S1R）

本目录是复核端要实际运行的脚本，不是说明性文档。一个命令跑完整条链：

```bash
unzip stsai_s1r_review_<sha>.zip -d pkg
git clone pkg/repo.bundle repo && git -C repo checkout <HEAD of repo.bundle>
python pkg/review/run_review.py --repo repo --sources pkg/native_sources.tar.gz \
    --package pkg [--model pkg/model/policy_weights.pt]
```

## 顺序为什么是这样

```text
attachments  →  校验包内 MANIFEST.sha256（给了 --package 时）
native_build →  校验 native_sources 归档与逐文件哈希，把 engine_lock.json 的补丁序列
                按声明顺序应用到 PRE_PATCH 快照，再在临时目录里 cmake 构建
import       →  把构建出的模块放进 checkout 的 src/stsai，import stsai._lightspeed，
                并核对 build_info 的 revision 与补丁哈希
intent       →  用上一步校验过的补丁后源码路径重新生成意图表并比对
tests        →  跑全部 pytest，要求 native 用例真的被执行（零 skip）
counterfactual → 重放随包公开轨迹、复算 observation hash，并重跑 louse 反事实对
model_smoke  →  仅当给了 --model：加载 selected 权重并跑随包 12 条公开观测
```

先跑 pytest 再编译，会让 native 用例以 skip 通过、构建结果无人验证；
读一个已保存的 true/false 也不是"重放反事实"。所以顺序写死在脚本里。

## NOT_RUN 与 FAIL

- `FAIL`：步骤真的跑了并且失败。
- `NOT_RUN`：必需步骤在本机跑不了（缺 cmake、缺编译器、没给 --sources）。
  两者都让总退出码非零，不会打印"所有可运行检查通过"后放行训练。

本机没有 CUDA 只影响 GPU 相关的可选步骤，不影响上述必需步骤：离线复核只做
CPU 推理与 native 检查，不宣称复跑 GPU 训练。`game_differential_verified`
保持 false —— 构建成功不是原版一致性。

## 运行预算

复核只跑既有 pytest 与定向重放：单个 root 最多 128 步、每候选分布最多 4096 个
sampler seed（实际用 1024）、反事实对固定 4 个 seed。不重开随机碰撞扫描，不做
native 训练或强度评测。

## 脚本

| 文件 | 作用 |
|---|---|
| `run_review.py` | 上面那条链的编排与退出码 |
| `offline_native_build.py` | 校验快照、按序应用补丁、离线构建、安装模块 |
| `counterfactual_replay.py` | 重放公开轨迹、复算 hash、重跑反事实对 |
| `model_smoke.py` | 加载 selected 权重并比对随包期望值（仅训练轮） |
