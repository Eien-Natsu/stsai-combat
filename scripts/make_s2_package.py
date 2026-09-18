#!/usr/bin/env python3
"""Assemble stsai_s2_review_<sha>.zip.

    python scripts/make_s2_package.py [--out-dir delivery] [--docs delivery_docs_s2]

The package holds one ZIP inside the project budget: the history as a bundle,
the five-patch offline sources with their manifest, the review scripts, the
protocol, the compatibility argument, the training records for all six runs,
the one shipped inference weight, and the full evaluation. Nothing else - no
runs directory, no optimizer state, no virtualenv, no compiled objects, no game
files.

Only D384_s17's weights are shipped, as pre-registered. The other five runs
travel as their configs, selected steps and hashes, which is enough to check the
records and regenerate the weights without carrying five more files.
"""
import argparse
import hashlib
import gzip
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FILES = [
    ("protocol.json", "reports/s2_volume_protocol.json", True),
    ("semantic_compatibility.json", "reports/s2_semantic_compatibility.json", True),
    ("native_sources.tar.gz", "native_sources.tar.gz", True),
    ("native_sources_manifest.json", "native_sources_manifest.json", True),
    ("review/README.md", "review/README.md", True),
    ("review/run_review.py", "review/run_review.py", True),
    ("review/offline_native_build.py", "review/offline_native_build.py", True),
    ("review/counterfactual_replay.py", "review/counterfactual_replay.py", True),
    ("review/model_smoke.py", "review/model_smoke.py", True),
    ("review/recompute_s2.py", "review/recompute_s2.py", True),
    ("data/initial_scenarios.json.gz", "runs/s2/package_data/data/initial_scenarios.json.gz", True),
    ("data/composition_and_shards.json", "runs/s2/package_data/data/composition_and_shards.json", True),
    ("data/coverage.json", "runs/s2/package_data/data/coverage.json", True),
    ("training/runs.json", "training/runs.json", True),
    ("training/metrics.jsonl.gz", "training/metrics.jsonl.gz", True),
    ("training/validation.jsonl.gz", "training/validation.jsonl.gz", True),
    ("training/selected_summary.csv", "training/selected_summary.csv", True),
    ("model/D384_s17_selected.pt", "model/D384_s17_selected.pt", True),
    ("model/smoke_observations.jsonl.gz", "model/smoke_observations.jsonl.gz", True),
    ("model/smoke_expected.json", "model/smoke_expected.json", True),
    ("evaluation/scenarios.json.gz", "runs/s2/package_data/evaluation/scenarios.json.gz", True),
    ("evaluation/episodes.jsonl.gz", "runs/s2/evaluation/episodes.jsonl.gz", True),
    ("evaluation/decision_latency.jsonl.gz", "runs/s2/evaluation/decision_latency.jsonl.gz", True),
    ("evaluation/paired_summary.json", "reports/s2_paired_summary.json", True),
    ("tests/junit.xml", "reports/s2_junit.xml", True),
    ("reports/known_limitations.md", "reports/s2_known_limitations.md", True),
    ("reports/commands_and_limits.md", "reports/s2_commands_and_limits.md", True),
    # provenance.json, repo.bundle, INDEX.md, SUMMARY.md and report command_log.txt
    # are generated below, so they are not listed here.
    ("tests/build_and_test.log.gz", "reports/s2_build_and_test.log", True),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_command_log(staging):
    sections = []
    for name in ("s2_build_and_test.log", "s2_evaluation.log", "s2_training.log"):
        path = ROOT / "reports" / name
        if path.is_file():
            sections.append((f"reports/{name}", path.read_text(encoding="utf-8")))
    for path in sorted((ROOT / "logs").glob("71_s2_train_*.log")):
        sections.append((f"logs/{path.name}", path.read_text(encoding="utf-8")))
    for path in sorted((ROOT / "reports").glob("s2_gates/*.txt")) if (ROOT / "reports/s2_gates").is_dir() else []:
        sections.append((f"reports/s2_gates/{path.name}", path.read_text(encoding="utf-8")))
    out = staging / "reports" / "command_log.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        handle.write("# Raw command output for the S2 round\n")
        for name, text in sections:
            handle.write(f"\n===== {name} =====\n{text}")
    return len(sections)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="delivery")
    parser.add_argument("--docs", default="delivery_docs_s2")
    args = parser.parse_args()

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    name = f"stsai_s2_review_{head[:7]}"
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
        if archive_path.endswith(".gz") and source.endswith(".log"):
            # long logs ship gzipped to stay inside the budget
            with gzip.open(dest, "wt", encoding="utf-8") as handle:
                handle.write(src.read_text(encoding="utf-8"))
        else:
            shutil.copy2(src, dest)

    for doc in ("INDEX.md", "SUMMARY.md"):
        src = ROOT / args.docs / doc
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
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_s2_provenance.py"),
                    "--bundle", str(bundle), "--out", str(staging / "provenance.json")],
                   cwd=ROOT, check=True)

    entries = sorted(p for p in staging.rglob("*") if p.is_file() and p.name != "MANIFEST.sha256")
    (staging / "MANIFEST.sha256").write_text(
        "\n".join(f"{sha256(p)}  {p.relative_to(staging).as_posix()}" for p in entries) + "\n",
        encoding="utf-8")

    zip_path = out_dir / f"{name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(staging))

    count = len([p for p in staging.rglob("*") if p.is_file()])
    print(f"{zip_path} ({zip_path.stat().st_size/1e6:.2f} MB zipped, {count} files, "
          f"{sections} log sections)")
    if count > 40:
        raise SystemExit(f"file budget exceeded: {count} > 40")
    if zip_path.stat().st_size > 40 * 1e6:
        raise SystemExit("archive exceeds the outer size limit")


if __name__ == "__main__":
    main()
