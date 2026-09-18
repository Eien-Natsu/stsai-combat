#!/usr/bin/env python3
"""Export the selected checkpoint as a standalone inference weight.

    python scripts/export_inference_weights.py --checkpoint runs/.../best.pt \
        --out model/policy_weights.pt --source runs/.../last.pt

The file keeps everything a normal loader needs - model config, backend, every
semantic revision and the frozen training constants - and drops the optimizer
state. It records which step it was selected at and the hash of the training
checkpoint it came from, so the shipped file can be traced back to the run
without shipping the run.

The export is checked by loading it and comparing its outputs with the source
checkpoint on real observations; a mismatch aborts rather than shipping.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True, help="the selected checkpoint")
    parser.add_argument("--out", required=True)
    parser.add_argument("--source", default=None, help="last.pt, for the run provenance record")
    parser.add_argument("--observations", type=int, default=12)
    args = parser.parse_args()

    source_path = Path(args.checkpoint)
    checkpoint = torch.load(source_path, map_location="cpu", weights_only=True)
    if checkpoint.get("format_version") != 1:
        raise SystemExit("unknown checkpoint format")
    for key in ("backend", "encoding_revision", "observation_schema", "loss_revision",
                "sampler_revision", "model_config", "model_state"):
        if key not in checkpoint:
            raise SystemExit(f"the selected checkpoint does not record {key}")

    exported = {key: value for key, value in checkpoint.items() if key != "optimizer_state"}
    exported["export"] = {
        "purpose": "selected inference weights; optimizer state removed",
        "source_checkpoint": str(source_path),
        "source_sha256": sha256(source_path),
        "source_step": checkpoint.get("step"),
        "source_epoch": checkpoint.get("epoch"),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.save(exported, out)
    if args.source:
        exported["export"]["run_last_checkpoint_sha256"] = sha256(args.source)

    # Load it back the way any consumer would, and require identical outputs.
    from stsai.model import ModelEvaluator, load_checkpoint
    from stsai.scenarios import make_scenario
    from stsai.native import NativeBattle

    reloaded, _ = load_checkpoint(out)
    reference, _ = load_checkpoint(source_path)
    differences = []
    for index in range(args.observations):
        scenario, seed, _ = make_scenario("lightspeed_pilot", "val", index, 20260917)
        obs = NativeBattle(scenario, seed).observe()
        a = ModelEvaluator(reference, "cpu", "lightspeed_pilot").evaluate(obs)
        b = ModelEvaluator(reloaded, "cpu", "lightspeed_pilot").evaluate(obs)
        if not np.allclose(a[0], b[0], atol=0, rtol=0) or a[1] != b[1]:
            differences.append(index)
    if differences:
        raise SystemExit(f"the export does not reproduce the source on cases {differences}")

    # Record the export in the run directory so the run points at what shipped.
    run_record = Path(args.checkpoint).parent / "export.json"
    run_record.write_text(json.dumps({
        "exported": str(out), "sha256": sha256(out), "bytes": out.stat().st_size,
        "source": str(source_path), "source_sha256": exported["export"]["source_sha256"],
        "step": exported["export"]["source_step"], "epoch": exported["export"]["source_epoch"],
        "bit_identical_to_source_on_cases": args.observations,
        "optimizer_state_removed": "optimizer_state" not in exported,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1e6:.2f} MB), identical on {args.observations} cases")
    print(json.dumps(exported["export"], indent=1))


if __name__ == "__main__":
    main()
