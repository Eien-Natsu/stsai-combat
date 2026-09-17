#!/usr/bin/env python3
"""Run the frozen 2x2x3 generalisation matrix, serially, on one GPU.

Width 128/192 x regularisation R0/R1 x training seeds 17/29/43. The protocol is
written to disk BEFORE the first run and never rewritten, so a later reader can
tell what was planned from what was actually executed.

Data order is held fixed across the whole matrix (data_seed) so that two widths
differ only by their shape; the per-run seed drives initialisation alone.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def build_protocol(base_config):
    from stsai.encoding import ENCODING_REVISION
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import SCHEMA_VERSION

    training = base_config["training"]
    r0 = {"dropout": training["model"]["dropout"], "weight_decay": training["training_weight_decay"]}
    # The task fixes R1 in advance: dropout +0.10 capped at 0.50, weight decay
    # x5 floored at 0.01. Recorded here before any run so it cannot be tuned.
    r1 = {"dropout": min(r0["dropout"] + 0.10, 0.50),
          "weight_decay": max(5 * r0["weight_decay"], 0.01)}
    return {"r0": r0, "r1": r1,
            "versions": {"observation_schema": SCHEMA_VERSION, "encoding_revision": ENCODING_REVISION,
                         "utility_revision": UTILITY_REVISION, "scenario_revision": SCENARIO_REVISION}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-data", nargs="+", required=True)
    parser.add_argument("--val-data", nargs="+", required=True)
    parser.add_argument("--output-root", default="runs/matrix")
    parser.add_argument("--protocol", default="reports/generalization_protocol.json")
    parser.add_argument("--seeds", nargs="+", type=int, default=[17, 29, 43])
    parser.add_argument("--widths", nargs="+", type=int, default=[128, 192])
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--updates", type=int, default=500)
    parser.add_argument("--eval-every", type=int, default=25)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base = json.loads((ROOT / "configs" / "native_pilot.json").read_text())
    training = base["training"]
    variants = build_protocol({"training": {**training,
                                            "training_weight_decay": training["weight_decay"]}})

    # 4 heads divides both 128 and 192, so head COUNT stays fixed and the head
    # dimension changes with width; that is reported as part of the width arm.
    cells = []
    for width in args.widths:
        for reg in ("R0", "R1"):
            for seed in args.seeds:
                cells.append({"id": f"M{width}-{reg}-s{seed}", "d_model": width, "reg": reg,
                              "init_seed": seed, "data_seed": 42, "heads": args.heads})
    for cell in cells:
        if cell["d_model"] % args.heads:
            raise SystemExit(f"{args.heads} heads does not divide d_model={cell['d_model']}")

    protocol = {
        "purpose": "Frozen generalisation matrix. Written before the first run and not rewritten.",
        "matrix": {"widths": args.widths, "regularisation": ["R0", "R1"], "seeds": args.seeds,
                   "cells": len(cells)},
        "regularisation": variants,
        "head_count": args.heads,
        "head_count_note": "4 divides 128 and 192, so head count is held fixed and head "
                           "dimension varies with width (32 vs 48).",
        "training": {"max_updates": args.updates, "eval_every": args.eval_every, "epochs": args.epochs,
                     "batch_size": training["batch_size"],
                     "accumulation_steps": training["accumulation_steps"],
                     "effective_batch": training["batch_size"] * training["accumulation_steps"],
                     "learning_rate": training["learning_rate"],
                     "validation_batches": training["validation_batches"]},
        "selection": "kl_dev = mean over battles of (battle mean decision-state KL); ties keep the earlier step",
        "policy_loss_normalisation": "decision states only (legal_actions > 1)",
        "expected_runs": len(cells),
        "planned": cells,
    }
    path = ROOT / args.protocol
    if path.exists():
        existing = json.loads(path.read_text())
        if existing.get("planned") != cells:
            raise SystemExit("Protocol on disk differs from this run; refusing to rewrite it")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
        print("wrote", path)

    root = ROOT / args.output_root
    root.mkdir(parents=True, exist_ok=True)
    resolved, executed = [], []
    for cell in cells:
        out = root / cell["id"]
        cfg = {
            "seed": cell["init_seed"], "init_seed": cell["init_seed"], "data_seed": cell["data_seed"],
            "batch_size": training["batch_size"], "accumulation_steps": training["accumulation_steps"],
            "learning_rate": training["learning_rate"],
            "weight_decay": variants[cell["reg"].lower()]["weight_decay"],
            "max_updates": args.updates, "epochs": args.epochs,
            "eval_every": args.eval_every, "save_every": args.eval_every,
            "validation_batches": training["validation_batches"],
            "shuffle_buffer": training["shuffle_buffer"], "amp": training["amp"],
            "cpu_threads": training["cpu_threads"],
            "model": {"d_model": cell["d_model"], "layers": training["model"]["layers"],
                      "heads": args.heads, "dropout": variants[cell["reg"].lower()]["dropout"]},
        }
        resolved.append({**cell, "config": cfg})
        if args.dry_run:
            continue
        # Each cell gets its own config file: the CLI reads a config path, and a
        # per-cell file is the auditable record of what was actually run.
        out.mkdir(parents=True, exist_ok=True)
        cell_config = out / "config.json"
        cell_config.write_text(json.dumps({**base, "training": cfg}, indent=2) + "\n", encoding="utf-8")
        if (out / "model" / "best.pt").exists():
            executed.append({**cell, "status": "already_present"})
            continue
        started = time.perf_counter()
        result = subprocess.run(
            [sys.executable, "-m", "stsai", "train",
             "--train-data", *args.train_data, "--val-data", *args.val_data,
             "--output", str(out / "model"), "--device", args.device,
             "--backend", "lightspeed_pilot", "--config", str(cell_config)],
            cwd=ROOT, capture_output=True, text=True)
        status = "ok" if result.returncode == 0 else f"failed({result.returncode})"
        executed.append({**cell, "status": status, "seconds": time.perf_counter() - started,
                         "stdout_tail": result.stdout[-400:] if status != "ok" else None,
                         "stderr_tail": result.stderr[-400:] if status != "ok" else None})
        print(json.dumps({k: v for k, v in executed[-1].items() if k != "config"}))

    (root / "matrix.json").write_text(json.dumps(
        {"planned": cells, "resolved": resolved, "executed": executed}, indent=2) + "\n", encoding="utf-8")
    print(f"executed {len([e for e in executed if e['status'] in ('ok','already_present')])}/{len(cells)}")


if __name__ == "__main__":
    main()
