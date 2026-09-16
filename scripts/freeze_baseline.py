#!/usr/bin/env python3
"""Freeze everything a later result must be traceable to.

A run is only comparable to another run when the code, the engine, the patch
series, the input semantics and the fixture generator all match. This writes
that set out as one machine-readable record; the diagnosis and any evaluation
report should quote its hash rather than restating the fields by hand.
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
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def git(*args):
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="reports/baseline_freeze.json")
    args = parser.parse_args()

    from stsai.encoding import ENCODING_REVISION
    from stsai.objective import UTILITY_REVISION
    from stsai.scenarios import SCENARIO_REVISION
    from stsai.util import SCHEMA_VERSION

    try:
        from stsai.native import SAMPLER_REVISION, engine_metadata
        engine = engine_metadata()
    except (ImportError, RuntimeError) as exc:
        engine = {"error": str(exc)}
        SAMPLER_REVISION = None

    lock = json.loads((ROOT / "engine_lock.json").read_text(encoding="utf-8"))
    module = next(iter((ROOT / "src" / "stsai").glob("_lightspeed*.so")), None)

    record = {
        "purpose": "Baseline for comparability. Quote this hash instead of restating fields.",
        "git": {
            "commit": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
            "worktree_status": git("status", "--porcelain"),
        },
        "upstream_engine": {
            "url": lock.get("url"),
            "revision": lock.get("revision"),
            "json_submodule": lock.get("json_submodule"),
            "license_sha256": lock.get("license_sha256"),
            "patches": lock.get("patches", []),
            "build_info": engine,
        },
        "built_module_sha256": sha256(module) if module else None,
        "built_module": str(module.relative_to(ROOT)) if module else None,
        "input_semantics": {
            "observation_schema": SCHEMA_VERSION,
            "encoding_revision": ENCODING_REVISION,
            "utility_revision": UTILITY_REVISION,
            "scenario_revision": SCENARIO_REVISION,
            "sampler_revision": SAMPLER_REVISION,
            "belief_model": engine.get("belief_model"),
        },
        "checkpoints": {str(p.relative_to(ROOT)): sha256(p)
                        for p in sorted((ROOT / "runs").glob("*/model/*.pt"))},
        "python": sys.version,
    }
    try:
        import torch
        import numpy
        record["torch"] = torch.__version__
        record["torch_cuda"] = torch.version.cuda
        record["numpy"] = numpy.__version__
    except ImportError:
        pass

    import os
    record["built_module_mtime"] = os.path.getmtime(module) if module else None
    record["source_files"] = {
        str(p.relative_to(ROOT)): sha256(p)
        for p in sorted(list((ROOT / "src" / "stsai").glob("*.py")) + [ROOT / "native" / "bridge.cpp"])
    }
    record["baseline_id"] = hashlib.sha256(
        json.dumps({k: v for k, v in record.items() if k != "baseline_id"},
                   sort_keys=True, default=str).encode()).hexdigest()

    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in record.items()
                      if k not in ("source_files", "checkpoints", "git")}, indent=2, default=str))
    print("\nwrote", out)


if __name__ == "__main__":
    main()
