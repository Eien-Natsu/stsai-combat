#!/usr/bin/env python3
"""Emit handoffs/GITHUB-HANDOFF-001/files.json from what is actually on disk.

    python reports/github_handoff_001/make_files_json.py

Every byte count and digest here is computed, never typed. A hand-written index is
how a wrong hash gets published, and a wrong hash in an evidence index is worse
than no index at all.

`files.json` itself and `publish_receipt.json` are deliberately absent from their
own listing: neither can contain its own digest. The index says so explicitly
rather than leaving a hole a reader has to notice.
"""
import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HANDOFF = REPO / "handoffs" / "GITHUB-HANDOFF-001"

CONTROL_FILES = [
    "AGENTS.md", "PROJECT_MAINLINE.md", "NEXT_ACTIONS.md", "SESSION_STATE.json",
    ".github/agent_handoff_template.md", ".github/review_handoff_template.md",
    ".github/next_actions_template.md", ".github/evidence_index_template.md",
    ".github/pull_request_template.md", "handoffs/README.md",
    "handoffs/BOOTSTRAP-GITHUB-ONLY/REVIEW.md",
    "handoffs/BOOTSTRAP-GITHUB-ONLY/github_snapshot.json",
]

EXCLUDED = {"handoffs/GITHUB-HANDOFF-001/files.json",
            "handoffs/GITHUB-HANDOFF-001/publish_receipt.json"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=False).stdout.strip()


def blob_of(rel):
    out = git("hash-object", "--", rel)
    return out or None


def describe(rel, origin, note, records=None, keys=None):
    path = REPO / rel
    entry = {
        "path": rel,
        "origin": origin,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "git_blob": blob_of(rel),
        "note": note,
    }
    if records is not None:
        entry["records"] = records
    if keys is not None:
        entry["key_range"] = keys
    return entry


def main():
    entries = []
    for rel in CONTROL_FILES:
        entries.append(describe(
            rel, "imported verbatim from plan commit 5c331ca8",
            "control document; not written by this round"))

    index = json.loads((REPO / "reports/github_handoff_001/shard_index.json").read_text())
    for name, label in (("episodes", "per-episode record"), ("decisions", "per-decision record")):
        for shard in index[name]["shards"]:
            entries.append(describe(
                shard["path"], "S2 evaluation records, recovered from the ignored runs/ tree",
                f"{label} text shard, verbatim lines",
                records=shard["records"],
                keys=f"record index {shard['first_record_index']}.."
                     f"{shard['first_record_index'] + shard['records'] - 1}"))

    for rel, note in (
        ("reports/github_handoff_001/shard_index.json",
         "shard paths, byte counts, digests, record ranges; decompressed and compressed input digests"),
        ("reports/github_handoff_001/key_coverage.json",
         "episode key grid and decision-to-episode linkage, derived from the records"),
        ("reports/github_handoff_001/shard_roundtrip.json",
         "proof that the shards concatenate back to the decompressed input"),
        ("reports/github_handoff_001/s2r_task_window.json",
         "old task commits mapped to T0..T4 with diffstats, from git"),
        ("reports/github_handoff_001/new_tests_run_evidence.json",
         "what the repository can and cannot show about the 17 new tests"),
        ("reports/github_handoff_001/convert_s2_records.py",
         "the converter that produced the shards"),
        ("reports/github_handoff_001/derive_handoff_facts.py",
         "the derivation that produced the fact files"),
        ("reports/github_handoff_001/make_files_json.py", "this generator"),
        ("reports/github_handoff_001/README.md", "reading guide for the directory"),
        ("reports/github_handoff_001/package/MANIFEST.sha256",
         "verbatim copy of the zip's manifest, so the 33-member listing is readable"),
        ("reports/github_handoff_001/package/provenance.json",
         "verbatim copy of the zip's provenance record"),
        ("reports/github_handoff_001/package/INDEX.md", "verbatim copy from the zip"),
        ("reports/github_handoff_001/package/known_limitations.md", "verbatim copy from the zip"),
        ("reports/github_handoff_001/package/commands_and_limits.md", "verbatim copy from the zip"),
        ("reports/github_handoff_001/package/command_log.txt", "verbatim copy from the zip"),
        ("reports/github_handoff_001/package/semantic_compatibility.json", "verbatim copy from the zip"),
        ("handoffs/GITHUB-HANDOFF-001/EXECUTION.md", "this round's execution record"),
        ("handoffs/GITHUB-HANDOFF-001/EVIDENCE_INDEX.md", "the index a reviewer reads"),
        ("handoffs/GITHUB-HANDOFF-001/clarifications.md",
         "precise reading of the isolation, cold-review and hash-semantics claims"),
        ("handoffs/GITHUB-HANDOFF-001/command_versions.json", "driver vs code-under-test per command"),
        ("handoffs/GITHUB-HANDOFF-001/budget.json", "old-range and this-round budget accounting"),
    ):
        entries.append(describe(rel, "written by this round", note))

    payload = {
        "kind": "handoff_files",
        "task_id": "GITHUB-HANDOFF-001",
        "plan_commit": "5c331ca8c043c951b5ea9687fc7b92b3566ee21d",
        "code_base": "e0fc584d19afe58ac10b65c93c7bcc75a2630f05",
        "self_reference": {
            "excluded": sorted(EXCLUDED),
            "reason": "a file cannot carry its own digest; these two are named here instead",
        },
        "counts": {"files": len(entries),
                   "total_bytes": sum(e["bytes"] for e in entries)},
        "files": sorted(entries, key=lambda e: e["path"]),
    }
    out = HANDOFF / "files.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(REPO)} with {len(entries)} entries, "
          f"{payload['counts']['total_bytes']} bytes")
    missing = [e["path"] for e in entries if e["git_blob"] is None]
    if missing:
        print("NOT YET TRACKED (expected before the first commit):")
        for path in missing:
            print("  ", path)


if __name__ == "__main__":
    main()
