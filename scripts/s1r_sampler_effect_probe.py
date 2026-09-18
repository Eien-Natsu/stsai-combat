#!/usr/bin/env python3
"""Did the fixed sampler change the teacher's decisions on the rebuilt episodes?

    python scripts/s1r_sampler_effect_probe.py [--out reports/s1r_sampler_effect.json]

The rebuilt collection reproduces the S1 action sequence exactly on every
episode checked, which is either "the fix does not reach these seeds" or a sign
that something was reused. This replays a bounded set of roots twice - once with
the shipped sampler, once with the pre-fix hook that copies the true hidden base
- through the same search, and reports whether the teacher's chosen action and
policy differ.

Budget: at most 64 roots, at most 128 actions per root, one search per root per
sampler, unchanged 64 simulations.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.native import NativeBattle  # noqa: E402
from stsai.scenarios import make_scenario  # noqa: E402
from stsai.search import BeliefSearch, SearchConfig  # noqa: E402
from stsai.util import atomic_json, digest, seed_for  # noqa: E402

MAX_ROOTS = 64
MAX_STEPS = 128


def teacher(config):
    return BeliefSearch(SearchConfig(**config))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/native_pilot.json")
    parser.add_argument("--out", default="reports/s1r_sampler_effect.json")
    parser.add_argument("--indices", nargs="*", type=int, default=None,
                        help="episode indices to probe; defaults to the louse encounters found")
    parser.add_argument("--split", default="train")
    args = parser.parse_args()

    config = json.loads((ROOT / args.config).read_text())
    search_config = config["search"]
    master_seed = config["master_seed"]
    indices = args.indices
    if indices is None:
        indices = []
        for index in range(96):
            scenario, seed, _ = make_scenario("lightspeed_pilot", args.split, index, master_seed)
            env = NativeBattle(scenario, seed)
            if any("LOUSE" in e["id"] for e in env.observe()["enemies"]):
                indices.append(index)
    indices = indices[:MAX_ROOTS]

    result = {"purpose": "Whether the fixed sampler changes the teacher's decisions.",
              "split": args.split, "search": search_config, "roots": [], "steps_compared": 0,
              "steps_where_the_teacher_changed": 0, "roots_with_any_change": 0}
    for index in indices:
        scenario, seed, _ = make_scenario("lightspeed_pilot", args.split, index, master_seed)
        fixed = NativeBattle(scenario, seed)
        prefix = NativeBattle(scenario, seed)
        row = {"episode_index": index, "scenario_sha256": digest(scenario), "steps": []}
        obs_f, obs_p = fixed.observe(), prefix.observe()
        for step in range(MAX_STEPS):
            if obs_f["terminal"] or obs_p["terminal"]:
                break
            search_seed = seed_for("search-agent", "lightspeed_pilot", args.split, index, step, 0)
            a = teacher(search_config).run(obs_f, fixed.sampler(), search_seed)
            b = teacher(search_config).run(obs_p, lambda s: NativeBattle._wrap(
                prefix._handle.debug_sample_with_true_base(s)), search_seed)
            same_action = a["action"]["id"] == b["action"]["id"]
            same_policy = digest(a["policy"]) == digest(b["policy"])
            row["steps"].append({"step": step, "same_action": same_action,
                                 "same_policy": same_policy})
            result["steps_compared"] += 1
            if not same_action:
                result["steps_where_the_teacher_changed"] += 1
            obs_f = fixed.step(a["action"])
            obs_p = prefix.step(b["action"])
            if not same_action:
                break  # the trajectories diverged; further steps compare different states
        if not all(s["same_action"] for s in row["steps"]):
            result["roots_with_any_change"] += 1
        row["all_steps_same"] = all(s["same_action"] for s in row["steps"])
        result["roots"].append(row)
        print(f"index {index}: {len(row['steps'])} steps, "
              f"same={row['all_steps_same']}", flush=True)

    result["conclusion"] = (
        "the fixed sampler leaves the teacher's chosen action unchanged on every probed root"
        if result["steps_where_the_teacher_changed"] == 0 else
        "the fixed sampler changes the teacher's chosen action on at least one probed root")
    atomic_json(ROOT / args.out, result)
    print(result["conclusion"])


if __name__ == "__main__":
    main()
