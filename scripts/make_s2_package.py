#!/usr/bin/env python3
"""Assemble stsai_s2_review_<sha>.zip.

    python scripts/make_s2_package.py [--out-dir delivery] [--docs delivery_docs/s2]

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
sys.path.insert(0, str(ROOT / "review"))

# The required inputs are data, not a list repeated here: the reviewer verifies a
# package against the same entries with review/check_review_inputs.py.
import package_contract as contract  # noqa: E402

FILES = [(entry["package_path"], entry["source_path"], True) for entry in contract.REQUIRED_INPUTS]


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
    parser.add_argument("--docs", default="delivery_docs/s2")
    parser.add_argument("--artifacts", default=str(ROOT),
                        help="root the run artefacts are read from; they are not tracked by git, "
                             "so this is how a package is rebuilt on a machine that only has a "
                             "checkout plus the release attachment")
    parser.add_argument("--lock", default=None,
                        help="JSON map of source path -> sha256; every artefact input is checked "
                             "against it before anything is packed")
    args = parser.parse_args()
    artifacts = Path(args.artifacts).resolve()
    lock = json.loads(Path(args.lock).read_text(encoding="utf-8")) if args.lock else {}
    lock = lock.get("sha256", lock)

    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    name = f"stsai_s2_review_{head[:7]}"
    out_dir = ROOT / args.out_dir
    staging = out_dir / name
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    missing, mismatched = [], []
    for entry in contract.REQUIRED_INPUTS:
        archive_path, source = entry["package_path"], entry["source_path"]
        src = contract.resolve_source(entry, ROOT, artifacts)
        if not src.is_file():
            missing.append(f"{source} (looked in {src})")
            continue
        expected = lock.get(source)
        if expected and sha256(src) != expected:
            mismatched.append(f"{source}: {sha256(src)} != the locked {expected}")
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
    if mismatched:
        raise SystemExit("inputs do not match the lock; nothing was packed: " + "; ".join(mismatched))
    if missing:
        raise SystemExit(f"missing required inputs: {missing}")

    sections = build_command_log(staging)

    bundle = staging / "repo.bundle"
    subprocess.run(["git", "bundle", "create", str(bundle), "--all"], cwd=ROOT, check=True,
                   capture_output=True)
    # The provenance names the bundle by hash, so it is written after the bundle.
    # It reads the same artefact root, so a package can be assembled on a machine
    # that only has a checkout plus the attachment.
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_s2_provenance.py"),
                    "--bundle", str(bundle), "--out", str(staging / "provenance.json"),
                    "--artifacts", str(artifacts)],
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
