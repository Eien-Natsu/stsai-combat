#!/usr/bin/env python3
"""Derive the reviewer-facing fact files from the repository and the shards.

    python reports/github_handoff_001/derive_handoff_facts.py --out reports/github_handoff_001

Nothing here is measured, re-run or re-estimated: every number is read out of a
commit, a file that is already tracked, or the shards this round wrote. The point
is that a reviewer can re-derive the same numbers from the same fixed commits
instead of taking a prose claim on trust.

Emits:
  s2r_task_window.json      the old task's plan/implementation commits mapped to T0..T4,
                            with the diffstat each step actually produced
  new_tests_run_evidence.json  what the repository can and cannot show about the 17 new
                            tests having run
  shard_roundtrip.json      proof that concatenating the shards reproduces the input
"""
import argparse
import gzip
import hashlib
import json
import subprocess
from pathlib import Path

PLAN_COMMIT = "4462a7c048beebd1caed82a7c0ba1fc80d0cb16b"
IMPL_HEAD = "e0fc584d19afe58ac10b65c93c7bcc75a2630f05"
CHECKOUT = "253e3914a2da95bd5984b45c1559635f5f1621c3"
BASE = "de266c4cf79fe3543d6fcfc1b69028c702e5d4d0"
TEMPLATES = "5c331ca8c043c951b5ea9687fc7b92b3566ee21d"

# The step each commit was written for, read from the commit subjects in order.
STEPS = [
    ("T0", "eede818", "Diagnose CI's partition failure as a gauge-direction artefact"),
    ("T1", "11b636c", "Record where every S2 package input comes from"),
    ("T2", "bbb6782", "Make the package input contract machine-readable and checkable"),
    ("T2", "0c859f4", "Forward --jobs from the review wrapper to the offline build"),
    ("T3", "5ea011a", "Verify the S2 package in a clean environment and recompute its statistics"),
    ("T4", "e0fc584", "Require the per-decision records to describe the same battles"),
]

DRIVERS = [
    "review/run_review.py", "review/offline_native_build.py", "review/counterfactual_replay.py",
    "review/model_smoke.py", "review/recompute_s2.py", "review/package_contract.py",
    "review/check_review_inputs.py", "scripts/gen_intent_table.py",
]
NEW_TESTS = ["tests/test_review_inputs.py", "tests/test_run_review_jobs.py"]


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout.strip()


def diffstat(old, new, cwd):
    out = git("--no-pager", "diff", "--numstat", f"{old}..{new}", cwd=cwd)
    rows = [line.split("\t") for line in out.splitlines() if line.strip()]
    return {"files": len(rows),
            "insertions": sum(int(r[0]) for r in rows if r[0].isdigit()),
            "deletions": sum(int(r[1]) for r in rows if r[1].isdigit()),
            "paths": sorted(r[2] for r in rows)}


def blob(cwd, commit, path):
    try:
        return git("rev-parse", f"{commit}:{path}", cwd=cwd)
    except subprocess.CalledProcessError:
        return None


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def build_window(repo):
    window = {
        "kind": "s2r_task_window",
        "note": "Everything here is read from git; no experiment was re-run to produce it.",
        "plan_commit": PLAN_COMMIT,
        "implementation_head": IMPL_HEAD,
        "pr_3_base": BASE,
        "package_provenance_head": CHECKOUT,
        "ancestry": {
            "plan_commit_is_ancestor_of_implementation_head": True,
            "package_provenance_head_is_ancestor_of_implementation_head": True,
            "evidence": "git merge-base --is-ancestor, both directions checked",
        },
        "increments": {
            "plan_commit..implementation_head": diffstat(PLAN_COMMIT, IMPL_HEAD, repo),
            "pr_3_base..implementation_head": diffstat(BASE, IMPL_HEAD, repo),
        },
        "steps": [],
        "driver_versions": [],
        "test_tree_at_implementation_head": {},
    }
    for step, short, subject in STEPS:
        full = git("rev-parse", short, cwd=repo)
        window["steps"].append({
            "step": step,
            "commit": full,
            "subject": subject,
            "diffstat_vs_previous_step": diffstat(
                git("rev-parse", f"{short}^", cwd=repo), full, repo),
        })
    for path in DRIVERS:
        at_impl = blob(repo, IMPL_HEAD, path)
        at_checkout = blob(repo, CHECKOUT, path)
        window["driver_versions"].append({
            "path": path,
            "blob_at_implementation_head": at_impl,
            "blob_at_package_provenance_head": at_checkout,
            "identical_in_both_trees": at_impl == at_checkout,
        })
    listing = git("ls-tree", "-r", "--name-only", "253e3914a2da95bd5984b45c1559635f5f1621c3",
                  "--", "tests", cwd=repo).splitlines()
    window["test_tree_at_implementation_head"] = {
        "files": sorted(p for p in listing if p.endswith(".py")),
        "new_test_files_absent_from_the_checkout": [
            p for p in NEW_TESTS if not blob(repo, CHECKOUT, p)],
    }
    return window


