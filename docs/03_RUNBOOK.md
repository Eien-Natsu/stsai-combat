# 操作手册

以下命令均在项目根目录和已激活 `.venv` 中运行。

## 0. 先验证，不直接长训

```bash
python -m stsai doctor --require-cuda --output runs/doctor.json
python -m pytest -q --junitxml=reports/target_pytest.xml
python scripts/smoke.py --output runs/smoke_cpu --device cpu
python scripts/smoke.py --output runs/smoke_cuda --device cuda
```

smoke 输出四局训练、两局验证、8 次更新、每策略四个评测场景。这是程序联通性测试，不是有效强度实验。`runs/smoke_*` 权重不得用于声称真实游戏能力。

## 1. 构建和 native 探针

```bash
python scripts/fetch_engine.py
python scripts/build_native.py --jobs 4
python -m pytest -q tests/test_native.py
python scripts/build_native.py --jobs 2 --sanitize
python scripts/benchmark.py --backend lightspeed_pilot --output runs/native_benchmark.json
python -m stsai collect --backend lightspeed_pilot --output data/native_probe \
  --count 16 --workers 2 --config configs/native_pilot.json
```

UBSan 版本用于排错，速度数据请重新构建普通 Release 后测量。首批收集有崩溃／非法动作／不支持状态时停止扩大。测试只覆盖现有范围，不能用删除 whitelist 来“修复”。

## 2. 分步运行第一轮

```bash
python -m stsai collect --backend lightspeed_pilot --output data/native/train_i0 \
  --count 128 --workers 2 --sample-actions --config configs/native_pilot.json
python -m stsai collect --backend lightspeed_pilot --split val --output data/native/val_i0 \
  --count 16 --workers 2 --config configs/native_pilot.json
python -m stsai train --backend lightspeed_pilot \
  --train-data data/native/train_i0 --val-data data/native/val_i0 \
  --output runs/native/model_i0 --device cuda --config configs/native_pilot.json
python -m stsai evaluate --backend lightspeed_pilot \
  --agents heuristic search model hybrid --checkpoint runs/native/model_i0/best.pt \
  --count 32 --device cuda --output runs/native/eval_i0 --config configs/native_pilot.json
python -m stsai mine --data data/native/train_i0 --output runs/native/failures_i0.json
```

`mine` 按死亡和预测／结果差异整理病例，不证明哪个动作是死因，也不自动把病例重加权回放。输出是一个 JSON 对象，不是逐行 JSONL。

训练日志包含总损失、policy／outcome／value 分项、验证 teacher agreement、GPU 峰值。`best.pt` 表示最低验证监督损失，**不是自动实战最强**。`last.pt` 用于续训。

## 3. 断点恢复与新一轮

同数据同结构恢复：

```bash
python -m stsai train --backend lightspeed_pilot \
  --train-data data/native/train_i0 --val-data data/native/val_i0 \
  --output runs/native/model_i0 --resume runs/native/model_i0/last.pt \
  --device cuda --config configs/native_pilot.json
```

需要更多更新时先复制配置并增大 max_updates / epochs；若已达到原上限，原配置不会自动继续。中断或 OOM 产生 `interrupted.pt` 时，检查损失／数据状态后显式使用它。改变数据目录或文件集合会改变 fingerprint；新数据用新 output 和 `--init-checkpoint`，而不是滥用 resume。

新一轮收集指定 `--checkpoint old/best.pt --iteration 1 --start 100000 --sample-actions`；训练传入当前与上一轮的 train 目录。验证用固定分布；模型替换依赖整场评测，不是仅 loss。

## 4. 最终盲测

模型选择完毕，才生成：

```bash
python -m stsai make-test-manifest --backend lightspeed_pilot \
  --count 1000 --output evaluation/final_manifest.json
python -m stsai evaluate --backend lightspeed_pilot --split test \
  --manifest evaluation/final_manifest.json --agents heuristic search model hybrid \
  --checkpoint runs/native/model_i0/best.pt --device cuda \
  --config configs/native_pilot.json --output runs/native/final_test
```

manifest 指定的 count 覆盖命令的 count。需要先满足 native 规则验证；即便此测试高分，也只对应两种敌人／受控卡组／限定遗物的 pilot 分布。

## 5. 资源与故障处理

先用 doctor 实际检测显存。正式短训练出现 OOM：微批次减半、累积加倍、保存新配置，重新测试；不要偷偷改成 CPU 然后报告 GPU 已跑通。不在第一次运行启用 torch.compile，先排除基础兼容问题。

教师采样每 worker 在 CPU 上加载一个模型；不要让每个进程各自创建大 GPU 副本。内存不足先减少 worker 和 shuffle buffer。并行效率必须实测；5070 不会自动加速 Python/C++ 环境状态转移。前几轮建议限制在 128→256→1,024 训练局，每轮以吞吐和强度证据决定扩大，不能直接照搬亿级样本目标。

No optimizer updates：有效批次比可读样本太大，减少 batch/accumulation 或增收数据。Nonfinite loss：停止，保存出错样本、日志、checkpoint，查 mask 和数值。大量截断：检查循环动作、预算和卡组；不能把未结束战斗一律算死亡后隐藏。

磁盘先留足依赖和数据空间；每轮报告实际目录大小。安装失败不自动升级驱动；列出检测到的版本和官方兼容信息，再决定授权操作。
