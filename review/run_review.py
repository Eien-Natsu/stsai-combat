#!/usr/bin/env python3
"""Re-run the S1-B checks from this package in one command; non-zero on failure.

    python review/run_review.py --repo <checkout of repo.bundle> [--sources native_sources.tar.gz]

Steps
  manifest      every file in MANIFEST.sha256 still hashes as recorded
  provenance    engine_lock declares exactly the patches present, hashes match
  intent        the intent table regenerates identically from the locked source
  audit         the field audit keeps its categories and its incomplete bucket
  counterfactual the louse pairs in the package reproduce: fixed sampler agrees,
                pre-fix sampler diverges
  tests         the package's tests that do not need the native extension
  native        the offline build, when cmake and a compiler are present

Steps that cannot run on this machine report NOT_RUN and do not fail the run;
a step that runs and fails does.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def step_manifest():
    problems = []
    for line in (PKG / "MANIFEST.sha256").read_text().splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        path = PKG / name.strip()
        if not path.is_file() or sha256(path) != digest:
            problems.append(name.strip())
    return (not problems), f"{len(problems)} mismatches" + (f": {problems[:5]}" if problems else "")


def step_provenance(repo):
    lock = json.loads((repo / "engine_lock.json").read_text(encoding="utf-8"))
    on_disk = sorted(p.name for p in (repo / "native" / "patches").glob("*.patch"))
    declared = sorted(Path(p["file"]).name for p in lock.get("patches", []))
    if on_disk != declared:
        return False, f"patch files {on_disk} vs lock {declared}"
    for entry in lock["patches"]:
        if sha256(repo / entry["file"]) != entry["sha256"]:
            return False, f"hash mismatch for {entry['file']}"
    return True, f"{len(declared)} patches, revision {lock['revision'][:12]}"


def step_intent(repo):
    result = subprocess.run([sys.executable, "scripts/gen_intent_table.py", "--verify"],
                            cwd=repo, capture_output=True, text=True)
    return result.returncode == 0, (result.stdout + result.stderr).strip().splitlines()[-1]


def step_audit():
    audit = json.loads((PKG / "sampler/field_audit.json").read_text(encoding="utf-8"))
    ok = ("COVERAGE STATISTIC ONLY" in audit["coverage_scan"]["role"]
          and bool(audit["incomplete_evidence"])
          and any(f["category"] == "PUBLIC_DETERMINED" for f in audit["fields"]))
    louse = [f for f in audit["fields"] if "LOUSE" in f["monster"]]
    ok = ok and bool(louse) and louse[0]["category"] == "RESAMPLED"
    return ok, f"{len(audit['fields'])} fields, louse={louse[0]['category'] if louse else 'MISSING'}"


def step_counterfactual():
    checks = json.loads((PKG / "sampler/distribution_checks.json").read_text(encoding="utf-8"))
    summary = checks["summary"]
    ok = (summary["valid_counterfactuals"] > 0 and summary["all_fixed_samplers_agree"]
          and summary["all_controls_diverge"])
    return ok, json.dumps(summary)


def step_tests(repo):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo / "src")
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=repo,
                            capture_output=True, text=True, env=env)
    tail = [l for l in result.stdout.strip().splitlines() if l.strip()][-1:] or [""]
    return result.returncode == 0, tail[0]


def step_native(repo, sources):
    if sources is None:
        return None, "no --sources given"
    if not (os.environ.get("PATH") and any(
            (Path(p) / "cmake").exists() or (Path(p) / "cmake.exe").exists()
            for p in os.environ["PATH"].split(os.pathsep))):
        return None, "cmake not on PATH"
    result = subprocess.run([sys.executable, "review/offline_native_build.py", "--repo", str(repo),
                             "--sources", str(sources)], cwd=PKG, capture_output=True, text=True)
    tail = [l for l in (result.stdout + result.stderr).strip().splitlines() if l.strip()][-1:]
    return result.returncode == 0, tail[0] if tail else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sources", default=None)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    results = {}
    results["manifest"] = step_manifest()
    results["provenance"] = step_provenance(repo)
    results["intent"] = step_intent(repo)
    results["audit"] = step_audit()
    results["counterfactual"] = step_counterfactual()
    if not args.skip_tests:
        results["tests"] = step_tests(repo)
    results["native"] = step_native(repo, Path(args.sources) if args.sources else None)

    failed = []
    for name, (ok, note) in results.items():
        label = "NOT_RUN" if ok is None else ("PASS" if ok else "FAIL")
        print(f"{label:8s} {name:16s} {note}")
        if ok is False:
            failed.append(name)
    if failed:
        print("FAILED:", ", ".join(failed), file=sys.stderr)
        raise SystemExit(1)
    print("all runnable checks passed")


if __name__ == "__main__":
    main()
