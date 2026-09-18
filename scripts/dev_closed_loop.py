#!/usr/bin/env python3
"""Closed-loop development evaluation over 256 frozen rollout scenarios.

These scenarios are a DEVELOPMENT set: they are materialised and hashed before
any candidate is scored, they never enter training, and they are not the final
test split. Reusing one development set for many decisions is how it slowly
becomes a training set, so the file records that it has been used.

Every agent plays the same scenario with the same episode seed. Different
policies diverge afterwards, so what is paired is the initial condition, not the
random future. Pure-network inference runs on CPU FP32, the measured-faster
option at batch one on this host; a GPU comparison is reported separately
rather than being mixed into the same latency column.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from stsai.objective import terminal_utility
from stsai.scenarios import make_scenario, make_env
from stsai.search import BeliefSearch, HeuristicEvaluator, SearchConfig
from stsai.util import atomic_json, digest

DEV_MASTER_SEED = 20260917
MAX_ACTIONS = 256


def freeze_scenarios(count):
    out = []
    for index in range(count):
        scenario, episode_seed, family = make_scenario("lightspeed_pilot", "val", index, DEV_MASTER_SEED)
        out.append({"index": index, "family": family, "episode_seed": episode_seed,
                    "scenario": scenario, "encounter": scenario["encounter"],
                    "hp": scenario["hp"], "deck_size": len(scenario["deck"])})
    return out


def step_episode(env, choose, max_actions=MAX_ACTIONS):
    obs = env.observe(); latencies = []
    for _ in range(max_actions):
        if obs["terminal"]:
            break
        start = time.perf_counter()
        index = choose(obs)
        latencies.append(time.perf_counter() - start)
        obs = env.step(obs["actions"][index])
    return obs, latencies


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/dev_closed_loop")
    parser.add_argument("--scenarios", type=int, default=256)
    parser.add_argument("--matrix", default="runs/matrix")
    parser.add_argument("--model-dirs", nargs="+", default=None,
                        help="explicit checkpoint directories; default is every cell under --matrix")
    parser.add_argument("--baselines", nargs="+", default=["heuristic", "search", "random"],
                        help="baseline agents to run alongside the models")
    parser.add_argument("--config", default="configs/native_pilot.json")
    args = parser.parse_args()

    out = ROOT / args.output
    out.mkdir(parents=True, exist_ok=True)
    frozen_path = out / "dev_scenarios.json"
    scenarios = freeze_scenarios(args.scenarios)
    if frozen_path.exists():
        existing = json.loads(frozen_path.read_text())["scenarios"]
        if digest(existing) != digest(scenarios):
            raise SystemExit("Frozen development scenarios differ; refusing to overwrite")
    else:
        atomic_json(frozen_path, {
            "purpose": "Frozen DEVELOPMENT rollout scenarios. Not training data, not the final test split.",
            "split": "val", "master_seed": DEV_MASTER_SEED, "count": len(scenarios),
            "used_for": "candidate comparison; treat as a reused development set",
            "scenarios": scenarios})
        print("froze", frozen_path)

    base = json.loads((ROOT / args.config).read_text())["search"]
    sc = SearchConfig(**base)

    from stsai.model import ModelEvaluator
    if args.model_dirs:
        sources = [(Path(d).name, ROOT / d / "model" / "best.pt") for d in args.model_dirs]
    else:
        sources = [(cell, ROOT / args.matrix / cell / "model" / "best.pt")
                   for cell in sorted(p.name for p in (ROOT / args.matrix).iterdir() if p.is_dir())]
    models = {}
    for cell, ckpt in sources:
        if ckpt.exists():
            models[cell] = (ModelEvaluator.from_checkpoint(str(ckpt), "cpu", "lightspeed_pilot"),
                            ckpt, "cpu")
    print(f"loaded {len(models)} checkpoints on cpu fp32")

    # GPU counterpart for the device comparison only, on a subset.
    gpu_models = {}

    records = []
    started = time.perf_counter()
    for entry in scenarios:
        scenario = entry["scenario"]; seed = entry["episode_seed"]; index = entry["index"]
        for agent in list(args.baselines) + list(models):
            env = make_env("lightspeed_pilot", scenario, seed)
            if agent == "random":
                rng = np.random.default_rng(index)
                choose = lambda obs, rng=rng: int(rng.integers(len(obs["actions"])))  # noqa: E731
            elif agent == "heuristic":
                choose = lambda obs: int(np.argmax(HeuristicEvaluator().evaluate(obs)[0]))  # noqa: E731
            elif agent == "search":
                search = BeliefSearch(sc)
                choose = lambda obs, s=search, e=env: next(  # noqa: E731
                    i for i, a in enumerate(obs["actions"])
                    if a["id"] == s.run(obs, e.sampler(), 4242 + index)["action"]["id"])
            else:
                evaluator, _ckpt, _dev = models[agent]
                choose = lambda obs, ev=evaluator: int(np.argmax(ev.evaluate(obs)[0]))  # noqa: E731
            final, latencies = step_episode(env, choose)
            completed = bool(final["terminal"])
            records.append({
                "agent": agent, "episode_index": index, "family": entry["family"],
                "encounter": entry["encounter"], "start_hp": entry["hp"], "deck_size": entry["deck_size"],
                "completed": completed, "won": bool(final["won"]) if completed else None,
                "truncated": not completed, "end_hp": final["player"]["hp"],
                "utility": terminal_utility(final, sc.potion_cost) if completed else None,
                "decisions": len(latencies),
                "p50_ms": float(np.percentile(latencies, 50) * 1000) if latencies else 0.0,
                "p95_ms": float(np.percentile(latencies, 95) * 1000) if latencies else 0.0,
            })
        if (index + 1) % 32 == 0:
            print(f"  {index + 1}/{len(scenarios)} scenarios, {time.perf_counter() - started:.0f}s", flush=True)

    with (out / "episodes.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    agents = list(args.baselines) + list(models)
    by_agent = {}
    for agent in agents:
        rows = [r for r in records if r["agent"] == agent]
        completed = [r for r in rows if r["completed"]]
        wins = [r for r in rows if r["won"]]
        by_agent[agent] = {
            "episodes": len(rows), "wins": len(wins),
            "losses": sum(1 for r in rows if r["completed"] and not r["won"]),
            "truncated": sum(1 for r in rows if r["truncated"]),
            "mean_utility": float(np.mean([r["utility"] for r in completed])) if completed else None,
            "mean_end_hp_survivors": float(np.mean([r["end_hp"] for r in wins])) if wins else None,
            "mean_decisions": float(np.mean([r["decisions"] for r in rows])),
            "p50_ms": float(np.median([r["p50_ms"] for r in rows])),
            "p95_ms": float(np.median([r["p95_ms"] for r in rows])),
        }

    index_of = {}
    for record in records:
        index_of.setdefault(record["episode_index"], {})[record["agent"]] = record
    paired = {}
    for other in agents:
        if other == "heuristic":
            continue
        keys = [k for k, v in index_of.items()
                if v.get(other, {}).get("completed") and v.get("heuristic", {}).get("completed")]
        if not keys:
            continue
        deltas = np.asarray([index_of[k][other]["utility"] - index_of[k]["heuristic"]["utility"] for k in keys])
        rng = np.random.default_rng(7)
        boot = [float(np.mean(deltas[rng.integers(0, len(deltas), len(deltas))])) for _ in range(2000)]
        paired[f"{other}_minus_heuristic"] = {
            "pairs": len(keys), "mean_delta": float(deltas.mean()),
            "bootstrap95": [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))],
            "complete_pairs_only": len(keys) == len(scenarios),
            "dropped_incomplete": len(scenarios) - len(keys),
        }

    summary = {
        "scope": "DEVELOPMENT closed loop over frozen scenarios; not a test result and not original-game strength",
        "scenarios": len(scenarios), "master_seed": DEV_MASTER_SEED,
        "agents": agents, "by_agent": by_agent, "paired_vs_heuristic": paired,
        "search_config": base, "max_actions": MAX_ACTIONS,
        "network_device": "cpu fp32 (batch one); GPU is used for training only",
        "elapsed_seconds": time.perf_counter() - started,
        "caveats": [
            "Only completed pairs enter the paired means; the dropped count is reported, not hidden.",
            "Same initial seed does not give different policies the same future randomness.",
            "This development set has now been seen; further reuse makes it less held out.",
        ],
    }
    atomic_json(out / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("by_agent", "paired_vs_heuristic")}, indent=2))
    for agent, values in by_agent.items():
        print(f"  {agent:16s} wins={values['wins']:3d} util={values['mean_utility']} "
              f"p50={values['p50_ms']:.2f}ms trunc={values['truncated']}")


if __name__ == "__main__":
    main()
