#!/usr/bin/env python3
"""Calibration of the outcome head, reported separately from the value head.

The scalar `value` output is a battle UTILITY estimate, not a survival
probability, so calibrating death probability reads class 0 of the 11-way
outcome softmax instead. Brier is also compared against a constant baseline
whose rate comes from the calibration set, never from held-out test data.

Every step of one battle shares that battle's ending, so the states are not
independent samples. Figures are therefore given twice: over all states, and
over one state per battle, with a battle-clustered bootstrap interval.
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import torch

from stsai.encoding import encode, collate_encoded
from stsai.model import load_checkpoint
from stsai.util import atomic_json

EPS = 1e-12


def load_rows(directory):
    import gzip
    rows = []
    for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            rows += [json.loads(line) for line in handle if line.strip()]
    return rows


def ece(probabilities, labels, bins=10):
    """Expected calibration error over fixed-width bins, plus the table."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    table = []
    total = len(probabilities)
    value = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (probabilities >= lo) & (probabilities < hi if i < bins - 1 else probabilities <= hi)
        if not mask.any():
            table.append({"bin": [float(lo), float(hi)], "count": 0})
            continue
        confidence = float(probabilities[mask].mean())
        accuracy = float(labels[mask].mean())
        value += mask.sum() / total * abs(confidence - accuracy)
        table.append({"bin": [float(lo), float(hi)], "count": int(mask.sum()),
                      "mean_predicted": confidence, "observed_rate": accuracy})
    return float(value), table


def clustered_bootstrap(values, groups, draws=2000, seed=42):
    rng = np.random.default_rng(seed)
    unique = list({g for g in groups})
    if len(unique) < 2:
        return None
    buckets = defaultdict(list)
    for value, group in zip(values, groups):
        buckets[group].append(value)
    samples = []
    for _ in range(draws):
        pick = rng.integers(0, len(unique), size=len(unique))
        pooled = [v for i in pick for v in buckets[unique[i]]]
        samples.append(float(np.mean(pooled)))
    return [float(np.quantile(samples, 0.025)), float(np.quantile(samples, 0.975))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data", nargs="+", required=True, help="calibration/development data only")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--bins", type=int, default=10)
    args = parser.parse_args()

    model, checkpoint = load_checkpoint(args.checkpoint, args.device)
    device = next(model.parameters()).device
    rows = load_rows(args.data[0]) if len(args.data) == 1 else \
        [r for d in args.data for r in load_rows(d)]
    if not rows:
        raise SystemExit("No rows")

    death_p, death_y, utilities, utility_y, masks = [], [], [], [], []
    groups, completed = [], []
    with torch.inference_mode():
        for start in range(0, len(rows), 64):
            chunk = rows[start:start + 64]
            batch = {k: v.to(device) for k, v in
                     collate_encoded([encode(r["observation"]) for r in chunk]).items()}
            out = model(batch)
            probs = out["outcome_logits"].softmax(-1).float().cpu().numpy()
            values = out["value"].float().cpu().numpy()
            for i, row in enumerate(chunk):
                target = np.asarray(row["outcome"], dtype=np.float64)
                death_p.append(float(probs[i, 0]))
                death_y.append(float(target[0]))
                utilities.append(float(values[i]))
                utility_y.append(float(row["value"]))
                masks.append(float(row["value_mask"]))
                groups.append(row["episode_id"])
                completed.append(bool(row["value_mask"]))

    death_p = np.asarray(death_p); death_y = np.asarray(death_y)
    utilities = np.asarray(utilities); utility_y = np.asarray(utility_y)
    masks = np.asarray(masks)
    base_rate = float(death_y.mean())

    brier = float(np.mean((death_p - death_y) ** 2))
    brier_baseline = float(np.mean((base_rate - death_y) ** 2))
    p = np.clip(death_p, EPS, 1 - EPS)
    nll = float(np.mean(-(death_y * np.log(p) + (1 - death_y) * np.log(1 - p))))
    ece_value, table = ece(death_p, death_y, args.bins)

    # One state per battle: the first, so the choice is fixed rather than tuned.
    first = {}
    for i, g in enumerate(groups):
        first.setdefault(g, i)
    idx = sorted(first.values())

    def subset(values):
        return [float(v) for v in values[idx]]

    report = {
        "scope": "development/calibration data only; not a test evaluation",
        "checkpoint": str(args.checkpoint),
        "data": [str(Path(d).resolve()) for d in args.data],
        "states": len(rows), "battles": len(first),
        "death_rate_in_this_set": base_rate,
        "death_probability": {
            "brier": brier,
            "brier_constant_rate_baseline": brier_baseline,
            "brier_skill_vs_baseline": 1.0 - brier / max(brier_baseline, EPS),
            "nll": nll,
            "ece": ece_value,
            "bin_count": args.bins,
            "reliability_table": table,
        },
        "one_state_per_battle": {
            "battles": len(idx),
            "death_rate": float(np.mean(death_y[idx])),
            "brier": float(np.mean((death_p[idx] - death_y[idx]) ** 2)),
            "brier_clustered_bootstrap95": clustered_bootstrap(
                (death_p - death_y) ** 2, groups),
            "ece": ece(np.asarray(subset(death_p)), np.asarray(subset(death_y)), args.bins)[0],
        },
        "utility_head": {
            "mse_completed_only": float(np.mean(((utilities - utility_y) ** 2)[masks > 0])) if (masks > 0).any() else None,
            "completed_states": int((masks > 0).sum()),
            "truncated_states": int((masks == 0).sum()),
            "note": "truncated states carry no outcome and are excluded, not treated as deaths",
        },
        "caveats": [
            "States inside one battle share an ending; the clustered figures are the honest ones.",
            "Calibration is for the policy that produced these trajectories; another policy's "
            "leaf distribution is not covered by these numbers.",
            "No temperature scaling was fitted. If one is added it must be fitted on an "
            "independent calibration set and reported separately.",
        ],
    }
    atomic_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
