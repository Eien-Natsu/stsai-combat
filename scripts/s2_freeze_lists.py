#!/usr/bin/env python3
"""Freeze the S2 data lists and the two development sets before anything runs.

    python scripts/s2_freeze_lists.py [--out reports/s2_dev_lists.json]

Three things happen here, all before a single new trajectory is collected:

  1. the S1R shards and the labelled validation set are hashed and compared with
     the manifest that was shipped with S1R, so the round cannot silently train
     on a different D96 or V24;
  2. the original 256 development scenarios are re-materialised and checked
     against the frozen file, and the new DEV_PROBE256 is materialised from
     master_seed 20260919 and hashed;
  3. the overlaps between every pair of lists are computed and reported as they
     are - an identical (scenario, episode seed) pair is a duplicate, and an
     identical public opening with a different seed is not, and the two are
     counted separately rather than merged into "no collisions".

DEV_PROBE256 is a development probe, not a held-out test and not P6: it is
marked used the first time a comparison is read from it.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stsai.scenarios import make_scenario  # noqa: E402
from stsai.util import atomic_json, digest  # noqa: E402

MASTER_SEED_TRAIN = 20260916
MASTER_SEED_DEV_OLD = 20260917
MASTER_SEED_DEV_PROBE = 20260919
PROBE_COUNT = 256


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_shards(directory, expected, label):
    """Every shard the S1R delivery listed must still hash the same."""
    problems, checked = [], 0
    for name, want in sorted(expected.items()):
        path = Path(directory) / name
        if not path.is_file():
            problems.append(f"missing {name}")
            continue
        if sha256(path) != want:
            problems.append(f"hash changed: {name}")
        checked += 1
    return {"label": label, "verified": checked, "expected": len(expected),
            "problems": problems, "ok": not problems}


def scenario_list(split, count, master_seed, start=0):
    out = []
    for index in range(start, start + count):
        scenario, episode_seed, family = make_scenario("lightspeed_pilot", split, index, master_seed)
        out.append({"index": index, "family": family, "episode_seed": episode_seed,
                    "scenario": scenario, "scenario_sha256": digest(scenario),
                    "encounter": scenario["encounter"], "hp": scenario["hp"],
                    "deck_size": len(scenario["deck"])})
    return out


def identity(entry):
    return (entry["scenario_sha256"], entry["episode_seed"])


def overlap(left, right, left_name, right_name):
    left_ids = {identity(e): e for e in left}
    right_ids = {identity(e): e for e in right}
    duplicates = sorted(set(left_ids) & set(right_ids))
    left_openings = {e["scenario_sha256"] for e in left}
    right_openings = {e["scenario_sha256"] for e in right}
    shared_opening = left_openings & right_openings
    return {
        "left": left_name, "right": right_name,
        "identical_scenario_and_episode_seed": len(duplicates),
        "identical_public_opening_different_seed": len(shared_opening) - len(
            {s for s, _ in duplicates}),
        "duplicate_examples": [{"scenario_sha256": s[:16], "episode_seed": seed}
                               for s, seed in duplicates[:5]],
        "note": "a shared opening with a different episode seed is the generator coinceding, "
                "not leakage; an identical (scenario, seed) pair would be a duplicate",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/s2_dev_lists.json")
    parser.add_argument("--manifest", default="training/data_manifests.json")
    parser.add_argument("--dev-scenarios", default="runs/s1r_eval/dev_scenarios.json")
    parser.add_argument("--probe-out", default="runs/s2/dev_probe256.json")
    parser.add_argument("--old-out", default="runs/s2/dev_old256.json")
    args = parser.parse_args()

    manifest = json.loads((ROOT / args.manifest).read_text())
    d96 = verify_shards(ROOT / "data/s1r/train", manifest["splits"]["train"]["shards"], "D96")
    v24 = verify_shards(ROOT / "data/s1r/val", manifest["splits"]["val"]["shards"], "V24")
    if not (d96["ok"] and v24["ok"]):
        print(json.dumps({"D96": d96, "V24": v24}, indent=2))
        raise SystemExit("the S1R shards do not match the delivered manifest; STOP")

    frozen_old = json.loads((ROOT / args.dev_scenarios).read_text())
    old = [{"index": e["index"], "family": e["family"], "episode_seed": e["episode_seed"],
            "scenario": e["scenario"], "scenario_sha256": digest(e["scenario"]),
            "encounter": e["encounter"], "hp": e["hp"], "deck_size": e["deck_size"]}
           for e in frozen_old["scenarios"]]
    regenerated = scenario_list("val", len(frozen_old["scenarios"]), MASTER_SEED_DEV_OLD)
    old_matches = [identity(a) for a in old] == [identity(b) for b in regenerated]
    probe = scenario_list("val", PROBE_COUNT, MASTER_SEED_DEV_PROBE)

    d96_scenarios = scenario_list("train", 96, MASTER_SEED_TRAIN)
    add288_scenarios = scenario_list("train", 288, MASTER_SEED_TRAIN, start=96)
    v24_scenarios = scenario_list("val", 24, MASTER_SEED_TRAIN)

    atomic_json(ROOT / args.old_out, {
        "purpose": "DEV_OLD256: the development scenarios S1R already used. Reused, not held out.",
        "master_seed": MASTER_SEED_DEV_OLD, "count": len(old), "already_used": True,
        "regenerates_from_the_generator": old_matches, "scenarios": old})
    atomic_json(ROOT / args.probe_out, {
        "purpose": "DEV_PROBE256: a second development probe, materialised before any model was "
                   "trained for this round. Not a held-out test and not P6.",
        "master_seed": MASTER_SEED_DEV_PROBE, "count": len(probe),
        "used_for": "the primary D384-vs-D96 comparison; marked used from the first read",
        "scenarios": probe})

    record = {
        "purpose": "S2 data lists and development sets, frozen before collection and training.",
        "master_seeds": {"training_and_validation": MASTER_SEED_TRAIN,
                         "dev_old256": MASTER_SEED_DEV_OLD, "dev_probe256": MASTER_SEED_DEV_PROBE},
        "shards": {"D96": d96, "V24": v24,
                   "D96_manifest_sha256": digest(manifest["splits"]["train"]["shards"]),
                   "V24_manifest_sha256": digest(manifest["splits"]["val"]["shards"])},
        "lists": {
            "D96": {"count": len(d96_scenarios), "definition": "make_scenario(train, index 0-95, "
                                                               f"master_seed {MASTER_SEED_TRAIN})",
                    "sha256": digest([identity(e) for e in d96_scenarios])},
            "Dadd288": {"count": len(add288_scenarios),
                        "definition": f"make_scenario(train, index 96-383, master_seed {MASTER_SEED_TRAIN})",
                        "sha256": digest([identity(e) for e in add288_scenarios])},
            "D384": {"count": len(d96_scenarios) + len(add288_scenarios),
                     "definition": "D96 union Dadd288; D96 is a strict subset and appears once"},
            "V24": {"count": len(v24_scenarios),
                    "definition": f"make_scenario(val, index 0-23, master_seed {MASTER_SEED_TRAIN})",
                    "sha256": digest([identity(e) for e in v24_scenarios])},
            "DEV_OLD256": {"count": len(old), "sha256": digest([identity(e) for e in old])},
            "DEV_PROBE256": {"count": len(probe), "sha256": digest([identity(e) for e in probe])},
        },
        "DEV_OLD256_regenerates": old_matches,
        "overlaps": [
            overlap(probe, d96_scenarios, "DEV_PROBE256", "D96"),
            overlap(probe, v24_scenarios, "DEV_PROBE256", "V24"),
            overlap(probe, add288_scenarios, "DEV_PROBE256", "Dadd288"),
            overlap(old, d96_scenarios, "DEV_OLD256", "D96"),
            overlap(old, v24_scenarios, "DEV_OLD256", "V24"),
            overlap(old, add288_scenarios, "DEV_OLD256", "Dadd288"),
            overlap(d96_scenarios, add288_scenarios, "D96", "Dadd288"),
        ],
        "generator": {"module": "stsai.scenarios.make_scenario",
                      "source_sha256": sha256(ROOT / "src/stsai/scenarios.py"),
                      "scenario_revision": __import__("stsai.scenarios", fromlist=["x"]).SCENARIO_REVISION},
        "probe_policy": "DEV_PROBE256 enters no training and no validation; it is run only after "
                        "all six checkpoints are selected on V24, and it is reused afterwards at "
                        "its own risk",
    }
    atomic_json(ROOT / args.out, record)
    for entry in record["overlaps"]:
        print(f"{entry['left']} vs {entry['right']}: identical pairs "
              f"{entry['identical_scenario_and_episode_seed']}, shared openings "
              f"{entry['identical_public_opening_different_seed']}")
    print(f"wrote {args.out}, {args.probe_out}, {args.old_out}")


if __name__ == "__main__":
    main()
