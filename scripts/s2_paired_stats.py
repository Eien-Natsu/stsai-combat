#!/usr/bin/env python3
"""The S2 paired analysis: D384 minus D96 per seed, with scenario bootstrap.

    python scripts/s2_paired_stats.py [--episodes runs/s2/evaluation/episodes.jsonl.gz] \
        [--out evaluation/paired_summary.json]

The primary quantity is delta_s,i = utility(D384, seed s, scenario i) -
utility(D96, seed s, scenario i) on DEV_PROBE256. Three seeds are three paired
comparisons, not 768 independent scenarios, so each is resampled over scenarios
and the joint statement is the mean of the three, with the spread across seeds
reported beside the interval rather than inside it: the interval is conditional
on exactly these three trained seeds.

A truncated episode scores 0 in the primary summary, as the protocol says. The
complete-pairs result is reported next to it, so a reader can see whether the
two disagree. Every configuration and seed is also compared against the
heuristic and the search on both sets, in the same way.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.util import atomic_json  # noqa: E402

REPLICATES = 20000
SEED = 20260920
SEEDS = (17, 29, 43)
BASELINES = ("heuristic", "search")


def load(path):
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    out = {}
    for row in rows:
        out.setdefault(row["set"], {}).setdefault(row["policy"], {})[row["episode_index"]] = row
    return out, rows


def utilities(by_policy, index_map):
    """{(policy, index): reported utility}, plus the truncation counts."""
    values, truncated = {}, {}
    for policy, rows in by_policy.items():
        for index, row in rows.items():
            # Conservative primary: an episode that never finished scores 0, which
            # is what the protocol pre-registered.
            values[(policy, index)] = float(row["utility"]) if row["completed"] else 0.0
            if not row["completed"]:
                truncated[policy] = truncated.get(policy, 0) + 1
    return values, truncated


def bootstrap(delta, rng):
    draws = [float(np.mean(delta[rng.integers(0, len(delta), len(delta))]))
             for _ in range(REPLICATES)]
    return [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]


def paired(values, left, right, indices, complete_only, completed_by_policy=None):
    """Every comparison resamples with its own generator at the protocol seed, so
    one comparison can be recomputed on its own without replaying the others."""
    keys = sorted(indices)
    if complete_only:
        keys = [k for k in keys
                if completed_by_policy[left][k] and completed_by_policy[right][k]]
    if not keys:
        return None
    delta = np.asarray([values[(left, k)] - values[(right, k)] for k in keys])
    interval = bootstrap(delta, np.random.default_rng(SEED))
    return {"pairs": len(keys), "mean": float(delta.mean()), "bootstrap95": interval,
            "lower_above_zero": bool(interval[0] > 0), "a_better": int((delta > 0).sum()),
            "b_better": int((delta < 0).sum()), "tie": int((delta == 0).sum()),
            "replicates": REPLICATES, "bootstrap_seed": SEED, "unit": "scenario",
            "complete_pairs_only": complete_only}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", default="runs/s2/evaluation/episodes.jsonl.gz")
    parser.add_argument("--out", default="reports/s2_paired_summary.json")
    args = parser.parse_args()

    by_set, rows = load(ROOT / args.episodes)
    result = {
        "purpose": "S2 paired analysis: the D384-vs-D96 contrast and each policy against the "
                   "baselines, on both frozen development sets.",
        "direction": "positive means the first policy is better; utility is the round's terminal "
                     "utility",
        "bootstrap": {"replicates": REPLICATES, "seed": SEED, "unit": "scenario",
                      "conditional_on": "the three trained seeds (17, 29, 43); this does not "
                                        "cover training randomness"},
        "truncation_rule": "a truncated episode scores 0 in the primary summary; the complete-pairs "
                           "result is reported beside it",
        "sets": {},
    }

    for set_name, by_policy in by_set.items():
        indices = sorted(next(iter(by_policy.values())).keys())
        values, truncated = utilities(by_policy, indices)
        completed_by_policy = {policy: {i: bool(row["completed"]) for i, row in rows_.items()}
                               for policy, rows_ in by_policy.items()}

        entry = {"scenarios": len(indices), "policies": sorted(by_policy),
                 "truncated": truncated,
                 "mean_utility": {policy: float(np.mean([values[(policy, i)] for i in indices]))
                                  for policy in sorted(by_policy)},
                 "wins": {policy: int(sum(1 for i in indices if by_policy[policy][i]["won"]))
                          for policy in sorted(by_policy)}}

        # The primary contrast, seed by seed.
        per_seed = {}
        seed_means = []
        for seed in SEEDS:
            pair = paired(values, f"D384_s{seed}", f"D96_s{seed}", indices, False)
            pair_complete = paired(values, f"D384_s{seed}", f"D96_s{seed}", indices, True,
                                   completed_by_policy)
            pair["complete_pairs_sensitivity"] = pair_complete
            per_seed[f"s{seed}"] = pair
            seed_means.append(pair["mean"])
        entry["D384_minus_D96_per_seed"] = per_seed
        entry["D384_minus_D96_across_seeds"] = {
            "seed_means": [float(m) for m in seed_means],
            "mean_of_seed_means": float(np.mean(seed_means)),
            "sd_across_seeds": float(np.std(seed_means, ddof=1)) if len(seed_means) > 1 else None,
            "range": [float(min(seed_means)), float(max(seed_means))],
            "all_same_direction": bool(len({np.sign(m) for m in seed_means}) == 1),
            "direction": "positive" if np.mean(seed_means) > 0 else "negative",
        }
        # The joint interval: average the three seeds per scenario, then resample
        # scenarios. It is still conditional on those three seeds.
        joint = np.asarray([np.mean([values[(f"D384_s{s}", i)] - values[(f"D96_s{s}", i)]
                                     for s in SEEDS]) for i in indices])
        joint_interval = bootstrap(joint, np.random.default_rng(SEED))
        entry["D384_minus_D96_joint"] = {
            "pairs": len(indices), "mean": float(joint.mean()), "bootstrap95": joint_interval,
            "lower_above_zero": bool(joint_interval[0] > 0), "replicates": REPLICATES,
            "bootstrap_seed": SEED, "unit": "scenario",
            "note": "per-scenario mean over the three seeds, then resampled over scenarios",
        }

        # Every policy against both baselines.
        entry["versus_baselines"] = {}
        for policy in sorted(by_policy):
            if policy in BASELINES:
                continue
            entry["versus_baselines"][policy] = {
                f"{policy}_minus_{baseline}": paired(values, policy, baseline, indices, False)
                for baseline in BASELINES if baseline in by_policy}

        # Strata are exploratory and carry their n.
        encounters = {i: by_policy[sorted(by_policy)[0]][i]["family"] for i in indices}
        strata = {}
        for encounter in sorted({v for v in encounters.values() if v}):
            keys = [i for i in indices if encounters[i] == encounter]
            if len(keys) < 5:
                continue
            deltas = [np.mean([values[(f"D384_s{s}", i)] - values[(f"D96_s{s}", i)]
                               for s in SEEDS]) for i in keys]
            strata[encounter] = {"n_scenarios": len(keys),
                                 "mean_delta": float(np.mean(deltas)),
                                 "exploratory": True}
        entry["strata_by_family"] = strata
        result["sets"][set_name] = entry

    # The decision rule, applied to the primary set only, as written in the protocol.
    primary = result["sets"].get("dev_probe256")
    if primary:
        across = primary["D384_minus_D96_across_seeds"]
        joint = primary["D384_minus_D96_joint"]
        supports = (across["all_same_direction"] and across["mean_of_seed_means"] > 0
                    and joint["lower_above_zero"])
        result["conclusion"] = {
            "rule": "all three seeds moving the same way with a positive mean and a conditional "
                    "scenario interval above zero supports D384",
            "all_three_same_direction": across["all_same_direction"],
            "mean_of_seed_means": float(across["mean_of_seed_means"]),
            "joint_lower_bound": joint["bootstrap95"][0],
            "verdict": ("supports D384 over D96 on this probe at this budget"
                        if supports else "insufficient evidence under the pre-registered rule"),
        }
        old = result["sets"].get("dev_old256")
        if old:
            result["conclusion"]["secondary_set_agrees"] = bool(
                np.sign(old["D384_minus_D96_across_seeds"]["mean_of_seed_means"])
                == np.sign(across["mean_of_seed_means"]))

    atomic_json(ROOT / args.out, result)
    for set_name, entry in result["sets"].items():
        across = entry["D384_minus_D96_across_seeds"]
        joint = entry["D384_minus_D96_joint"]
        print(f"{set_name}: per-seed means {[round(m, 4) for m in across['seed_means']]}")
        print(f"   mean {across['mean_of_seed_means']:+.4f} joint95 "
              f"[{joint['bootstrap95'][0]:+.4f}, {joint['bootstrap95'][1]:+.4f}]")
    print(json.dumps(result.get("conclusion", {}), indent=1))


if __name__ == "__main__":
    main()
