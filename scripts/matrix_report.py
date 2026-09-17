#!/usr/bin/env python3
"""Summarise the frozen generalisation matrix: all 12 runs, paired by seed.

Reports every seed, not the luckiest one, and separates the two arms:
  width   192 - 128 at the same regularisation
  reg     R1 - R0 at the same width
Dispersions are across the three training seeds only, so they describe training
randomness conditioned on these three runs rather than a population.
"""
import argparse
import json
import statistics as stats
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIELDS = ["kl_dev", "kl_over_decision_states", "policy_kl", "teacher_entropy",
          "teacher_top1_agreement", "teacher_choice_agreement",
          "teacher_choice_agreement_decision_states", "loss", "policy_loss",
          "outcome_loss", "value_loss"]


def load(root):
    rows = []
    for cell in sorted(p for p in root.iterdir() if p.is_dir()):
        summary_path = cell / "model" / "training_summary.json"
        if not summary_path.exists():
            continue
        summary = json.loads(summary_path.read_text())
        run = json.loads((cell / "model" / "run.json").read_text())
        metrics = [json.loads(line) for line in (cell / "model" / "metrics.jsonl").read_text().splitlines() if line.strip()]
        best_step = summary.get("best_selection_metric", [None, None])[1]
        rows.append({
            "cell": cell.name, "d_model": run["config"]["model"]["d_model"],
            "dropout": run["config"]["model"]["dropout"], "weight_decay": run["config"]["weight_decay"],
            "init_seed": run["config"]["init_seed"], "data_seed": run["config"]["data_seed"],
            "parameters": run["parameters"], "amp_bfloat16": run["amp_bfloat16"],
            "peak_allocated_bytes": max((m.get("peak_allocated_bytes", 0) for m in metrics), default=0),
            "elapsed_seconds": summary["elapsed_seconds"], "best_step": best_step,
            **{f: summary["validation"].get(f) for f in FIELDS},
            "decision_states": summary["validation"].get("decision_states"),
            "forced_states": summary["validation"].get("forced_states"),
            "battles_seen": summary["validation"].get("battles_seen"),
            "battles_with_decisions": summary["validation"].get("battles_with_decisions"),
            "battles_without_decisions": summary["validation"].get("battles_without_decisions"),
            "samples": summary["validation"].get("samples"),
        })
    return rows