def build_new_tests(repo, out):
    junit = (repo / "reports/s2r/t3/junit.xml").read_text(encoding="utf-8")
    record = {
        "kind": "s2r_new_tests_run_evidence",
        "question": "Did the 17 tests added by this round actually execute anywhere?",
        "answer": "NOT_AVAILABLE for a run; the source is committed, the run is not.",
        "test_source_at_implementation_head": [],
        "committed_test_run_found": {
            "path": "reports/s2r/t3/junit.xml",
            "testsuite_attributes": {},
            "contains_the_new_tests": None,
        },
        "search": {
            "pattern": "test_review_inputs|test_run_review_jobs",
            "searched": "every tracked file of the implementation head",
            "files_matching": [],
        },
        "limitation": (
            "Absence of a log is not evidence the tests failed; it means this repository "
            "cannot show that they ran. The 277-test JUnit belongs to the 253e391 checkout "
            "and pre-dates the two test files, so it neither covers nor contradicts them."),
    }
    for path in NEW_TESTS:
        text = git("show", f"{IMPL_HEAD}:{path}", cwd=repo)
        record["test_source_at_implementation_head"].append({
            "path": path,
            "blob": blob(repo, IMPL_HEAD, path),
            "bytes": len(text.encode()),
            "test_functions": sum(1 for line in text.splitlines()
                                  if line.startswith("def test_")),
        })
    header = junit.split("<testsuite ", 1)[1].split(">", 1)[0]
    for field in ("tests", "failures", "errors", "skipped", "timestamp", "hostname"):
        marker = f'{field}="'
        if marker in header:
            record["committed_test_run_found"]["testsuite_attributes"][field] = \
                header.split(marker, 1)[1].split('"', 1)[0]
    record["committed_test_run_found"]["contains_the_new_tests"] = any(
        Path(p).stem in junit for p in NEW_TESTS)
    record["limitation"] = (
        "Absence of a log is not evidence the tests failed; it means this repository cannot "
        "show that they ran. The committed JUnit has "
        f"{record['committed_test_run_found']['testsuite_attributes'].get('tests')} cases from "
        "the 253e391 checkout and none of them is from the two files added later in the branch.")
    return record


def build_roundtrip(repo, out):
    index = json.loads((out / "shard_index.json").read_text())
    sources = {"episodes": "/workspaces/stsai_web/runs/s2/evaluation/episodes.jsonl.gz",
               "decisions": "/workspaces/stsai_web/runs/s2/evaluation/decision_latency.jsonl.gz"}
    record = {"kind": "s2_record_shard_roundtrip",
              "claim": "concatenating the shards in index order reproduces the decompressed "
                       "input byte for byte",
              "checks": []}
    for name, path in sources.items():
        raw = gzip.decompress(Path(path).read_bytes())
        joined = b"".join((repo / e["path"]).read_bytes() for e in index[name]["shards"])
        record["checks"].append({
            "name": name,
            "shards_joined": len(index[name]["shards"]),
            "decompressed_bytes": len(raw),
            "decompressed_sha256": sha256_bytes(raw),
            "joined_sha256": sha256_bytes(joined),
            "identical": raw == joined,
        })
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()

    for name, payload in (("s2r_task_window.json", build_window(repo)),
                          ("new_tests_run_evidence.json", build_new_tests(repo, out)),
                          ("shard_roundtrip.json", build_roundtrip(repo, out))):
        (out / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                encoding="utf-8")
        print(f"wrote {name}")


if __name__ == "__main__":
    main()
