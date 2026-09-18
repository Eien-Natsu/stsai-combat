#!/usr/bin/env python3
"""Show that the S2 header patch changes nothing the S1R artefacts depend on.

    python scripts/gen_semantic_compatibility.py [--out reports/s2_semantic_compatibility.json]

The S2 round reuses the S1R training shards, the labelled validation set and the
D96-seed17 weights. That is only legitimate if patch 0005 is what it claims to
be: one standard-library include in one translation unit, with no change to
rules, sampling, encoding, loss or any other semantic version.

This records the old and new build identities, the exact patch text, the
declared version numbers on both sides, and a regression that replays the
development set with the current build and compares it episode by episode with
the S1R record. A header include that changed behaviour would move those
episodes; a build that merely compiles the same code will not.
"""
import argparse
import gzip
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha256(path):
    return __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()


def versions_now():
    from stsai.encoding import ENCODING_REVISION
    from stsai.native import SAMPLER_REVISION
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import LOSS_REVISION, SCHEMA_VERSION
    return {"observation_schema": SCHEMA_VERSION, "encoding_revision": ENCODING_REVISION,
            "loss_revision": LOSS_REVISION, "sampler_revision": SAMPLER_REVISION,
            "scenario_revision": SCENARIO_REVISION, "utility_revision": UTILITY_REVISION}


def replay_development_set(scenarios_path, checkpoint, recorded_path, limit=None):
    """Play the frozen development scenarios again and compare with the S1R record."""
    import numpy as np
    from stsai.model import ModelEvaluator
    from stsai.native import NativeBattle
    from stsai.objective import terminal_utility

    scenarios = json.loads(Path(scenarios_path).read_text())["scenarios"]
    if limit:
        scenarios = scenarios[:limit]
    recorded = {}
    for line in Path(recorded_path).read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            recorded[row["episode_index"]] = row
    agent = None
    evaluator = ModelEvaluator.from_checkpoint(str(checkpoint), "cpu")
    differences = []
    compared = 0
    for entry in scenarios:
        index = entry["index"]
        env = NativeBattle(entry["scenario"], entry["episode_seed"])
        obs = env.observe()
        actions = []
        for _ in range(256):
            if obs["terminal"]:
                break
            probs, _ = evaluator.evaluate(obs)
            choice = int(np.argmax(probs))
            actions.append(choice)
            obs = env.step(obs["actions"][choice])
        completed = bool(obs["terminal"])
        utility = terminal_utility(obs, 0.02) if completed else None
        # The S1R record is the student row for this scenario.
        candidates = [row for row in recorded.values()
                      if row["episode_index"] == index and row["agent"] == "M128-R0-s17-S1R"]
        if not candidates:
            continue
        row = candidates[0]
        agent = row["agent"]
        compared += 1
        same = (row["completed"] == completed and row["won"] == (bool(obs["won"]) if completed else None)
                and row["decisions"] == len(actions) and row["utility"] == utility
                and row["end_hp"] == obs["player"]["hp"])
        if not same:
            differences.append({"episode_index": index, "recorded": {k: row[k] for k in
                               ("won", "utility", "decisions", "end_hp", "completed")},
                               "replayed": {"won": bool(obs["won"]) if completed else None,
                                            "utility": utility, "decisions": len(actions),
                                            "end_hp": obs["player"]["hp"], "completed": completed}})
    return {"agent": agent, "compared": compared, "differences": differences,
            "identical": not differences}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="reports/s2_semantic_compatibility.json")
    parser.add_argument("--scenarios", default="runs/s1r_eval/dev_scenarios.json")
    parser.add_argument("--checkpoint", default="model/policy_weights.pt")
    parser.add_argument("--recorded", default="runs/s1r_eval/episodes.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    lock = json.loads((ROOT / "engine_lock.json").read_text())
    snapshot = json.loads((ROOT / "native_sources_manifest.json").read_text())
    s1r_manifests = json.loads((ROOT / "training/data_manifests.json").read_text())
    s1r_run = json.loads((ROOT / "runs/s1r/M128-R0-s17-S1R/model/run.json").read_text())

    patch = next(entry for entry in lock["patches"] if "0005" in entry["file"])
    patch_text = (ROOT / patch["file"]).read_text()
    old_patches = [entry for entry in lock["patches"] if "0005" not in entry["file"]]

    record = {
        "purpose": "Why the S1R data and weights stay valid under the S2 header patch.",
        "conclusion": ("patch 0005 adds one standard-library include to one translation unit; no "
                       "rule, sampler, encoding, loss, utility or scenario semantics change, so "
                       "the S1R shards, validation set and D96-seed17 weights are reusable"),
        "old_build": {
            "revision": lock["revision"],
            "patches": old_patches,
            "recorded_in": "training/data_manifests.json settings.engine, runs/s1r/.../run.json",
            "s1r_collection_engine": s1r_manifests["splits"]["train"]["settings"]["engine"],
            "s1r_run_backend": s1r_run["backend"],
        },
        "new_build": {
            "revision": lock["revision"],
            "patches": lock["patches"],
            "added": {"file": patch["file"], "sha256": patch["sha256"],
                      "patch_text": patch_text,
                      "diff_shape": "one added line: #include <algorithm>, before the existing "
                                    "first include, in src/combat/CardManager.cpp",
                      "why": "the GCC 14 review build failed on std::find in that file; GCC 12 "
                             "compiles it through a transitive include"},
            "snapshot_manifest_patch_order": snapshot["engine"]["patch_order"],
            "snapshot_archive_sha256": snapshot["archive_sha256"],
        },
        "versions": {"now": versions_now(),
                     "s1r_recorded": {"observation_schema": 4, "encoding_revision": 5,
                                      "loss_revision": 2,
                                      "sampler_revision": "public_history_candidate_sampling/2",
                                      "scenario_revision": 3, "utility_revision": 1},
                     "changed_by_this_patch": []},
        "regression": replay_development_set(ROOT / args.scenarios, ROOT / args.checkpoint,
                                             ROOT / args.recorded, args.limit),
        "not_claimed": ["the patch is not a claim that every other translation unit is portable",
                        "a clean replay is not original-game verification"],
    }
    record["version_match"] = (record["versions"]["now"] == record["versions"]["s1r_recorded"])
    if not record["version_match"]:
        record["conclusion"] = "VERSIONS DIFFER: the equivalence does not hold"
    Path(ROOT / args.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    regression = record["regression"]
    print(f"versions match: {record['version_match']}; replay {regression['compared']} episodes, "
          f"identical: {regression['identical']}")
    if not (record["version_match"] and regression["identical"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
