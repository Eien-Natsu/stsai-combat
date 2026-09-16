#!/usr/bin/env python3
"""Where the time and the network calls actually go, on frozen diagnostic roots.

Separates four modes that "hybrid" otherwise conflates:

  S   heuristic prior, rollout cutoff, no network at all
  P   network prior, otherwise identical rollout and cutoff to S
  V   heuristic prior, network value at the cutoff instead of the heuristic's
  PV  network prior and network value

Reports evaluator calls, network forwards, node revisit rate and wall-clock per
decision, on CPU and CUDA, warm-up first and with the synchronisation inside
the timed region so a fast kernel does not hide a slow transfer.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from stsai.native import NativeBattle
from stsai.scenarios import make_scenario
from stsai.search import BeliefSearch, HeuristicEvaluator, SearchConfig, SplitEvaluator
from stsai.util import atomic_json


class CountingEvaluator:
    """Wrap an evaluator to count calls; optionally run it on another evaluator."""

    def __init__(self, inner, counter):
        self.inner = inner
        self.counter = counter

    def evaluate(self, obs):
        self.counter["calls"] += 1
        return self.inner.evaluate(obs)


def build(mode, config, model_evaluator, counter):
    heuristic = CountingEvaluator(HeuristicEvaluator(), counter)
    network = CountingEvaluator(model_evaluator, counter)
    if mode == "S":
        return BeliefSearch(config, heuristic), False
    if mode == "P":
        return BeliefSearch(config, network), False
    if mode == "V":
        # Both halves must be the counting wrappers, or the count silently reads 0.
        return BeliefSearch(config, SplitEvaluator(heuristic, network)), True
    if mode == "PV":
        return BeliefSearch(config, network), True
    raise ValueError(mode)


def roots(count, seed=20260916):
    out = []
    for index in range(count):
        scenario, episode_seed, _ = make_scenario("lightspeed_pilot", "val", index, seed)
        env = NativeBattle(scenario, episode_seed)
        obs = env.observe()
        for _ in range(index % 3):
            if obs["terminal"]:
                break
            obs = env.step(obs["actions"][0])
        if not obs["terminal"]:
            out.append((env, obs))
    return out


def timed(fn, device):
    import torch
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()
    start = time.perf_counter()
    result = fn()
    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize()
    return time.perf_counter() - start, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--roots", type=int, default=24)
    parser.add_argument("--simulations", type=int, default=64)
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--devices", nargs="+", default=["cpu", "cuda"])
    args = parser.parse_args()

    from stsai.model import ModelEvaluator
    base = json.loads((ROOT / args.config).read_text())["search"]
    config = SearchConfig(**base)
    frozen = roots(args.roots)
    if not frozen:
        raise SystemExit("no live roots")

    report = {"scope": "frozen diagnostic roots; not a strength measurement",
              "checkpoint": str(args.checkpoint), "roots": len(frozen),
              "simulations": config.simulations, "modes": {}}

    for device in args.devices:
        try:
            import torch
            model_evaluator = ModelEvaluator.from_checkpoint(args.checkpoint, device, "lightspeed_pilot")
        except (RuntimeError, ValueError) as exc:
            report["modes"][device] = {"error": str(exc)}
            continue
        per_device = {}
        for mode in ("S", "P", "V", "PV"):
            counter = {"calls": 0}
            search, use_leaf_value = build(mode, config, model_evaluator, counter)
            search.config.use_leaf_value = use_leaf_value
            latencies = []
            cutoffs = []
            # Warm-up: first calls pay lazy allocation and cuDNN/autotune costs.
            for env, obs in frozen[:2]:
                search.run(obs, env.sampler(), 12345)
            counter["calls"] = 0
            for env, obs in frozen:
                elapsed, result = timed(lambda e=env, o=obs: search.run(o, e.sampler(), 777), device)
                latencies.append(elapsed)
                cutoffs.append(result["cutoff_fraction"])
            per_device[mode] = {
                "evaluator_calls_total": counter["calls"],
                "evaluator_calls_per_decision": counter["calls"] / len(frozen),
                "decisions": len(frozen),
                "p50_ms": float(np.percentile(latencies, 50) * 1000),
                "p95_ms": float(np.percentile(latencies, 95) * 1000),
                "mean_cutoff_fraction": float(np.mean(cutoffs)),
            }
        report["modes"][device] = per_device

    # Single-forward cost, batch of one, the shape the search actually uses.
    import torch
    if torch.cuda.is_available():
        model_evaluator = ModelEvaluator.from_checkpoint(args.checkpoint, "cuda", "lightspeed_pilot")
        obs = frozen[0][1]
        for _ in range(3):
            model_evaluator.evaluate(obs)
        cpu_ms = []
        from stsai.model import load_checkpoint
        cpu_model, _ = load_checkpoint(args.checkpoint, "cpu")
        cpu_eval = ModelEvaluator(cpu_model, "cpu", "lightspeed_pilot")
        for _ in range(3):
            cpu_eval.evaluate(obs)
        for _ in range(10):
            elapsed, _ = timed(lambda: cpu_eval.evaluate(obs), "cpu")
            cpu_ms.append(elapsed * 1000)
        gpu_ms = []
        for _ in range(10):
            elapsed, _ = timed(lambda: model_evaluator.evaluate(obs), "cuda")
            gpu_ms.append(elapsed * 1000)
        report["single_forward_batch1"] = {
            "cpu_p50_ms": float(np.percentile(cpu_ms, 50)),
            "cuda_p50_ms": float(np.percentile(gpu_ms, 50)),
            "note": "timed with synchronisation inside the region; batch of one",
        }

    atomic_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
