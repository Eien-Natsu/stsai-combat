#!/usr/bin/env python3
"""Summarise the six logical runs: selected checkpoints, coverage and hashes.

    python scripts/s2_training_summary.py [--out-dir training]

D96_s17 is the S1R run, reused rather than retrained; the other five are this
round's. Nothing here reselects anything: the selected step is the one the
training run itself recorded, under the protocol's rule (lowest kl_dev on the
full V24 validation set, ties keeping the earlier step).

Coverage is reported as it is rather than as "epochs": how many rows and decision
states each run actually pushed through an update, how many exist in its data in
total, and how many times the run therefore saw its own data. Two runs at the
same update ceiling see the same number of samples; they differ in how much of
that is new.
"""
import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.util import atomic_json, digest  # noqa: E402

RUNS = [
    {"run": "D96_s17", "data": ["data/s1r/train"], "init_seed": 17,
     "directory": "runs/s1r/M128-R0-s17-S1R/model", "reused_from": "S1R"},
    {"run": "D96_s29", "data": ["data/s1r/train"], "init_seed": 29,
     "directory": "runs/s2/D96_s29/model"},
    {"run": "D96_s43", "data": ["data/s1r/train"], "init_seed": 43,
     "directory": "runs/s2/D96_s43/model"},
    {"run": "D384_s17", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 17,
     "directory": "runs/s2/D384_s17/model"},
    {"run": "D384_s29", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 29,
     "directory": "runs/s2/D384_s29/model"},
    {"run": "D384_s43", "data": ["data/s1r/train", "data/s2/add288"], "init_seed": 43,
     "directory": "runs/s2/D384_s43/model"},
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def dataset_size(directories):
    """Rows and decision states that exist, over the directories a run reads."""
    total_rows, decision_rows, episodes = 0, 0, 0
    for directory in directories:
        for shard in sorted((ROOT / directory).glob("episode_*.jsonl.gz")):
            episodes += 1
            with gzip.open(shard, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    total_rows += 1
                    if len(row["observation"]["actions"]) > 1:
                        decision_rows += 1
    return {"episodes": episodes, "rows": total_rows, "decision_states": decision_rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="training")
    args = parser.parse_args()
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    dataset_cache = {}
    runs, metrics_lines, validation_lines, csv_lines = [], [], [], [
        "run,data,init_seed,selected_step,selected_kl_dev,teacher_choice_agreement,last_step,"
        "last_kl_dev,selected_sha256,last_sha256,parameters"]
    for spec in RUNS:
        directory = ROOT / spec["directory"]
        if not (directory / "training_summary.json").is_file():
            raise SystemExit(f"{spec['run']}: no training output at {directory}")
        run_json = json.loads((directory / "run.json").read_text())
        summary = json.loads((directory / "training_summary.json").read_text())
        validations = jsonl(directory / "validation.jsonl")
        metrics = jsonl(directory / "metrics.jsonl")
        selected_step = summary["best_selection_metric"][1]
        selected = next(v for v in validations if v["step"] == selected_step)
        last = validations[-1]
        key = tuple(spec["data"])
        if key not in dataset_cache:
            dataset_cache[key] = dataset_size(spec["data"])

        for row in metrics:
            metrics_lines.append({"run": spec["run"], "init_seed": spec["init_seed"],
                                  "data": "+".join(spec["data"]), **row})
        for row in validations:
            validation_lines.append({"run": spec["run"], "init_seed": spec["init_seed"],
                                     "data": "+".join(spec["data"]), **row})

        record = {
            "run": spec["run"], "data": spec["data"], "init_seed": spec["init_seed"],
            "reused_from": spec.get("reused_from"),
            "directory": spec["directory"],
            "training_config": run_json["config"],
            "data_fingerprint": run_json["data_fingerprint"],
            "data_provenance": run_json.get("data_provenance"),
            "parameters": run_json["parameters"],
            "device": run_json["device"], "amp_bfloat16": run_json["amp_bfloat16"],
            "steps": summary["steps"],
            "selection_metric": summary["selection_metric"],
            "selected": {"step": selected_step, "kl_dev": selected["kl_dev"],
                         "teacher_choice_agreement_decision_states":
                             selected.get("teacher_choice_agreement_decision_states"),
                         "teacher_top1_agreement_legacy": selected.get("teacher_top1_agreement"),
                         "teacher_entropy_decision": selected.get("teacher_entropy_decision"),
                         "policy_ce_decision": selected.get("policy_ce_decision"),
                         "loss": selected.get("loss"),
                         "sha256": sha256(directory / "best.pt")},
            "last": {"step": last["step"], "kl_dev": last["kl_dev"],
                     "teacher_choice_agreement_decision_states":
                         last.get("teacher_choice_agreement_decision_states"),
                     "sha256": sha256(directory / "last.pt")},
            "coverage": {
                "updates": len(metrics),
                "rows_seen_with_repeats": sum(m["effective_batch_samples"] for m in metrics),
                "decision_states_seen_with_repeats":
                    sum(m["effective_batch_decision_states"] for m in metrics),
                "masked_states_seen_with_repeats":
                    sum(m["effective_batch_masked_states"] for m in metrics),
                "dataset": dataset_cache[key],
                "dropped_tail_rows": summary["dropped_tail_rows"],
                "epochs_reached": metrics[-1]["epoch"],
                "passes_over_its_own_rows":
                    round(sum(m["effective_batch_samples"] for m in metrics)
                          / max(dataset_cache[key]["rows"], 1), 3),
                "note": "rows_seen counts every row pushed through an update, including repeats "
                        "across epochs; the dataset figures count distinct rows and are taken "
                        "from the data itself",
            },
            "elapsed_seconds": summary.get("elapsed_seconds"),
            "validations": len(validations),
        }
        runs.append(record)
        csv_lines.append(",".join(str(x) for x in (
            spec["run"], "+".join(spec["data"]), spec["init_seed"], selected_step,
            selected["kl_dev"], selected.get("teacher_choice_agreement_decision_states"),
            last["step"], last["kl_dev"], record["selected"]["sha256"][:16],
            record["last"]["sha256"][:16], run_json["parameters"])))

    with gzip.open(out_dir / "metrics.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in metrics_lines:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    with gzip.open(out_dir / "validation.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in validation_lines:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (out_dir / "selected_summary.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")
    atomic_json(out_dir / "runs.json", {
        "purpose": "The six logical runs of the S2 matrix: five new, D96_s17 reused from S1R.",
        "selection_rule": "lowest kl_dev on the full V24 set, ties keep the earlier step; the "
                          "development sets are never used to select",
        "frozen_config": json.loads((ROOT / "configs/s1_m128_r0_s17.json").read_text())["training"],
        "runs": runs,
    })
    for record in runs:
        print(f"{record['run']:9s} selected step {record['selected']['step']:3d} "
              f"kl_dev {record['selected']['kl_dev']:.5f} "
              f"teacher {record['selected']['teacher_choice_agreement_decision_states']} "
              f"rows_seen {record['coverage']['rows_seen_with_repeats']} "
              f"distinct {record['coverage']['dataset']['rows']}")


if __name__ == "__main__":
    main()