def paired(rows, key_a, key_b, metric):
    """Pair by (init_seed) with the other factor held fixed."""
    index = {(r["d_model"], r["weight_decay"], r["init_seed"]): r for r in rows}
    out = []
    for r in rows:
        a = {**r, key_a: key_b}
        other = index.get((a["d_model"], a["weight_decay"], a["init_seed"]))
        if other is None:
            continue
        out.append((r["cell"], {**{k: r[k] for k in ("d_model", "dropout", "weight_decay", "init_seed")},
                                "a": r[metric], "b": other[metric],
                                "delta": other[metric] - r[metric] if other[metric] is not None else None}))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="runs/matrix")
    parser.add_argument("--csv", default="reports/generalization_matrix.csv")
    parser.add_argument("--md", default="reports/generalization_matrix.md")
    parser.add_argument("--json", default="reports/generalization_matrix.json")
    args = parser.parse_args()

    rows = load(ROOT / args.root)
    if len(rows) != 12:
        raise SystemExit(f"Expected 12 runs, found {len(rows)}")

    columns = ["cell", "d_model", "dropout", "weight_decay", "init_seed", "parameters",
               "best_step", "elapsed_seconds", "peak_allocated_bytes", "battles_seen",
               "battles_with_decisions", "battles_without_decisions", "decision_states",
               "forced_states", "samples"] + FIELDS
    csv_path = ROOT / args.csv
    csv_path.write_text(",".join(columns) + "\n" + "\n".join(
        ",".join(str(r.get(c)) for c in columns) for r in rows) + "\n", encoding="utf-8")

    def group(metric, **filters):
        return [r[metric] for r in rows
                if all(r[k] == v for k, v in filters.items()) and r[metric] is not None]

    width_arm, reg_arm = [], []
    for width in sorted({r["d_model"] for r in rows}):
        for wd in sorted({r["weight_decay"] for r in rows}):
            for seed in sorted({r["init_seed"] for r in rows}):
                a = next((r for r in rows if r["d_model"] == width and r["weight_decay"] == wd and r["init_seed"] == seed), None)
                if a is None:
                    continue
                if width == 128:
                    b = next((r for r in rows if r["d_model"] == 192 and r["weight_decay"] == wd and r["init_seed"] == seed), None)
                    if b:
                        width_arm.append({"seed": seed, "weight_decay": wd, "m128": a["kl_dev"], "m192": b["kl_dev"],
                                          "delta_192_minus_128": b["kl_dev"] - a["kl_dev"]})
                if wd == 0.01:
                    b = next((r for r in rows if r["d_model"] == width and r["weight_decay"] == 0.05 and r["init_seed"] == seed), None)
                    if b:
                        reg_arm.append({"seed": seed, "d_model": width, "r0": a["kl_dev"], "r1": b["kl_dev"],
                                        "delta_r1_minus_r0": b["kl_dev"] - a["kl_dev"]})

    def describe(values):
        return {"n": len(values), "mean": stats.mean(values), "sd": stats.stdev(values) if len(values) > 1 else 0.0,
                "min": min(values), "max": max(values)}

    report = {
        "scope": "development generalisation matrix; not a strength or original-game result",
        "runs": len(rows),
        "primary_metric": "kl_dev (mean over battles of battle mean decision-state KL), lower is better",
        "by_cell": rows,
        "width_arm_192_minus_128": {
            "pairs": width_arm, "delta": describe([p["delta_192_minus_128"] for p in width_arm])},
        "reg_arm_r1_minus_r0": {
            "pairs": reg_arm, "delta": describe([p["delta_r1_minus_r0"] for p in reg_arm])},
        "cost": {
            "peak_allocated_bytes_max": max(r["peak_allocated_bytes"] for r in rows),
            "elapsed_seconds_mean": stats.mean([r["elapsed_seconds"] for r in rows]),
            "parameters_by_width": {w: next(r["parameters"] for r in rows if r["d_model"] == w)
                                    for w in sorted({r["d_model"] for r in rows})},
            "note": "128 and 192 are not equal FLOPs; the update count is fixed, not the compute.",
        },
        "validation_coverage": {
            "battles_seen": sorted({r["battles_seen"] for r in rows}),
            "samples": sorted({r["samples"] for r in rows}),
            "note": "Full development validation split, not a batch prefix.",
        },
        "caveats": [
            "Dispersions span three training seeds only; they characterise training randomness "
            "conditioned on these runs, not a population of runs.",
            "The development split has been used for early stopping and selection throughout, "
            "so it is a reusable development set and never a blind test.",
        ],
    }
    (ROOT / args.json).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = ["# 泛化矩阵（128/192 × R0/R1 × 3 seeds）", "",
             "主指标 `kl_dev`：每场战斗内先对决策状态求平均 KL，再对战斗求平均；越低越好。",
             "选择规则在开跑前冻结（见 `reports/generalization_protocol.json`）。", "",
             "| cell | d_model | dropout | wd | seed | kl_dev | kl(decision) | policy_kl | H_teacher | agree(dec) | best_step |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r["d_model"], r["weight_decay"], r["init_seed"])):
        lines.append(f"| {r['cell']} | {r['d_model']} | {r['dropout']} | {r['weight_decay']} | {r['init_seed']} | "
                     f"{r['kl_dev']:.5f} | {r['kl_over_decision_states']:.5f} | {r['policy_kl']:.5f} | "
                     f"{r['teacher_entropy']:.4f} | {r['teacher_choice_agreement_decision_states']:.3f} | {r['best_step']} |")
    lines += ["", "## 配对差", "",
              f"**192 − 128（同正则）**：n={report['width_arm_192_minus_128']['delta']['n']}，"
              f"均值 {report['width_arm_192_minus_128']['delta']['mean']:+.5f}，"
              f"sd {report['width_arm_192_minus_128']['delta']['sd']:.5f}", "",
              "| seed | wd | M128 | M192 | Δ(192−128) |", "|---|---|---|---|---|"]
    for p in width_arm:
        lines.append(f"| {p['seed']} | {p['weight_decay']} | {p['m128']:.5f} | {p['m192']:.5f} | {p['delta_192_minus_128']:+.5f} |")
    lines += ["", f"**R1 − R0（同宽度）**：n={report['reg_arm_r1_minus_r0']['delta']['n']}，"
                  f"均值 {report['reg_arm_r1_minus_r0']['delta']['mean']:+.5f}，"
                  f"sd {report['reg_arm_r1_minus_r0']['delta']['sd']:.5f}", "",
              "| seed | d_model | R0 | R1 | Δ(R1−R0) |", "|---|---|---|---|---|"]
    for p in reg_arm:
        lines.append(f"| {p['seed']} | {p['d_model']} | {p['r0']:.5f} | {p['r1']:.5f} | {p['delta_r1_minus_r0']:+.5f} |")
    lines += ["", "## 成本", "",
              f"- 参数量：{report['cost']['parameters_by_width']}",
              f"- 峰值显存（全部运行的最大值）：{report['cost']['peak_allocated_bytes_max']} B",
              f"- 单次训练耗时均值：{report['cost']['elapsed_seconds_mean']:.1f} s",
              f"- 验证覆盖：每场运行都遍历了完整开发验证集，battles_seen={report['validation_coverage']['battles_seen']}，"
              f"samples={report['validation_coverage']['samples']}", "",
              "> 128 与 192 不是相同 FLOPs；这里固定的是更新数，不是算力。", ""]
    (ROOT / args.md).write_text("\n".join(lines), encoding="utf-8")

    print(json.dumps({"width_arm": report["width_arm_192_minus_128"]["delta"],
                      "reg_arm": report["reg_arm_r1_minus_r0"]["delta"],
                      "cost": report["cost"]}, indent=2))
    print("wrote", args.csv, args.md, args.json)


if __name__ == "__main__":
    main()
