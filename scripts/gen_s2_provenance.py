#!/usr/bin/env python3
"""Record where every S2 artefact came from, by content hash.

    python scripts/gen_s2_provenance.py --bundle <repo.bundle> --out provenance.json

Sources are identified by hash rather than by filename: the bundle is verified
with `git bundle verify` and hashed, each training run is named by its config,
its data fingerprint and its selected checkpoint's hash, the data by shard and
normalised-sample hashes, and the evaluation by the hashes of both frozen sets
plus the per-episode file the numbers were computed from.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def entry(path):
    path = Path(path)
    if not path.is_file():
        return None
    return {"file": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from stsai.encoding import ENCODING_REVISION
    from stsai.native import SAMPLER_REVISION
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import LOSS_REVISION, SCHEMA_VERSION

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    bundle = Path(args.bundle)
    verify = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=ROOT,
                            capture_output=True, text=True)
    lock = json.loads((ROOT / "engine_lock.json").read_text())
    runs = json.loads((ROOT / "training/runs.json").read_text())
    lists = json.loads((ROOT / "reports/s2_dev_lists.json").read_text())
    add288 = json.loads((ROOT / "reports/s2_collection_report.json").read_text())
    environment = json.loads((ROOT / "runs/s2/evaluation/environment.json").read_text())

    record = {
        "purpose": "Provenance for the S2 review package.",
        "protocol": {
            "baseline_commit": "c31ba2f02dccb92ff96d593e14ed5b3dd2644183",
            "protocol_file": entry(ROOT / "reports/s2_volume_protocol.json"),
        },
        "head": head, "branch": branch,
        "bundle": {"file": str(bundle), "sha256": sha256(bundle), "bytes": bundle.stat().st_size,
                   "verify_returncode": verify.returncode,
                   "verify_output": verify.stdout.strip() or verify.stderr.strip(),
                   "clone_command": f"git clone {bundle.name} repo && git -C repo checkout {head}"},
        "engine": {"url": lock["url"], "revision": lock["revision"],
                   "json_submodule": lock["json_submodule"],
                   "license_sha256": lock["license_sha256"],
                   "patches": [{"file": e["file"], "sha256": e["sha256"]} for e in lock["patches"]]},
        "versions": {"observation_schema": SCHEMA_VERSION, "encoding_revision": ENCODING_REVISION,
                     "loss_revision": LOSS_REVISION, "utility_revision": UTILITY_REVISION,
                     "scenario_revision": SCENARIO_REVISION, "sampler_revision": SAMPLER_REVISION},
        "data": {
            "D96_manifest_sha256": lists["shards"]["D96_manifest_sha256"],
            "V24_manifest_sha256": lists["shards"]["V24_manifest_sha256"],
            "D96_shards": len(json.loads((ROOT / "training/data_manifests.json").read_text())["splits"]["train"]["shards"]),
            "Dadd288_shards": len(add288["shards"]),
            "Dadd288_normalized_sample_hash": add288["normalized_sample_hash"],
            "D384_episodes": 96 + 288,
            "dev_sets": {"DEV_OLD256": lists["lists"]["DEV_OLD256"]["sha256"],
                         "DEV_PROBE256": lists["lists"]["DEV_PROBE256"]["sha256"]},
        },
        "training": {"runs": [
            {"run": r["run"], "data": r["data"], "init_seed": r["init_seed"],
             "reused_from": r.get("reused_from"), "steps": r["steps"],
             "selected_step": r["selected"]["step"], "selected_sha256": r["selected"]["sha256"],
             "last_step": r["last"]["step"], "last_sha256": r["last"]["sha256"],
             "data_fingerprint": r["data_fingerprint"]} for r in runs["runs"]]},
        "model": {"shipped": entry(ROOT / "model/D384_s17_selected.pt"),
                  "smoke_observations": entry(ROOT / "model/smoke_observations.jsonl.gz"),
                  "smoke_expected": entry(ROOT / "model/smoke_expected.json")},
        "evaluation": {"environment": environment,
                       "episodes": entry(ROOT / "runs/s2/evaluation/episodes.jsonl.gz"),
                       "decisions": entry(ROOT / "runs/s2/evaluation/decision_latency.jsonl.gz"),
                       "paired_summary": entry(ROOT / "reports/s2_paired_summary.json")},
        "claim": "unverified simulator pilot with a declared sampling approximation; "
                 "game_differential_verified=false",
    }
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"provenance written to {args.out}; bundle verify rc={verify.returncode}")


if __name__ == "__main__":
    main()
