#!/usr/bin/env python3
"""Write the data records the S2 package ships.

    python scripts/s2_package_data.py --out <package directory>

Four artefacts: the initial scenarios of every list this round used, the
composition of D384 with both sources' provenance and shard hashes, the coverage
counts behind "how much data is this really", and the materialised development
sets the evaluation read.

The training shards themselves are not shipped: the scenarios plus the locked
generator and the recorded seeds regenerate them deterministically, and the
manifest lets a reviewer check any shard it does have.
"""
import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.util import digest  # noqa: E402


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def initial_scenarios(directory, split):
    out = []
    for path in sorted(Path(directory).glob("episode_*.meta.json")):
        meta = json.loads(path.read_text())
        out.append({"list": split, "index": meta["episode_index"],
                    "episode_seed": meta["episode_seed"], "family": meta["family"],
                    "scenario_sha256": digest(meta["scenario"]), "scenario": meta["scenario"]})
    return out


def count_rows(directory):
    rows = decisions = 0
    families = Counter()
    for shard in sorted(Path(directory).glob("episode_*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                rows += 1
                if len(row["observation"]["actions"]) > 1:
                    decisions += 1
    for path in sorted(Path(directory).glob("episode_*.meta.json")):
        families[json.loads(path.read_text())["family"]] += 1
    return rows, decisions, dict(sorted(families.items()))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    (out / "data").mkdir(parents=True, exist_ok=True)
    (out / "evaluation").mkdir(parents=True, exist_ok=True)

    d96 = initial_scenarios(ROOT / "data/s1r/train", "D96")
    add288 = initial_scenarios(ROOT / "data/s2/add288", "Dadd288")
    v24 = initial_scenarios(ROOT / "data/s1r/val", "V24")
    with gzip.open(out / "data/initial_scenarios.json.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "purpose": "Initial scenarios of every training and validation list in this round.",
            "note": "the shards are not shipped; these plus the locked generator and the recorded "
                    "master seeds regenerate them deterministically",
            "D96": d96, "Dadd288": add288, "V24": v24}, sort_keys=True) + "\n")

    d96_rows, d96_dec, d96_families = count_rows(ROOT / "data/s1r/train")
    add_rows, add_dec, add_families = count_rows(ROOT / "data/s2/add288")
    v24_rows, v24_dec, v24_families = count_rows(ROOT / "data/s1r/val")
    collection_reports = json.loads((ROOT / "reports/s2_collection_report.json").read_text())
    s1r_report = json.loads((ROOT / "reports/s1r_collection_report.json").read_text())

    composition = {
        "purpose": "What D384 is made of, and where each half came from.",
        "D384": {"definition": "D96 union Dadd288, read as two directories",
                 "episodes": len(d96) + len(add288),
                 "rows": d96_rows + add_rows,
                 "decision_states": d96_dec + add_dec,
                 "strict_subset_check": "D96 is a subset by construction; the 96 indices appear "
                                        "once, in data/s1r/train"},
        "sources": {
            "D96": {"directory": "data/s1r/train", "episodes": len(d96), "rows": d96_rows,
                    "decision_states": d96_dec, "families": d96_families,
                    "fingerprint": json.loads((ROOT / "data/s1r/train/collection.json").read_text())["fingerprint"],
                    "origin": "rebuilt in S1R under the fixed sampler; shards verified against the "
                              "manifest S1R shipped",
                    "shards": json.loads((ROOT / "training/data_manifests.json").read_text())["splits"]["train"]["shards"]},
            "Dadd288": {"directory": "data/s2/add288", "episodes": len(add288), "rows": add_rows,
                        "decision_states": add_dec, "families": add_families,
                        "fingerprint": json.loads((ROOT / "data/s2/add288/collection.json").read_text())["fingerprint"],
                        "origin": "collected this round, one pass, two workers",
                        "shards": collection_reports["shards"],
                        "normalized_sample_hash": collection_reports["normalized_sample_hash"]},
            "V24": {"directory": "data/s1r/val", "episodes": len(v24), "rows": v24_rows,
                    "decision_states": v24_dec, "families": v24_families},
        },
        "hashes": {"shard_hash": "sha256 of the compressed shard file",
                   "normalized_sample_hash": "digest over the samples with every timing field "
                                             "removed, so two machines that took different amounts "
                                             "of time still agree"},
        "s1r_collection_report": s1r_report["splits"]["train"],
    }
    (out / "data/composition_and_shards.json").write_text(
        json.dumps(composition, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    coverage = {
        "purpose": "How much data each condition actually is, and how much of it a run saw.",
        "conditions": {
            "D96": {"episodes": len(d96), "rows": d96_rows, "decision_states": d96_dec,
                    "forced_states": d96_rows - d96_dec, "families": d96_families},
            "D384": {"episodes": len(d96) + len(add288), "rows": d96_rows + add_rows,
                     "decision_states": d96_dec + add_dec,
                     "forced_states": (d96_rows + add_rows) - (d96_dec + add_dec),
                     "families": {k: d96_families.get(k, 0) + add_families.get(k, 0)
                                  for k in sorted(set(d96_families) | set(add_families))}},
            "V24": {"episodes": len(v24), "rows": v24_rows, "decision_states": v24_dec,
                    "families": v24_families},
        },
        "seen_per_run": "training/runs.json records, per run, the rows and decision states pushed "
                        "through an update (with repeats) and the distinct rows its data holds",
        "overlaps": json.loads((ROOT / "reports/s2_dev_lists.json").read_text())["overlaps"],
        "note": "rows seen counts repeats across epochs; the distinct figures come from the data. "
                "500 updates at an effective batch of 32 is 16,000 rows for every run, so a D96 "
                "run passes over its 1,774 rows roughly nine times and a D384 run over its 6,891 "
                "roughly twice.",
    }
    (out / "data/coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sets = {}
    for name in ("dev_old256", "dev_probe256"):
        payload = json.loads((ROOT / "runs/s2" / f"{name}.json").read_text())
        sets[name] = payload
    with gzip.open(out / "evaluation/scenarios.json.gz", "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "purpose": "The two development sets the evaluation read, exactly as materialised.",
            "dev_old256": {"already_used": True, "master_seed": sets["dev_old256"]["master_seed"],
                           "scenarios": sets["dev_old256"]["scenarios"]},
            "dev_probe256": {"already_used": False,
                             "master_seed": sets["dev_probe256"]["master_seed"],
                             "scenarios": sets["dev_probe256"]["scenarios"]},
            "note": "DEV_PROBE256 is a development probe, not a held-out test and not P6; it is "
                    "marked used from the first comparison read from it",
        }, sort_keys=True) + "\n")

    print(f"wrote data/initial_scenarios.json.gz ({len(d96)}+{len(add288)}+{len(v24)}), "
          f"data/composition_and_shards.json, data/coverage.json, evaluation/scenarios.json.gz")


if __name__ == "__main__":
    main()
