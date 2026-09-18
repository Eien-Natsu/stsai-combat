#!/usr/bin/env python3
"""Compare the independent recomputation with the shipped S2 summary.

    python reports/s2r/t3_compare.py --shipped <paired_summary.json> \
        --recomputed <recomputed_s2.json> --out <comparison.json>

The tolerance is declared here, before the numbers are read: 1e-9 absolute. Both
sides resample the same scenarios with the same seed and replicate count, so the
only legitimate difference is the order floating-point sums are accumulated in. A
gap larger than that is a disagreement about the data, not about arithmetic, and
is reported as one rather than being absorbed.

The comparison never adopts the recomputed value over the shipped one: the shipped
record stays as it is and the difference is what gets reported.
"""
import argparse
import json
from pathlib import Path

TOLERANCE = 1e-9
SETS = ["dev_old256", "dev_probe256"]
SEEDS = ["s17", "s29", "s43"]
BASELINES = ["heuristic", "search"]


def compare(label, shipped, recomputed, rows):
    if shipped is None or recomputed is None:
        rows.append({"field": label, "shipped": shipped, "recomputed": recomputed,
                     "difference": None, "within_tolerance": False,
                     "note": "missing on one side"})
        return
    difference = abs(float(shipped) - float(recomputed))
    rows.append({"field": label, "shipped": float(shipped), "recomputed": float(recomputed),
                 "difference": difference, "within_tolerance": difference <= TOLERANCE})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shipped", required=True)
    parser.add_argument("--recomputed", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    shipped = json.loads(Path(args.shipped).read_text(encoding="utf-8"))
    recomputed = json.loads(Path(args.recomputed).read_text(encoding="utf-8"))
    rows = []
    for name in SETS:
        original = shipped["sets"][name]
        new = recomputed["comparisons"][name]
        for seed in SEEDS:
            compare(f"{name}/D384_minus_D96/{seed}/mean",
                    original["D384_minus_D96_per_seed"][seed]["mean"],
                    new["D384_minus_D96_per_seed"][seed]["mean"], rows)
            for index, bound in enumerate(("low", "high")):
                compare(f"{name}/D384_minus_D96/{seed}/ci95_{bound}",
                        original["D384_minus_D96_per_seed"][seed]["bootstrap95"][index],
                        new["D384_minus_D96_per_seed"][seed]["ci95"][index], rows)
        compare(f"{name}/D384_minus_D96/across_seeds/mean_of_seed_means",
                original["D384_minus_D96_across_seeds"]["mean_of_seed_means"],
                new["mean_of_seed_means"], rows)
        compare(f"{name}/D384_minus_D96/joint/mean",
                original["D384_minus_D96_joint"]["mean"], new["D384_minus_D96_joint"]["mean"], rows)
        for index, bound in enumerate(("low", "high")):
            compare(f"{name}/D384_minus_D96/joint/ci95_{bound}",
                    original["D384_minus_D96_joint"]["bootstrap95"][index],
                    new["D384_minus_D96_joint"]["ci95"][index], rows)
        for policy in sorted(original["versus_baselines"]):
            for baseline in BASELINES:
                key = f"{policy}_minus_{baseline}"
                compare(f"{name}/{key}/mean", original["versus_baselines"][policy][key]["mean"],
                        new[key]["mean"], rows)
                for index, bound in enumerate(("low", "high")):
                    compare(f"{name}/{key}/ci95_{bound}",
                            original["versus_baselines"][policy][key]["bootstrap95"][index],
                            new[key]["ci95"][index], rows)

    outside = [row for row in rows if not row["within_tolerance"]]
    report = {
        "purpose": "S2 shipped summary vs the independent recomputation of the same records.",
        "tolerance": TOLERANCE,
        "tolerance_basis": ("both sides resample the same scenarios with seed 20260920 and 20000 "
                            "replicates; only float summation order may differ"),
        "episodes_recomputed": recomputed["episodes_read"],
        "fields_compared": len(rows),
        "fields_outside_tolerance": len(outside),
        "comparisons": rows,
        "verdicts": {
            "shipped": shipped["conclusion"]["verdict"] if "conclusion" in shipped else None,
            "recomputed_supports_D384": recomputed["verdict"]["supports_D384"],
            "shipped_supports_D384": (shipped["conclusion"]["all_three_same_direction"]
                                      and shipped["conclusion"]["mean_of_seed_means"] > 0
                                      and shipped["conclusion"]["joint_lower_bound"] > 0)
            if "conclusion" in shipped else None,
        },
        "conclusion": ("the recomputation reproduces the shipped summary within the declared "
                       "tolerance; the fixed-budget verdict is unchanged"
                       if not outside else
                       f"{len(outside)} values differ beyond the declared tolerance"),
    }
    Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"{len(rows)} fields compared, {len(outside)} outside {TOLERANCE}")
    for row in outside[:10]:
        print("  ", row)
    print(report["conclusion"])
    print(f"verdicts: {json.dumps(report['verdicts'])}")
    raise SystemExit(1 if outside else 0)


if __name__ == "__main__":
    main()
