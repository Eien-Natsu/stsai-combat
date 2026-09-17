#!/usr/bin/env python3
"""Paired Brier difference against a constant baseline.

A marginal interval for the model's own Brier says nothing about whether it beats
a constant predictor: the comparison is a difference on the SAME states, so it
must be computed per state and resampled per battle.

    d = (p_death - y)^2 - (q_baseline - y)^2

q_baseline is the death rate measured on the TRAINING shards and frozen before
this evaluation, never the death rate of the evaluation set itself. Death
probability is class 0 of the 11-way outcome head; the scalar `value` output is a
battle utility estimate and is not a probability.
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


def load_rows(directory):
    import gzip
    rows = []
    for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            rows += [json.loads(line) for line in handle if line.strip()]
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--calibration-data", required=True, help="states to score")
    parser.add_argument("--baseline-data", required=True, help="shards the constant rate is frozen from")
    parser.add_argument("--output", required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--draws", type=int, default=2000)
    args = parser.parse_args()

    # Freeze the constant BEFORE looking at the evaluation states.
    baseline_rows = load_rows(args.baseline_data)
    q = float(np.mean([np.asarray(r["outcome"], dtype=np.float64)[0] for r in baseline_rows]))

    model, _ = load_checkpoint(args.checkpoint, args.device)
    device = next(model.parameters()).device
    rows = load_rows(args.calibration_data)

    probabilities, outcomes, groups = [], [], []
    with torch.inference_mode():
        for start in range(0, len(rows), 64):
            chunk = rows[start:start + 64]
            batch = {k: v.to(device) for k, v in
                     collate_encoded([encode(r["observation"]) for r in chunk]).items()}
            probs = model(batch)["outcome_logits"].softmax(-1).float().cpu().numpy()
            for i, row in enumerate(chunk):
                probabilities.append(float(probs[i, 0]))
                outcomes.append(float(np.asarray(row["outcome"], dtype=np.float64)[0]))
                groups.append(row["episode_id"])

    p = np.asarray(probabilities); y = np.asarray(outcomes)
    d_state = (p - y) ** 2 - (q - y) ** 2

    per_battle = defaultdict(list)
    for value, group in zip(d_state, groups):
        per_battle[group].append(float(value))
    battle_ids = sorted(per_battle)
    per_battle_mean = np.asarray([np.mean(per_battle[b]) for b in battle_ids])
    per_battle_first = np.asarray([per_battle[b][0] for b in battle_ids])

    rng = np.random.default_rng(5)

    def clustered(values, weight=None):
        boot = []
        for _ in range(args.draws):
            pick = rng.integers(0, len(values), len(values))
            boot.append(float(np.mean(values[pick])))
        return [float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))]

    report = {
        "scope": "development analysis; not a test result",
        "checkpoint": str(args.checkpoint),
        "calibration_states": str(Path(args.calibration_data).resolve()),
        "baseline_source": str(Path(args.baseline_data).resolve()),
        "frozen_baseline_death_rate": q,
        "states": len(rows), "battles": len(battle_ids),
        "deaths_in_evaluation_set": float(y.mean()),
        "estimands": {
            "state_weighted": {
                "mean_difference": float(d_state.mean()),
                "note": "point estimate weights states; the interval below is battle-weighted and does not match it",
            },
            "one_state_per_battle": {
                "mean_difference": float(per_battle_first.mean()),
                "clustered_bootstrap95": clustered(per_battle_first),
            },
            "battle_mean_then_mean": {
                "mean_difference": float(per_battle_mean.mean()),
                "clustered_bootstrap95": clustered(per_battle_mean),
            },
        },
        "components": {
            "model_brier": float(np.mean((p - y) ** 2)),
            "baseline_brier": float(np.mean((q - y) ** 2)),
        },
        "caveats": [
            "Negative favours the model. The difference is a proper-score comparison, "
            "which is not by itself a calibration improvement.",
            "Reliability bins, NLL and the counts are reported separately in the calibration report.",
            "States inside one battle share an ending, so resampling is per battle, never per state.",
        ],
    }
    atomic_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
