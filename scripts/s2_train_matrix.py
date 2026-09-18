#!/usr/bin/env python3
"""Run the five new S2 training configurations, one process each.

    python scripts/s2_train_matrix.py [--runs D96_s29 D96_s43 ...] [--dry-run]

The run table is fixed by the protocol: D96 and D384, each at init_seed 17, 29
and 43, with D96_s17 reused from S1R rather than retrained. Every run keeps the
same model, effective batch, update ceiling and optimiser settings, and only the
initialisation seed and the training data change. data_seed stays 42 everywhere,
so the data order is identical across runs and the seeds differ only in weights.

A run whose output directory already holds a checkpoint is skipped, not
overwritten: re-running this script must not silently replace a finished run.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RUNS = [
    {"name": "D96_s29", "data": ["data/s1r/train"], "init_seed": 29},
    {"name": "D96_s43", "data": ["data/s1r/train"], "init_seed": 43},
    {"name": "D384_s17", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 17},
    {"name": "D384_s29", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 29},
    {"name": "D384_s43", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 43},
]
FROZEN = json.loads((ROOT / "configs/s1_m128_r0_s17.json").read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="*", default=[r["name"] for r in RUNS])
    parser.add_argument("--out", default="runs/s2")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    chosen = [r for r in RUNS if r["name"] in args.runs]
    if len(chosen) != len(args.runs):
        raise SystemExit(f"unknown run name in {args.runs}")
    if len(chosen) > 5:
        raise SystemExit("the protocol allows at most five new training runs")

    results = []
    for run in chosen:
        out = ROOT / args.out / run["name"] / "model"
        config_path = ROOT / args.out / run["name"] / "config.json"
        config = json.loads(json.dumps(FROZEN))
        config["training"]["init_seed"] = run["init_seed"]
        config["training"]["data_seed"] = 42
        if (out / "last.pt").exists():
            print(f"{run['name']}: a checkpoint already exists; skipping rather than overwriting")
            results.append({"run": run["name"], "skipped": "already trained"})
            continue
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        command = [sys.executable, "-m", "stsai", "train",
                   "--train-data", *[str(ROOT / d) for d in run["data"]],
                   "--val-data", str(ROOT / "data/s1r/val"),
                   "--output", str(out), "--backend", "lightspeed_pilot", "--device", "cuda",
                   "--config", str(config_path)]
        print(f"{run['name']}: {' '.join(command)}", flush=True)
        if args.dry_run:
            continue
        log = ROOT / args.log_dir / f"71_s2_train_{run['name']}.log"
        started = time.perf_counter()
        with log.open("w", encoding="utf-8") as handle:
            handle.write("$ " + " ".join(command) + "\n")
            handle.flush()
            result = subprocess.run(command, cwd=ROOT, stdout=handle, stderr=subprocess.STDOUT,
                                    env={**__import__("os").environ,
                                         "PYTHONPATH": str(ROOT / "src")})
        elapsed = time.perf_counter() - started
        summary_path = out / "training_summary.json"
        entry = {"run": run["name"], "data": run["data"], "init_seed": run["init_seed"],
                 "exit_code": result.returncode, "seconds": elapsed,
                 "log": str(log.relative_to(ROOT)),
                 "output": str(out.relative_to(ROOT))}
        if summary_path.is_file():
            summary = json.loads(summary_path.read_text())
            entry.update({"steps": summary["steps"],
                          "best_selection_metric": summary["best_selection_metric"],
                          "kl_dev_last": summary["validation"].get("kl_dev"),
                          "dropped_tail_rows": summary["dropped_tail_rows"]})
        results.append(entry)
        print(f"{run['name']}: exit {result.returncode} in {elapsed:.1f}s {entry.get('steps')} steps",
              flush=True)
        if result.returncode != 0:
            raise SystemExit(f"{run['name']} failed; stopping rather than continuing the matrix")

    (ROOT / args.out / "training_runs.json").write_text(
        json.dumps({"runs": results, "frozen_config": FROZEN}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
