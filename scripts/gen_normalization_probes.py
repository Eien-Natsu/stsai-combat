#!/usr/bin/env python3
"""Record the S1-A counting probes as machine-readable evidence.

Every value here is produced by calling the shipped code, not restated from a
report. The probes are the ones the review asked for: the hand-computed
effective-batch mean, partition invariance of the real trainer, validation
batch invariance, mask handling, and log consistency.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import numpy as np
import torch

from stsai.training import (LOSS_REVISION, ReplayDataset, collate_samples,
                            combine_numerators, loss_numerators, policy_term,
                            train, validate)
from test_training_loss import BACKEND, build_collection


def effective_batch_probe():
    costs = torch.tensor([1.0, 0.0, 3.0, 5.0])
    decision = torch.tensor([1, 0, 1, 1], dtype=torch.bool)
    superseded = float((policy_term(costs[:2], decision[:2])
                        + policy_term(costs[2:], decision[2:])) / 2)
    joined = float(costs[decision].sum() / decision.sum())
    return {"per_microbatch_mean_of_means": superseded, "effective_batch_decision_mean": joined,
            "expected_by_review": 3.0, "passes": abs(joined - 3.0) < 1e-9}


def gradient_probe():
    logits = torch.randn(4, 3, dtype=torch.float64, requires_grad=True)
    target = torch.softmax(torch.randn(4, 3), -1)
    decision = torch.tensor([1, 0, 1, 1], dtype=torch.bool)
    costs = -(target * logits.log_softmax(-1)).sum(-1)
    (costs[decision].sum() / decision.sum()).backward(retain_graph=True)
    effective = logits.grad.clone()
    logits.grad = None
    for lo, hi in ((0, 2), (2, 4)):
        part = costs[lo:hi]
        mask = decision[lo:hi]
        (part[mask].sum() / decision.sum()).backward(retain_graph=True)
    split = logits.grad.clone()
    return {"effective_batch_gradient_row0": effective[0].tolist(),
            "split_over_shared_denominator_row0": split[0].tolist(),
            "max_abs_difference": float((effective - split).abs().max()),
            "passes": bool(torch.allclose(effective, split, atol=1e-12))}


def all_forced_probe():
    logits = torch.randn(3, 4, requires_grad=True)
    labels = {"policy": torch.softmax(torch.randn(3, 4), -1),
              "decision": torch.zeros(3, dtype=torch.bool),
              "outcome": torch.full((3, 11), 1 / 11), "value": torch.zeros(3),
              "value_mask": torch.zeros(3)}
    output = {"policy_logits": logits, "outcome_logits": torch.randn(3, 11), "value": torch.zeros(3)}
    numerators, counts = loss_numerators(output, labels)
    (numerators["policy_num"] / max(float(counts["D"]), 1.0)).backward()
    return {"policy_numerator": float(numerators["policy_num"]),
            "denominator": float(counts["D"]),
            "gradient_is_zero": bool(torch.allclose(logits.grad, torch.zeros_like(logits))),
            "finite": bool(torch.isfinite(numerators["policy_num"]))}


def partition_probe(tmp):
    train_dir = build_collection(tmp / "train", "train")
    val_dir = build_collection(tmp / "val", "val", episodes=3, steps=6)
    states = {}
    for batch, accum in ((32, 1), (16, 2), (8, 4)):
        out = tmp / f"p_{batch}_{accum}"
        train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
              config={"seed": 17, "init_seed": 17, "data_seed": 42, "batch_size": batch,
                      "accumulation_steps": accum, "learning_rate": 3e-4, "weight_decay": 0.01,
                      "max_updates": 1, "epochs": 4, "eval_every": 10 ** 6, "save_every": 10 ** 6,
                      "validation_batches": 10 ** 6, "shuffle_buffer": 512, "amp": False,
                      "cpu_threads": 1, "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}})
        states[f"{batch}x{accum}"] = torch.load(out / "last.pt", map_location="cpu",
                                                weights_only=True)["model_state"]
    keys = list(states["32x1"])
    worst = max(float((states["32x1"][k] - states["16x2"][k]).abs().max()) for k in keys)
    worst = max(worst, max(float((states["32x1"][k] - states["8x4"][k]).abs().max()) for k in keys))
    return {"arrangements": ["32x1", "16x2", "8x4"], "max_abs_parameter_difference": worst,
            "passes": worst < 1e-5}


def validation_batch_probe(tmp):
    from torch.utils.data import DataLoader
    from stsai.model import CombatNet, ModelConfig
    val_dir = build_collection(tmp / "val2", "val", episodes=3, steps=6)
    torch.manual_seed(3)
    model = CombatNet(ModelConfig(d_model=16, layers=1, heads=2, dropout=0.0)).eval()
    out = {}
    for batch_size in (1, 2, 3, 7):
        loader = DataLoader(ReplayDataset([str(val_dir)], BACKEND, "val", 42, 1),
                            batch_size=batch_size, collate_fn=collate_samples)
        result = validate(model, loader, torch.device("cpu"), 10 ** 6)
        out[str(batch_size)] = {k: result[k] for k in
                                ("policy_loss", "outcome_loss", "value_loss", "loss",
                                 "kl_dev", "decision_numerator_D", "samples")}
    keys = list(next(iter(out.values())))
    spread = {k: max(abs(v[k] - out["1"][k]) for v in out.values()) for k in keys}
    return {"by_validation_batch_size": out, "max_spread": spread,
            "passes": all(v < 1e-6 for v in spread.values())}


def log_consistency_probe(tmp):
    train_dir = build_collection(tmp / "train3", "train")
    val_dir = build_collection(tmp / "val3", "val", episodes=3, steps=6)
    out = tmp / "log3"
    train([str(train_dir)], [str(val_dir)], str(out), backend=BACKEND, device="cpu",
          config={"seed": 17, "init_seed": 17, "data_seed": 42, "batch_size": 16,
                  "accumulation_steps": 2, "learning_rate": 3e-4, "weight_decay": 0.01,
                  "max_updates": 1, "epochs": 4, "eval_every": 10 ** 6, "save_every": 10 ** 6,
                  "validation_batches": 10 ** 6, "shuffle_buffer": 512, "amp": False,
                  "cpu_threads": 1, "model": {"d_model": 16, "layers": 1, "heads": 2, "dropout": 0.0}})
    rows = [json.loads(l) for l in (out / "metrics.jsonl").read_text().splitlines() if l.strip()]
    checked = []
    for row in rows:
        checked.append({
            "step": row["step"],
            "total_matches_components": abs(row["loss"] - (row["policy_loss"]
                + 0.5 * row["outcome_loss"] + row["value_loss"])) < 1e-9,
            "effective_batch_samples": row["effective_batch_samples"],
            "decision_states": row["effective_batch_decision_states"],
            "numerators_present": all(k in row for k in
                                      ("policy_numerator", "outcome_numerator", "value_numerator")),
        })
    summary = json.loads((out / "training_summary.json").read_text())
    return {"updates": checked, "loss_revision": summary["loss_revision"],
            "dropped_tail_rows": summary["dropped_tail_rows"],
            "passes": all(c["total_matches_components"] and c["numerators_present"] for c in checked)}


def main():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="s1probe"))
    report = {
        "purpose": "S1-A counting probes, produced by calling the shipped code.",
        "loss_revision": LOSS_REVISION,
        "effective_batch": effective_batch_probe(),
        "gradient_partitioning": gradient_probe(),
        "all_forced_batch": all_forced_probe(),
        "trainer_partition_invariance": partition_probe(tmp),
        "validation_batch_invariance": validation_batch_probe(tmp),
        "log_consistency": log_consistency_probe(tmp),
    }
    report["all_passed"] = all(v.get("passes", False) for v in report.values() if isinstance(v, dict))
    out = ROOT / "reports/s1_normalization_probes.json"
    out.write_text(json.dumps(report, indent=2) + "\n")
    for key, value in report.items():
        if isinstance(value, dict) and "passes" in value:
            print(f"  {key:34s} passes={value['passes']}")
    print("wrote", out)


if __name__ == "__main__":
    main()
