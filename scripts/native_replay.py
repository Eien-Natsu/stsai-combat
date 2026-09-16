#!/usr/bin/env python3
"""Bounded randomized replay over the pilot range (G2 engineering stress test).

Plays legal-but-random action sequences and records what happened: illegal
actions, crashes, unsupported states, undefined-behaviour flags and fights that
outran the action budget. Over-budget fights are classified, never dropped.

This is a rules-robustness probe, not a strength benchmark and not a
substitute for original-game differential testing. It reads no hidden RNG:
every action comes from the public `actions` list, and the sampler is only
checked for preserving the public root.
"""
import argparse
import json
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MAX_ACTIONS = 256
# Never a valid action id; proves the adapter rejects rather than clamps.
IMPOSSIBLE_ACTION = "4294967295"


def play_episode(job):
    """Run one random fight. Returns a JSON-able summary dict."""
    index, split, probe_illegal, probe_sample = job
    from stsai.scenarios import make_scenario
    from stsai.native import NativeBattle
    from stsai.contracts import validate_public, observation_key

    scenario, seed, family = make_scenario("lightspeed_pilot", split, index)
    record = {"index": index, "split": split, "family": family,
              "encounter": scenario["encounter"], "actions": 0,
              "terminal": False, "won": None, "illegal_actions": 0,
              "crashes": [], "undefined_behavior": 0, "sample_mismatches": 0,
              "over_budget": False, "win_hp": None}
    try:
        env = NativeBattle(scenario, seed)
        rng = random.Random(seed ^ 0x5A17)
        for _ in range(MAX_ACTIONS):
            obs = env.observe()
            validate_public(obs)
            if probe_illegal:
                before = observation_key(obs)
                try:
                    env.step({"id": IMPOSSIBLE_ACTION})
                    record["illegal_actions"] += 1  # an illegal action was ACCEPTED
                except Exception:
                    pass
                if observation_key(env.observe()) != before:
                    record["illegal_actions"] += 1  # rejected but mutated state anyway
            if probe_sample:
                try:
                    if observation_key(env.sampler()(rng.getrandbits(63)).observe()) != observation_key(obs):
                        record["sample_mismatches"] += 1
                except Exception as exc:
                    record["undefined_behavior"] += 1
                    record["crashes"].append(f"sample: {type(exc).__name__}: {exc}")
            if obs["terminal"]:
                record["terminal"] = True
                record["won"] = obs["won"]
                record["win_hp"] = obs["player"]["hp"]
                break
            env.step(rng.choice(obs["actions"]))
            record["actions"] += 1
        else:
            record["over_budget"] = True
    except Exception as exc:  # never swallow silently: report the class and message
        record["crashes"].append(f"{type(exc).__name__}: {exc}")
    return record


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=1000)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--splits", nargs="+", default=["train", "val"])
    p.add_argument("--probe-illegal", type=int, default=4,
                   help="probe illegal-action rejection on every Nth step (0 disables)")
    p.add_argument("--output", default="runs/native_replay.json")
    args = p.parse_args()
    if args.episodes < 1 or not 1 <= args.workers <= 32:
        raise SystemExit("Invalid episode or worker count")
    for split in args.splits:
        if split not in ("train", "val"):
            raise SystemExit("Only train/val splits may be replayed; test is reserved")

    jobs = [(i, args.splits[i % len(args.splits)], i % max(1, args.probe_illegal) == 0, i % 7 == 0)
            for i in range(args.episodes)]
    started = time.perf_counter()
    with Pool(args.workers) as pool:
        records = pool.map(play_episode, jobs, chunksize=8)
    elapsed = time.perf_counter() - started

    from stsai.native import engine_metadata
    crashes = [{"index": r["index"], "error": e} for r in records for e in r["crashes"]]
    over_budget = [r["index"] for r in records if r["over_budget"]]
    won = [r for r in records if r["won"]]
    lost = [r for r in records if r["terminal"] and not r["won"]]
    report = {
        "scope": "randomized replay over the pilot range; NOT a strength benchmark",
        "episodes": len(records), "workers": args.workers,
        "max_actions_per_episode": MAX_ACTIONS,
        "elapsed_seconds": elapsed, "episodes_per_second": len(records) / elapsed,
        "total_actions": sum(r["actions"] for r in records),
        "illegal_actions_accepted": sum(r["illegal_actions"] for r in records),
        "sample_root_mismatches": sum(r["sample_mismatches"] for r in records),
        "undefined_behavior_flags": sum(r["undefined_behavior"] for r in records),
        "crashes": crashes, "crash_count": len(crashes),
        "over_budget_count": len(over_budget), "over_budget_indices": over_budget,
        "terminal_count": sum(1 for r in records if r["terminal"]),
        "won": len(won), "lost": len(lost),
        "encounters": sorted({r["encounter"] for r in records}),
        "engine": engine_metadata(),
        "note": "Random play wins almost nothing; the win/loss split only shows the "
                "fight reaches a decided state. G3 original-game differential testing "
                "is still outstanding.",
    }
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "crashes"}, indent=2))
    if crashes or report["illegal_actions_accepted"] or report["sample_root_mismatches"]:
        print("FAILED: see report", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
