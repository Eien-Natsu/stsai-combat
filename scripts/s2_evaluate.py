#!/usr/bin/env python3
"""Run every frozen policy over both frozen development sets, once each.

    python scripts/s2_evaluate.py [--sets dev_old256 dev_probe256] [--policies ...]

Six selected networks, the heuristic and the 64-simulation search play the same
512 scenarios, so the comparison is paired on the initial condition. The search
baseline is re-run here rather than reused from S1R: the sampler and the encoder
changed, so the S1R search score is not a current baseline.

Every policy runs on CPU with torch threads pinned to 1, including the
baselines, and the environment is recorded with the results. Inference is batch
one. Episodes come from the materialised lists; nothing is regenerated here.

An episode that raises is a failure of the run, not a row to drop, so it stops
the evaluation. An episode that reaches the action ceiling is recorded as
truncated and left for the summary to score conservatively.
"""
import argparse
import gzip
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.model import ModelEvaluator  # noqa: E402
from stsai.native import NativeBattle  # noqa: E402
from stsai.objective import terminal_utility  # noqa: E402
from stsai.search import BeliefSearch, HeuristicEvaluator, SearchConfig  # noqa: E402
from stsai.util import atomic_json, digest  # noqa: E402

MAX_ACTIONS = 256
THREADS = 1  # fixed for every policy in this round

MODELS = [
    {"policy": "D96_s17", "directory": "runs/s1r/M128-R0-s17-S1R/model"},
    {"policy": "D96_s29", "directory": "runs/s2/D96_s29/model"},
    {"policy": "D96_s43", "directory": "runs/s2/D96_s43/model"},
    {"policy": "D384_s17", "directory": "runs/s2/D384_s17/model"},
    {"policy": "D384_s29", "directory": "runs/s2/D384_s29/model"},
    {"policy": "D384_s43", "directory": "runs/s2/D384_s43/model"},
]


def make_env(scenario, episode_seed):
    return NativeBattle(scenario, episode_seed)


def load_sets(names):
    out = {}
    for name in names:
        path = ROOT / "runs/s2" / f"{name}.json"
        if not path.is_file():
            raise SystemExit(f"the frozen set {name} is missing at {path}")
        out[name] = json.loads(path.read_text())
    return out


def play(choose, scenario, episode_seed, record_decisions, name, set_name, index):
    env = make_env(scenario, episode_seed)
    obs = env.observe()
    actions, latencies = [], []
    for step in range(MAX_ACTIONS):
        if obs["terminal"]:
            break
        started = time.perf_counter()
        # The sampler a policy searches with must come from the environment it is
        # playing, not from a second copy: a belief sample is drawn from the
        # current public state, and that state moves as the episode is played.
        choice = choose(obs, env)
        elapsed = time.perf_counter() - started
        actions.append(int(choice))
        latencies.append((step, int(choice), len(obs["actions"]) <= 1, elapsed * 1000.0))
        obs = env.step(obs["actions"][int(choice)])
    completed = bool(obs["terminal"])
    for step, choice, forced, ms in latencies:
        record_decisions.append({"set": set_name, "policy": name, "episode_index": index,
                                 "step": step, "action_index": choice, "forced": forced,
                                 "ms": ms})
    return {"set": set_name, "policy": name, "episode_index": index, "family": None,
            "completed": completed, "won": bool(obs["won"]) if completed else None,
            "truncated": not completed, "end_hp": obs["player"]["hp"],
            "utility": terminal_utility(obs, 0.02) if completed else None,
            "decisions": len(actions), "actions": actions,
            "action_sequence_sha256": digest(actions)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="runs/s2/evaluation")
    parser.add_argument("--sets", nargs="+", default=["dev_old256", "dev_probe256"])
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--skip-search", action="store_true",
                        help="debug only; a report without the search baseline is incomplete")
    args = parser.parse_args()

    import torch
    torch.set_num_threads(THREADS)
    sets = load_sets(args.sets)
    config = json.loads((ROOT / args.config).read_text())
    search_config = SearchConfig(**config["search"])

    evaluators = {}
    for entry in MODELS:
        checkpoint = ROOT / entry["directory"] / "best.pt"
        if not checkpoint.is_file():
            raise SystemExit(f"{entry['policy']}: no selected checkpoint at {checkpoint}")
        evaluators[entry["policy"]] = ModelEvaluator.from_checkpoint(str(checkpoint), "cpu")

    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    episodes, decisions = [], []
    started = time.perf_counter()
    for set_name, payload in sets.items():
        scenarios = payload["scenarios"]
        for entry in scenarios:
            index = entry["index"]
            choose_heur = lambda obs, env: int(  # noqa: E731
                np.argmax(HeuristicEvaluator().evaluate(obs)[0]))
            heuristic_result = play(choose_heur, entry["scenario"], entry["episode_seed"],
                                    decisions, "heuristic", set_name, index)
            heuristic_result["family"] = entry["family"]
            episodes.append(heuristic_result)
            if not args.skip_search:
                search = BeliefSearch(search_config)

                def choose_search(obs, env, index=index, search=search):
                    # Same sampler path as the S1R evaluation: the belief sample
                    # comes from the environment being played, at its current state.
                    return next(i for i, a in enumerate(obs["actions"])
                                if a["id"] == search.run(obs, env.sampler(),
                                                         4242 + index)["action"]["id"])
                result = play(choose_search, entry["scenario"], entry["episode_seed"],
                              decisions, "search", set_name, index)
                result["family"] = entry["family"]
                episodes.append(result)
            for name, evaluator in evaluators.items():
                choose_model = lambda obs, env, ev=evaluator: int(  # noqa: E731
                    np.argmax(ev.evaluate(obs)[0]))
                result = play(choose_model, entry["scenario"], entry["episode_seed"],
                              decisions, name, set_name, index)
                result["family"] = entry["family"]
                episodes.append(result)
            if (index + 1) % 32 == 0:
                print(f"  {set_name} {index + 1}/{len(scenarios)} scenarios, "
                      f"{time.perf_counter() - started:.0f}s", flush=True)

    with gzip.open(out / "episodes.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in episodes:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    with gzip.open(out / "decision_latency.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in decisions:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    atomic_json(out / "environment.json", {
        "policies": ["heuristic", "search"] + list(evaluators),
        "sets": {name: {"count": len(payload["scenarios"]),
                        "sha256": digest([[e["scenario_sha256"], e["episode_seed"]]
                                          for e in payload["scenarios"]])}
                 for name, payload in sets.items()},
        "max_actions": MAX_ACTIONS,
        "torch_threads": torch.get_num_threads(),
        "torch_version": torch.__version__,
        "cpu_model": next((line.split(":", 1)[1].strip()
                           for line in Path("/proc/cpuinfo").read_text().splitlines()
                           if line.startswith("model name")), ""),
        "device": "cpu fp32, batch one; the GPU is used for training only",
        "search": config["search"],
        "episodes_recorded": len(episodes), "decisions_recorded": len(decisions),
        "elapsed_seconds": time.perf_counter() - started,
    })
    print(f"{len(episodes)} episodes, {len(decisions)} decisions -> {out}")


if __name__ == "__main__":
    main()
