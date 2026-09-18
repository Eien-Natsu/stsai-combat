#!/usr/bin/env python3
"""Assemble stsai_s1r_review_<sha>.zip from the artefacts this round produced.

    python scripts/make_s1r_package.py [--out-dir delivery] [--skip-model]

The package holds one actual ZIP under the project budget (files under 40, size
under 20 MB): the history as a bundle, the offline sources with their manifest,
the review scripts, the gate receipts, the raw logs they point at, the training
and evaluation records, and the selected inference weights. Nothing that is not
needed - no runs directory, no optimizer state, no virtualenv, no compiled
objects, no game files.

When the round did not train, the model, training and evaluation sections are
listed as NOT_RUN in INDEX.md and their files are omitted rather than shipped
empty.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (archive path, source path, required)
FILES = [
    ("protocol.json", "reports/s1r_protocol.json", True),
    # git_and_provenance.json is generated below: it names the bundle by hash, so
    # it cannot be written before the bundle exists.
    ("gate_receipts.json", "reports/gate_receipts.json", True),
    ("native_sources.tar.gz", "native_sources.tar.gz", True),
    ("native_sources_manifest.json", "native_sources_manifest.json", True),
    ("review/README.md", "review/README.md", True),
    ("review/run_review.py", "review/run_review.py", True),
    ("review/offline_native_build.py", "review/offline_native_build.py", True),
    ("review/counterfactual_replay.py", "review/counterfactual_replay.py", True),
    ("review/model_smoke.py", "review/model_smoke.py", True),
    ("audit/patch_reconstruction.json", "audit/patch_reconstruction.json", True),
    ("audit/public_memory_evidence.jsonl.gz", "audit/public_memory_evidence.jsonl.gz", True),
    ("audit/sampler_effect.json", "reports/s1r_sampler_effect.json", True),
    ("audit/collection_report.json", "reports/s1r_collection_report.json", True),
    ("tests/pytest.txt", "reports/s1r_pytest.txt", True),
    ("tests/junit.xml", "reports/s1r_junit.xml", True),
    ("training/run.json", "runs/s1r/M128-R0-s17-S1R/model/run.json", False),
    ("training/metrics.jsonl", "runs/s1r/M128-R0-s17-S1R/model/metrics.jsonl", False),
    ("training/summary.json", "runs/s1r/M128-R0-s17-S1R/model/training_summary.json", False),
    ("training/validation.jsonl", "runs/s1r/M128-R0-s17-S1R/model/validation.jsonl", False),
    ("training/data_manifests.json", "training/data_manifests.json", False),
    ("training/initial_scenarios.json", "training/initial_scenarios.json", False),
    ("model/policy_weights.pt", "model/policy_weights.pt", False),
    ("model/smoke_observations.jsonl.gz", "model/smoke_observations.jsonl.gz", False),
    ("model/smoke_expected.json", "model/smoke_expected.json", False),
    ("evaluation/dev_scenarios.json", "runs/s1r_eval/dev_scenarios.json", False),
    ("evaluation/episodes.jsonl", "runs/s1r_eval/episodes.jsonl", False),
    ("evaluation/decision_latency.jsonl.gz", "runs/s1r_eval/decision_latency.jsonl.gz", False),
    ("evaluation/paired_summary.json", "reports/s1r_paired_summary.json", False),
    ("evaluation/summary.json", "runs/s1r_eval/summary.json", False),
    ("reports/known_limitations.md", "reports/s1r_known_limitations.md", True),
    ("reports/command_log.txt", None, True),  # generated below
    ("INDEX.md", None, True),
    ("SUMMARY.md", None, True),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_command_log(staging):
    """One file with every raw log, sectioned by the path the receipts name."""
    sections = []
    for path in sorted((ROOT / "reports" / "s1r_gates").glob("*.txt")):
        sections.append((f"reports/s1r_gates/{path.name}", path.read_text(encoding="utf-8")))
    for path in sorted((ROOT / "logs").glob("*.log")):
        if path.name.startswith(("60_", "61_", "62_")):
            sections.append((f"logs/{path.name}", path.read_text(encoding="utf-8")))
    out = staging / "reports" / "command_log.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        handle.write("# Raw command output for the S1R round\n")
        handle.write("# Sections are named after the paths quoted in gate_receipts.json.\n")
        for name, text in sections:
            handle.write(f"\n===== {name} =====\n{text}")
    return len(sections)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="delivery")
    parser.add_argument("--delivery-docs", default="delivery_docs",
                        help="directory holding hand-written INDEX.md and SUMMARY.md")
    args = parser.parse_args()

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    short = head[:7]
    name = f"stsai_s1r_review_{short}"
    out_dir = ROOT / args.out_dir
    staging = out_dir / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    missing = []
    for archive_path, source, required in FILES:
        if source is None:
            continue
        src = ROOT / source
        if not src.is_file():
            if required:
                missing.append(source)
            continue
        dest = staging / archive_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    for doc in ("INDEX.md", "SUMMARY.md"):
        src = ROOT / args.delivery_docs / doc
        if not src.is_file():
            missing.append(str(src))
            continue
        shutil.copy2(src, staging / doc)
    if missing:
        raise SystemExit(f"missing required inputs: {missing}")

    sections = build_command_log(staging)

    bundle = staging / "repo.bundle"
    subprocess.run(["git", "bundle", "create", str(bundle), "--all"], cwd=ROOT, check=True,
                   capture_output=True)
    # The provenance names the bundle by hash, so it is written after the bundle.
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_s1r_provenance.py"),
                    "--bundle", str(bundle), "--out", str(staging / "git_and_provenance.json")],
                   cwd=ROOT, check=True)

    entries = sorted(p for p in staging.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    lines = [f"{sha256(p)}  {p.relative_to(staging).as_posix()}" for p in entries]
    (staging / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    zip_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))

    total = sum(p.stat().st_size for p in staging.rglob("*") if p.is_file())
    count = len([p for p in staging.rglob("*") if p.is_file()])
    print(f"{zip_path} ({zip_path.stat().st_size/1e6:.2f} MB zipped, "
          f"{count} files, {total/1e6:.2f} MB raw, {sections} log sections)")
    if count > 40:
        raise SystemExit(f"file budget exceeded: {count} > 40")
    if zip_path.stat().st_size > 40 * 1e6:
        raise SystemExit("archive exceeds the outer size limit")


if __name__ == "__main__":
    main()
