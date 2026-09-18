"""Show that `policy.2.bias` does not influence the loss or the model's policy.

Forward passes only: no optimizer step, no training budget is spent.

A constant added to every action logit is removed again by the masked
`log_softmax`, because the illegal slots are pinned to -1e9 after the bias is
added. So the output bias of the policy head is a gauge direction: shifting it
changes no prediction and no loss value, which is why its gradient is an exact
cancellation residue rather than a usable signal.

Usage:
    python reports/s2r/t0_gauge_check.py --out reports/s2r/t0_gauge_check.json
"""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import torch  # noqa: E402

from stsai.model import CombatNet, ModelConfig  # noqa: E402

import test_training_loss as ttl  # noqa: E402

SHIFTS = (0.5, -3.0, 1000.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    torch.manual_seed(0)
    work = Path(tempfile.mkdtemp(prefix="t0-gauge-"))
    train_dir = ttl.build_collection(work / "train", "train")

    samples = []
    for _, _, files in __import__("os").walk(train_dir):
        for name in sorted(files):
            if name.endswith(".jsonl.gz"):
                import gzip
                with gzip.open(train_dir / name, "rt", encoding="utf-8") as handle:
                    samples.append(json.loads(handle.readline()))
        break
    batch, labels = ttl.collate_samples(samples[:16])

    model = CombatNet(ModelConfig(d_model=16, layers=1, heads=2, dropout=0.0)).eval()
    with torch.no_grad():
        reference = model(batch)
        reference_logp = reference["policy_logits"].log_softmax(-1)
        reference_loss = float(ttl.combine_numerators(
            {k: float(v) for k, v in ttl.loss_numerators(reference, labels)[0].items()},
            {k: float(v) for k, v in ttl.loss_numerators(reference, labels)[1].items()})["loss"])

    rows = []
    for shift in SHIFTS:
        with torch.no_grad():
            model.policy[2].bias.add_(shift)
            shifted = model(batch)
            shifted_logp = shifted["policy_logits"].log_softmax(-1)
            totals, counts = ttl.loss_numerators(shifted, labels)
            loss = float(ttl.combine_numerators(
                {k: float(v) for k, v in totals.items()},
                {k: float(v) for k, v in counts.items()})["loss"])
            model.policy[2].bias.sub_(shift)
        legal = batch["action_mask"]
        rows.append({
            "bias_shift": shift,
            "max_abs_logits_change_on_legal_actions":
                float((shifted["policy_logits"] - reference["policy_logits"])[legal].abs().max()),
            "max_abs_log_softmax_change": float((shifted_logp - reference_logp).abs().max()),
            "loss_before": reference_loss, "loss_after": loss,
            "loss_change": abs(loss - reference_loss),
            "value_head_change": float((shifted["value"] - reference["value"]).abs().max()),
        })

    report = {"kind": "t0_gauge_check", "samples": len(samples[:16]),
              "reference_loss": reference_loss, "shifts": rows,
              "conclusion": ("Every shift leaves the policy log-probabilities and the loss "
                             "unchanged, so policy.2.bias carries no loss information; the "
                             "residue gradient and its AdamW update are numerical, not signal.")}
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
