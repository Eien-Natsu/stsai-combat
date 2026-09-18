#!/usr/bin/env python3
"""Record where every artefact of this round came from.

    python scripts/gen_s1r_provenance.py --bundle <repo.bundle> --out <git_and_provenance.json>

Sources are identified by content hash, not by filename: the bundle is verified
with `git bundle verify` and hashed, data is identified by its collection
fingerprint and per-shard hashes, and the model by both the selected training
checkpoint's hash and the exported file's own hash. A reviewer can therefore
check that the tree, the data and the weights are the ones this record names.
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


def maybe(path):
    path = Path(path)
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size} \
        if path.is_file() else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    from stsai.encoding import ENCODING_REVISION, FEATURES, VOCAB
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import LOSS_REVISION, SCHEMA_VERSION, SAMPLER_NOT_APPLICABLE  # noqa: F401

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    bundle = Path(args.bundle)
    verify = subprocess.run(["git", "bundle", "verify", str(bundle)], cwd=ROOT,
                            capture_output=True, text=True)
    lock = json.loads((ROOT / "engine_lock.json").read_text())
    try:
        from stsai.native import SAMPLER_REVISION
    except Exception:
        SAMPLER_REVISION = "native module not importable here"

    data = json.loads((ROOT / "training/data_manifests.json").read_text())
    export = maybe(ROOT / "runs/s1r/M128-R0-s17-S1R/model/export.json")
    run = maybe(ROOT / "runs/s1r/M128-R0-s17-S1R/model/run.json")
    if export:
        export["content"] = json.loads((ROOT / export["path"]).read_text())

    record = {
        "purpose": "Provenance for the S1R review package.",
        "baseline_commit": json.loads((ROOT / "reports/s1r_protocol.json").read_text())["baseline"],
        "head": head, "branch": branch,
        "bundle": {"file": str(bundle), "sha256": sha256(bundle), "bytes": bundle.stat().st_size,
                   "verify_returncode": verify.returncode,
                   "verify_output": verify.stdout.strip() or verify.stderr.strip(),
                   "clone_command": f"git clone {bundle.name} repo && git -C repo checkout {head}"},
        "engine": {
            "url": lock["url"], "revision": lock["revision"],
            "json_submodule": lock["json_submodule"], "license_sha256": lock["license_sha256"],
            "patches": [{"file": entry["file"], "sha256": entry["sha256"]}
                        for entry in lock["patches"]],
        },
        "versions": {"observation_schema": SCHEMA_VERSION, "encoding_revision": ENCODING_REVISION,
                     "loss_revision": LOSS_REVISION, "utility_revision": UTILITY_REVISION,
                     "scenario_revision": SCENARIO_REVISION, "sampler_revision": SAMPLER_REVISION,
                     "features": FEATURES, "vocab": VOCAB},
        "data": {split: {"fingerprint": values["fingerprint"],
                         "settings": values["settings"],
                         "shards": len(values["shards"]),
                         "shards_sha256": values["shards"]}
                 for split, values in data["splits"].items()},
        "model": {"export_record": export, "training_run": run,
                  "weights": maybe(ROOT / "model/policy_weights.pt"),
                  "smoke_observations": maybe(ROOT / "model/smoke_observations.jsonl.gz"),
                  "smoke_expected": maybe(ROOT / "model/smoke_expected.json")},
        "evaluation": {"dev_scenarios": maybe(ROOT / "runs/s1r_eval/dev_scenarios.json"),
                       "paired_summary": maybe(ROOT / "reports/s1r_paired_summary.json")},
        "claim": "unverified simulator pilot with a declared sampling approximation; "
                 "game_differential_verified=false",
    }
    Path(args.out).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"provenance written to {args.out}; bundle verify rc={verify.returncode}")


if __name__ == "__main__":
    main()
