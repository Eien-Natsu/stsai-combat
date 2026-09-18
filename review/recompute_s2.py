#!/usr/bin/env python3
"""Recompute the S2 paired statistics from the packaged raw episodes.

    python review/recompute_s2.py --package <unpacked package> [--out recomputed.json]

This is written from the protocol rather than from the script that produced the
shipped numbers, so that agreement between the two is itself a check. It reads
only what the package ships: the per-episode records. It does not train, does
not touch the GPU, and does not read the final P6 manifest.

The primary quantity is delta_s,i = utility(D384, seed s, scenario i) -
utility(D96, seed s, scenario i) on DEV_PROBE256. Truncated episodes score 0 in
the primary summary, as the protocol pre-registered; the complete-pairs variant
is computed beside it. The interval is a scenario bootstrap, conditional on the
three trained seeds.
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

REPLICATES = 20000
RNG_SEED = 20260920
SEEDS = [17, 29, 43]


def load_package(package):
    path = Path(package) / "evaluation" / "episodes.jsonl.gz"
    if not path.is_file():
        raise SystemExit(f"the package does not ship {path}")
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def index_rows(rows):
    """{(set, policy, scenario): row}"""
    return {(r["set"], r["policy"], r["episode_index"]): r for r in rows}


def utility(row, conservative=True):
    if row["completed"]:
        return float(row["utility"])
    return 0.0 if conservative else None


def boot_mean(values, rng):
    values = np.asarray(values, dtype=float)
    n = len(values)
    draws = np.empty(REPLICATES)
    for i in range(REPLICATES):
        draws[i] = values[rng.integers(0, n, n)].mean()
    return float(values.mean()), float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))


def contrast(table, set_name, left, right, scenarios, conservative=True):
    pairs = []
    for scenario in scenarios:
        a = table.get((set_name, left, scenario))
        b = table.get((set_name, right, scenario))
        if a is None or b is None:
            continue
        ua, ub = utility(a, conservative), utility(b, conservative)
        if ua is None or ub is None:
            continue
        pairs.append(ua - ub)
    if not pairs:
        return None
    mean, low, high = boot_mean(pairs, np.random.default_rng(RNG_SEED))
    return {"scenarios": len(pairs), "mean": mean, "ci95": [low, high],
            "lower_above_zero": low > 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    rows = load_package(args.package)
    table = index_rows(rows)
    sets = sorted({r["set"] for r in rows})
    policies = sorted({r["policy"] for r in rows})
    scenarios = {name: sorted({r["episode_index"] for r in rows if r["set"] == name})
                 for name in sets}
    truncated = {}
    for row in rows:
        if not row["completed"]:
            truncated[f"{row['set']}/{row['policy']}"] = truncated.get(
                f"{row['set']}/{row['policy']}", 0) + 1

    report = {"purpose": "Independent recomputation of the S2 paired statistics.",
              "episodes_read": len(rows), "sets": sets, "policies": policies,
              "bootstrap": {"replicates": REPLICATES, "seed": RNG_SEED, "unit": "scenario"},
              "truncated": truncated, "comparisons": {}}

    for set_name in sets:
        entry = {}
        per_seed = {}
        for seed in SEEDS:
            per_seed[f"s{seed}"] = contrast(table, set_name, f"D384_s{seed}", f"D96_s{seed}",
                                            scenarios[set_name])
        entry["D384_minus_D96_per_seed"] = per_seed
        seed_means = [v["mean"] for v in per_seed.values() if v]
        if seed_means:
            joint_values = []
            for scenario in scenarios[set_name]:
                values = []
                for seed in SEEDS:
                    a = table.get((set_name, f"D384_s{seed}", scenario))
                    b = table.get((set_name, f"D96_s{seed}", scenario))
                    if a and b:
                        values.append(utility(a) - utility(b))
                if values:
                    joint_values.append(float(np.mean(values)))
            mean, low, high = boot_mean(joint_values, np.random.default_rng(RNG_SEED))
            entry["D384_minus_D96_joint"] = {"scenarios": len(joint_values), "mean": mean,
                                             "ci95": [low, high], "lower_above_zero": low > 0}
            entry["seed_means"] = seed_means
            entry["mean_of_seed_means"] = float(np.mean(seed_means))
            entry["all_same_direction"] = len({np.sign(m) for m in seed_means}) == 1
        for policy in policies:
            if policy in ("heuristic", "search"):
                continue
            for baseline in ("heuristic", "search"):
                entry[f"{policy}_minus_{baseline}"] = contrast(table, set_name, policy, baseline,
                                                               scenarios[set_name])
        report["comparisons"][set_name] = entry

    primary = report["comparisons"].get("dev_probe256", {})
    if primary.get("seed_means"):
        joint = primary["D384_minus_D96_joint"]
        report["verdict"] = {
            "all_three_seeds_same_direction": primary["all_same_direction"],
            "mean_of_seed_means": primary["mean_of_seed_means"],
            "joint_ci95": joint["ci95"],
            "supports_D384": bool(primary["all_same_direction"]
                                  and primary["mean_of_seed_means"] > 0
                                  and joint["lower_above_zero"]),
            "how_to_read": "applies to this probe and these three seeds at this budget",
        }

    text = json.dumps(report, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
